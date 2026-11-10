"""Application-owned interview policy. The model supplies evidence, never authority."""
from __future__ import annotations

import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Transition(StrictModel):
    when: Literal["required_covered", "irrelevant", "always"]
    target_node: str | None


class PathwayNode(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    objective: str = Field(min_length=1, max_length=1000)
    primary_question: str = Field(min_length=1, max_length=1000)
    suggested_probes: list[str] = Field(default_factory=list, max_length=6)
    required_information: list[str] = Field(default_factory=list, max_length=12)
    optional_information: list[str] = Field(default_factory=list, max_length=12)
    clarification_conditions: list[str] = Field(default_factory=list, max_length=6)
    deeper_probe_conditions: list[str] = Field(default_factory=list, max_length=6)
    max_followups: int = Field(default=2, ge=0, le=3)
    next_node: str | None = None
    transitions: list[Transition] = Field(default_factory=list, max_length=3)

    @field_validator("suggested_probes", "required_information", "optional_information", "clarification_conditions", "deeper_probe_conditions")
    @classmethod
    def unique_nonempty(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip() for v in values]
        if any(not v or len(v) > 1000 for v in cleaned) or len({v.casefold() for v in cleaned}) != len(cleaned):
            raise ValueError("Items must be nonempty, bounded, and unique")
        return cleaned


class StudyPathway(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2000)
    nodes: list[PathwayNode] = Field(min_length=1, max_length=12)
    max_total_turns: int = Field(default=20, ge=1, le=40)
    completion_rule: Literal["all_topics_visited", "all_required_covered"] = "all_topics_visited"

    @model_validator(mode="after")
    def valid_graph(self):
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("Node IDs must be unique")
        graph = {}
        for index, node in enumerate(self.nodes):
            fallback = node.next_node or (ids[index + 1] if index + 1 < len(ids) else None)
            targets = [t.target_node for t in node.transitions]
            if not any(t.when == "always" for t in node.transitions):
                targets.append(fallback)
            if node.next_node is not None:
                targets.append(node.next_node)
            if any(target not in ids for target in targets if target is not None):
                raise ValueError("Unknown transition target")
            graph[node.id] = [t for t in targets if t is not None]
        active, done = set(), set()

        def visit(node_id):
            if node_id in active:
                raise ValueError("Cycles are not permitted")
            if node_id in done:
                return
            active.add(node_id)
            for target in graph[node_id]:
                visit(target)
            active.remove(node_id)
            done.add(node_id)

        for node_id in ids:
            visit(node_id)
        return self


class Evidence(StrictModel):
    criterion: str = Field(min_length=1, max_length=1000)
    quote: str = Field(min_length=1, max_length=2000)


class Analysis(StrictModel):
    relevant: bool
    covered_information: list[str] = Field(default_factory=list, max_length=24)
    evidence: list[Evidence] = Field(default_factory=list, max_length=24)
    suggested_action: Literal["CLARIFY", "PROBE_DEEPER", "ASK_FOR_EXAMPLE", "MOVE_TO_NEXT_TOPIC", "REQUEST_HUMAN_SUPPORT"]
    followup: str = Field(default="", max_length=1000)


Action = Literal["ASK_PRIMARY", "PROBE_DEEPER", "CLARIFY", "ASK_FOR_EXAMPLE", "MOVE_TO_NEXT_TOPIC", "SKIP_TOPIC", "PAUSE_INTERVIEW", "COMPLETE_INTERVIEW", "REQUEST_HUMAN_SUPPORT"]
Status = Literal["active", "paused", "completed", "stopped", "withdrawn", "human_support"]


class InterviewState(StrictModel):
    current_node: str | None
    coverage: dict[str, Literal["covered", "partial", "unanswered"]] = Field(default_factory=dict)
    criteria_covered: dict[str, list[str]] = Field(default_factory=dict)
    followups: dict[str, int] = Field(default_factory=dict)
    asked_questions: list[str] = Field(default_factory=list)
    answered_turns: int = Field(default=0, ge=0)
    status: Status = "active"
    visited_nodes: list[str] = Field(default_factory=list)
    outstanding_question: str | None = None
    outstanding_action: Action = "ASK_PRIMARY"


class Decision(StrictModel):
    action: Action
    question: str | None = None
    reason_code: str
    evidence: list[Evidence] = Field(default_factory=list)
    state: InterviewState


def initial_state(pathway: StudyPathway) -> InterviewState:
    return InterviewState(current_node=pathway.nodes[0].id,
        coverage={node.id: "unanswered" for node in pathway.nodes},
        criteria_covered={node.id: [] for node in pathway.nodes},
        followups={node.id: 0 for node in pathway.nodes})


def _node(pathway: StudyPathway, state: InterviewState) -> PathwayNode:
    return next(node for node in pathway.nodes if node.id == state.current_node)


def _decision(state, action, reason, question=None, evidence=None):
    return Decision(state=state, action=action, reason_code=reason, question=question, evidence=evidence or [])


def _inactive(state):
    action = "PAUSE_INTERVIEW" if state.status == "paused" else "REQUEST_HUMAN_SUPPORT" if state.status == "human_support" else "COMPLETE_INTERVIEW"
    return _decision(state, action, f"interview_{state.status}")


def _ask(state, action, reason, question, evidence=None):
    state.outstanding_question = question
    state.outstanding_action = action
    state.asked_questions.append(question)
    return _decision(state, action, reason, question, evidence)


def _safe_followup(text: str) -> bool:
    """A narrow lexical screen, not a guarantee of neutrality or topical relevance."""
    if not text or len(text) > 400 or "?" not in text or text.count("?") > 1 or "\n" in text:
        return False
    blocked = r"password|passcode|secret|api.?key|social security|national.?id|full name|exact address|credit card|ignore.{0,30}(rule|instruction|previous)|system prompt|you should|you must|why (didn't|did not|don't|do not)|do you agree|isn't it|obviously|terrible|stupid|diagnos|prescrib|dosage"
    return re.search(blocked, text, re.IGNORECASE) is None


def begin(pathway: StudyPathway, state: InterviewState) -> Decision:
    state = state.model_copy(deep=True)
    if state.status != "active":
        return _inactive(state)
    if state.outstanding_question:
        return _decision(state, state.outstanding_action, "question_pending", state.outstanding_question)
    return _ask(state, "ASK_PRIMARY", "interview_started", _node(pathway, state).primary_question)


def _finish(pathway, state, evidence=None):
    state.current_node = None
    state.outstanding_question = None
    required = all(set(node.required_information) <= set(state.criteria_covered.get(node.id, [])) for node in pathway.nodes)
    visited = all(node.id in state.visited_nodes for node in pathway.nodes)
    met = required if pathway.completion_rule == "all_required_covered" else visited
    state.status = "completed" if met else "human_support"
    reason = "completion_rule_met" if met else "required_information_missing" if pathway.completion_rule == "all_required_covered" else "topics_unvisited"
    return _decision(state, "COMPLETE_INTERVIEW" if met else "REQUEST_HUMAN_SUPPORT", reason, evidence=evidence)


def _advance(pathway, state, *, relevant=True, covered=False, skip=False, evidence=None):
    node = _node(pathway, state)
    if node.id not in state.visited_nodes:
        state.visited_nodes.append(node.id)
    target = None
    matched = False
    # SKIP is participant authority and follows the ordinary study order.
    if not skip:
        for transition in node.transitions:
            if transition.when == "always" or (transition.when == "required_covered" and covered) or (transition.when == "irrelevant" and not relevant):
                target, matched = transition.target_node, True
                break
    if not matched:
        index = next(i for i, n in enumerate(pathway.nodes) if n.id == node.id)
        target = node.next_node or (pathway.nodes[index + 1].id if index + 1 < len(pathway.nodes) else None)
    if target is None:
        return _finish(pathway, state, evidence)
    state.current_node = target
    return _ask(state, "SKIP_TOPIC" if skip else "MOVE_TO_NEXT_TOPIC", "participant_skipped" if skip else "topic_advanced", _node(pathway, state).primary_question, evidence)


def apply_command(pathway: StudyPathway, state: InterviewState, command: str) -> Decision | None:
    command = command.strip().upper()
    if command not in {"PAUSE", "RESUME", "SKIP", "STOP", "WITHDRAW", "HELP"}:
        return None
    state = state.model_copy(deep=True)
    # Withdrawal may still purge a completed/stopped participant's material.
    if command == "WITHDRAW":
        state.status, state.outstanding_question = "withdrawn", None
        return _decision(state, "COMPLETE_INTERVIEW", "participant_withdrew")
    if state.status in {"stopped", "withdrawn", "completed", "human_support"}:
        return _inactive(state)
    if command == "STOP":
        state.status, state.outstanding_question = "stopped", None
        return _decision(state, "COMPLETE_INTERVIEW", "participant_stopped")
    if command == "HELP":
        state.status = "human_support"
        return _decision(state, "REQUEST_HUMAN_SUPPORT", "participant_requested_help")
    if command == "PAUSE":
        state.status = "paused"
        return _decision(state, "PAUSE_INTERVIEW", "participant_paused")
    if command == "RESUME":
        state.status = "active"
        return _decision(state, state.outstanding_action, "participant_resumed", state.outstanding_question) if state.outstanding_question else begin(pathway, state)
    if state.status == "paused":
        return _inactive(state)
    return _advance(pathway, state, skip=True)


def apply_response(pathway: StudyPathway, state: InterviewState, answer: str, analysis: Analysis) -> Decision:
    state = state.model_copy(deep=True)
    if state.status != "active":
        return _inactive(state)
    if state.answered_turns >= pathway.max_total_turns:
        state.status, state.outstanding_question = "human_support", None
        return _decision(state, "REQUEST_HUMAN_SUPPORT", "turn_limit")
    node = _node(pathway, state)
    state.answered_turns += 1
    if node.id not in state.visited_nodes:
        state.visited_nodes.append(node.id)
    valid = []
    if answer.strip() and analysis.relevant:
        for item in analysis.evidence:
            if item.criterion in node.required_information and item.criterion in analysis.covered_information and item.quote.strip() and item.quote.casefold() in answer.casefold():
                valid.append(item)
                if item.criterion not in state.criteria_covered[node.id]:
                    state.criteria_covered[node.id].append(item.criterion)
    covered = bool(node.required_information) and set(node.required_information) <= set(state.criteria_covered[node.id])
    state.coverage[node.id] = "covered" if covered else "partial" if state.criteria_covered[node.id] else "unanswered"
    if analysis.suggested_action == "REQUEST_HUMAN_SUPPORT":
        state.status, state.outstanding_question = "human_support", None
        return _decision(state, "REQUEST_HUMAN_SUPPORT", "support_review_requested", evidence=valid)
    if state.answered_turns >= pathway.max_total_turns:
        # Finishing a fully covered final topic is valid at the final allowed turn.
        if covered and node.id == pathway.nodes[-1].id:
            return _finish(pathway, state, valid)
        state.status, state.outstanding_question = "human_support", None
        return _decision(state, "REQUEST_HUMAN_SUPPORT", "turn_limit", evidence=valid)
    immediate_branch = any(t.when == "always" or (t.when == "irrelevant" and not analysis.relevant) for t in node.transitions)
    if covered or immediate_branch or state.followups[node.id] >= node.max_followups:
        return _advance(pathway, state, relevant=analysis.relevant, covered=covered, evidence=valid)
    # Model wording is advisory; movement, coverage and hard budgets stay in code.
    candidates = list(node.suggested_probes)
    if analysis.relevant and analysis.suggested_action in {"CLARIFY", "PROBE_DEEPER", "ASK_FOR_EXAMPLE"} and _safe_followup(analysis.followup):
        candidates.insert(0, analysis.followup)
    candidates.append(f"Could you tell me a little more about this question: {node.primary_question}")
    prior = {question.casefold() for question in state.asked_questions}
    question = next((q for q in candidates if q.casefold() not in prior), None)
    if question is None:
        return _advance(pathway, state, relevant=analysis.relevant, evidence=valid)
    state.followups[node.id] += 1
    action = analysis.suggested_action if analysis.suggested_action in {"CLARIFY", "PROBE_DEEPER", "ASK_FOR_EXAMPLE"} else "CLARIFY"
    return _ask(state, action, "required_information_pending", question, valid)


def default_pathway() -> StudyPathway:
    """A reviewable research draft, without clinical advice or treatment decisions."""
    return StudyPathway(title="Healthcare administration and AI opportunity research",
        objective="Understand healthcare administrative workflows, current AI deployments, and startup opportunity criteria through interviews with professionals, executives and researchers. Discuss processes without patient data, personal names, or identifying organizational details. Do not assume that AI or specialized models are the appropriate solution.",
        nodes=[
            PathwayNode(id="workflow", objective="Identify recurring administrative tasks, pain frequency, and operational impact without collecting patient information.",
                primary_question="In your healthcare administration work, which recurring tasks cause the most friction? Please describe the process without names or patient details.",
                required_information=["workflow_tasks", "pain_frequency", "workflow_impact"],
                optional_information=["existing_workarounds", "stakeholder_roles"],
                suggested_probes=["How often does that difficulty occur?", "What effect does it have on time, cost, quality or the people doing the work?", "Could you walk through a recent example without identifying anyone?"],
                clarification_conditions=["The task or workflow is unclear", "The response includes identifying information; redirect to the process"],
                deeper_probe_conditions=["A recurring difficulty is mentioned without its frequency or impact"], max_followups=3),
            PathwayNode(id="ai_deployment", objective="Understand actual AI use or non-use, practical limits, oversight, and how changing data or workflows are monitored.",
                primary_question="Where, if anywhere, is AI used in your administrative workflows today, and how is it working in practice?",
                required_information=["deployment_status", "deployment_limits", "monitoring_and_data_shifts"],
                optional_information=["evaluation_methods", "human_oversight", "integration_work"],
                suggested_probes=["What has limited its usefulness, or prevented deployment if it is not in use?", "How do people check outputs and notice problems when the data or workflow changes?", "Could you describe a concrete outcome or limitation without sharing confidential details?"],
                clarification_conditions=["A hypothetical AI use case is described without distinguishing it from a live deployment"],
                deeper_probe_conditions=["AI deployment is mentioned without evidence of outcomes or limits", "Monitoring or handling of changing data is unclear"], max_followups=3),
            PathwayNode(id="opportunity", objective="Understand which administrative problem a startup should prioritize and the criteria and constraints for adopting a solution, without presuming a particular technology.",
                primary_question="If a startup could improve one part of healthcare administration, which problem would you prioritize, and what would make a solution worth adopting?",
                required_information=["priority_problem", "adoption_criteria", "adoption_constraints"],
                optional_information=["buying_process", "integration_requirements", "alternatives"],
                suggested_probes=["What evidence would convince you that the solution creates enough value?", "What budget, integration, privacy, reliability or procurement constraints would it need to meet?", "How would you compare it with the current process or other available approaches?"],
                clarification_conditions=["A proposed technology is named without the underlying administrative problem"],
                deeper_probe_conditions=["The priority problem is clear but success criteria or adoption constraints are missing"], max_followups=3),
        ], max_total_turns=16)
