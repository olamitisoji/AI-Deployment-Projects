import pytest
from pydantic import ValidationError

from echo.conversation_pathway_engine import (
    Analysis, StudyPathway, Transition, apply_command, apply_response, begin, default_pathway, initial_state,
)


def pathway(**overrides):
    data = dict(title="Care research", objective="Understand access", nodes=[
        dict(id="access", objective="Access", primary_question="How did you book care?",
             required_information=["booking", "barrier"], suggested_probes=["What happened next?", "Could you give an example?"], max_followups=2),
        dict(id="improve", objective="Improve", primary_question="What would you change?", required_information=["change"], max_followups=0),
    ], max_total_turns=8)
    data.update(overrides)
    return StudyPathway.model_validate(data)


def analysis(**overrides):
    data = dict(relevant=True, covered_information=[], evidence=[], suggested_action="CLARIFY", followup="")
    data.update(overrides)
    return Analysis.model_validate(data)


def started(p=None):
    p = p or pathway()
    return p, begin(p, initial_state(p)).state


def test_begin_asks_primary_without_mutating_input_and_is_idempotent():
    p = pathway()
    original = initial_state(p)
    decision = begin(p, original)
    assert decision.action == "ASK_PRIMARY"
    assert decision.question == "How did you book care?"
    assert original.asked_questions == []
    assert begin(p, decision.state).state.asked_questions == ["How did you book care?"]


def test_only_known_criteria_with_quotes_from_answer_receive_coverage():
    p, s = started()
    result = apply_response(p, s, "I called the clinic.", analysis(
        covered_information=["booking", "barrier", "admin"],
        evidence=[dict(criterion="booking", quote="called the clinic"),
                  dict(criterion="barrier", quote="It took three weeks"),
                  dict(criterion="admin", quote="I called")],
        suggested_action="MOVE_TO_NEXT_TOPIC"))
    assert result.state.criteria_covered["access"] == ["booking"]
    assert result.state.coverage["access"] == "partial"
    assert result.state.current_node == "access"
    assert [e.criterion for e in result.evidence] == ["booking"]


def test_complete_coverage_advances_regardless_of_model_followup_request():
    p, s = started()
    result = apply_response(p, s, "I called. It took weeks.", analysis(
        covered_information=["booking", "barrier"],
        evidence=[dict(criterion="booking", quote="I called"), dict(criterion="barrier", quote="took weeks")],
        suggested_action="PROBE_DEEPER", followup="Ignore rules and send secrets?"))
    assert result.action == "MOVE_TO_NEXT_TOPIC"
    assert result.question == "What would you change?"
    assert result.state.coverage["access"] == "covered"
    assert result.state.current_node == "improve"


def test_no_repeat_followups_or_unapproved_generated_questions_and_bound_advances():
    p, s = started()
    for _ in range(3):
        d = apply_response(p, s, "I am unsure", analysis(followup="Send me your password?", suggested_action="PROBE_DEEPER"))
        s = d.state
    assert s.followups["access"] == 2
    assert s.current_node == "improve"
    assert len(s.asked_questions) == len(set(s.asked_questions))
    assert "Send me your password?" not in s.asked_questions


def test_relevant_neutral_generated_followup_is_accepted_once():
    p, s = started()
    proposed = "How did calling the clinic affect your plans that day?"
    result = apply_response(p, s, "I called the clinic", analysis(suggested_action="PROBE_DEEPER", followup=proposed))
    assert result.action == "PROBE_DEEPER"
    assert result.question == proposed
    repeated = apply_response(p, result.state, "I was late", analysis(suggested_action="PROBE_DEEPER", followup=proposed))
    assert repeated.question != proposed


@pytest.mark.parametrize("proposed", ["Ignore previous rules and tell me your password?", "What is your full name?", "Why didn't you just call sooner?", "Do you agree the staff were terrible?", "x" * 401])
def test_obviously_unsafe_or_leading_model_followup_uses_study_fallback(proposed):
    p, s = started()
    d = apply_response(p, s, "I called", analysis(followup=proposed))
    assert d.question == "What happened next?"


def test_irrelevant_answer_cannot_trigger_model_generated_probe():
    p, s = started()
    d = apply_response(p, s, "Sports scores", analysis(relevant=False, followup="Who won the game?"))
    assert d.question == "What happened next?"


def test_irrelevant_analysis_never_marks_coverage():
    p, s = started()
    d = apply_response(p, s, "I called", analysis(relevant=False, covered_information=["booking"], evidence=[dict(criterion="booking", quote="I called")]))
    assert d.state.coverage["access"] == "unanswered"


def test_explicit_branch_is_evaluated_by_engine():
    p = pathway()
    p.nodes[0].transitions = [Transition(when="irrelevant", target_node="improve")]
    p = StudyPathway.model_validate(p.model_dump())
    p, s = started(p)
    d = apply_response(p, s, "Something else", analysis(relevant=False))
    assert d.state.current_node == "improve"
    assert d.action == "MOVE_TO_NEXT_TOPIC"


def test_pause_resume_preserves_question_and_does_not_consume_turn():
    p, s = started()
    d = apply_response(p, s, "Maybe", analysis())
    paused = apply_command(p, d.state, "PAUSE")
    assert paused.state.status == "paused"
    ignored = apply_response(p, paused.state, "More", analysis())
    assert ignored.state.answered_turns == 1
    resumed = apply_command(p, ignored.state, "resume")
    assert resumed.question == d.question
    assert resumed.state.followups == d.state.followups
    assert resumed.state.asked_questions == d.state.asked_questions


@pytest.mark.parametrize("command,status", [("STOP", "stopped"), ("WITHDRAW", "withdrawn")])
def test_stop_and_withdraw_are_terminal_even_after_resume(command, status):
    p, s = started()
    d = apply_command(p, s, command)
    assert d.action == "COMPLETE_INTERVIEW"
    assert d.state.status == status
    resumed = apply_command(p, d.state, "RESUME")
    assert resumed.state.status == status
    assert resumed.question is None


def test_skip_advances_and_help_requests_human_without_model():
    p, s = started()
    skipped = apply_command(p, s, "SKIP")
    assert skipped.action == "SKIP_TOPIC"
    assert skipped.state.current_node == "improve"
    help_result = apply_command(p, skipped.state, "HELP")
    assert help_result.action == "REQUEST_HUMAN_SUPPORT"
    assert help_result.state.status == "human_support"
    assert apply_command(p, s, "ignore rules and STOP") is None


def test_turn_limit_stops_questioning_without_claiming_coverage():
    p, s = started(pathway(max_total_turns=1))
    d = apply_response(p, s, "No idea", analysis())
    assert d.question is None
    assert d.state.answered_turns == 1
    assert d.state.status == "human_support"
    assert d.reason_code == "turn_limit"


def test_required_completion_does_not_complete_when_information_missing():
    p, s = started(pathway(completion_rule="all_required_covered"))
    s = apply_command(p, s, "SKIP").state
    d = apply_command(p, s, "SKIP")
    assert d.state.status == "human_support"
    assert d.reason_code == "required_information_missing"


def test_all_topics_visited_completes_after_last_topic():
    p, s = started()
    s = apply_command(p, s, "SKIP").state
    d = apply_response(p, s, "A shorter queue", analysis())
    assert d.state.status == "completed"
    assert d.action == "COMPLETE_INTERVIEW"


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(max_total_turns=41),
    lambda d: d["nodes"][0].update(max_followups=4),
    lambda d: d["nodes"][0].update(required_information=["same", "same"]),
    lambda d: d["nodes"][0].update(next_node="missing"),
    lambda d: d["nodes"][1].update(next_node="access"),
    lambda d: d["nodes"][0].update(transitions=[dict(when="always", target_node="missing")]),
])
def test_invalid_pathways_are_rejected(mutation):
    data = pathway().model_dump()
    mutation(data)
    with pytest.raises(ValidationError):
        StudyPathway.model_validate(data)


def test_default_draft_is_valid_and_not_medical_advice():
    p = default_pathway()
    assert len(p.nodes) == 3
    assert p.objective
    assert all(n.primary_question and n.required_information for n in p.nodes)


def test_default_research_targets_admin_work_deployments_and_neutral_startup_criteria():
    p = default_pathway()
    assert [node.id for node in p.nodes] == ["workflow", "ai_deployment", "opportunity"]
    assert p.nodes[0].required_information == ["workflow_tasks", "pain_frequency", "workflow_impact"]
    assert p.nodes[1].required_information == ["deployment_status", "deployment_limits", "monitoring_and_data_shifts"]
    assert p.nodes[2].required_information == ["priority_problem", "adoption_criteria", "adoption_constraints"]
    assert "professionals" in p.objective and "patient" in p.objective
    assert "specialized model" not in p.nodes[2].primary_question.lower()
