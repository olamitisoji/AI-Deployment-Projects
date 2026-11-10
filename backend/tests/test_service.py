from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from echo.audio_transcription import AIError
from echo.conversation_pathway_engine import Analysis, InterviewState, apply_command, default_pathway
from echo.database import Base, InboundEvent, Interview, Invitation, Outbox, Participant, Project, Study, Turn, database, now_ts
from echo.interview_service import process_event
from echo.security import Vault, token_hash


class AI:
    def __init__(self):
        self.calls = []
        self.histories = []
        self.failure = None
        self.on_analyze = None
        self.transcript = "I reconcile appointment reports."
    async def transcribe(self, audio, mime, **kwargs):
        self.calls.append("transcribe")
        if self.failure == "transcribe":
            raise AIError("quota_exhausted")
        return self.transcript
    async def analyze(self, pathway, state, answer, history):
        self.calls.append("analyze")
        self.histories.append(history)
        if self.on_analyze:
            self.on_analyze()
        if self.failure == "analyze":
            raise AIError("quota_exhausted")
        return Analysis(relevant=True, covered_information=["workflow_tasks"], evidence=[dict(criterion="workflow_tasks", quote="reconcile appointment reports")], suggested_action="PROBE_DEEPER", followup="What made reconciling those reports difficult?")


class Gateway:
    def __init__(self):
        self.calls = []
    async def download_audio(self, media_id):
        self.calls.append(media_id)
        return b"audio", "audio/ogg"


@pytest.fixture
def context(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path}/service.db")
    Base.metadata.create_all(engine)
    vault = Vault(Fernet.generate_key().decode())
    settings = SimpleNamespace(retention_days=7, support_contact="research@example.org", privacy_notice_url="https://example.org/privacy")
    with sessions.begin() as db:
        project = Project(name="Test")
        db.add(project); db.flush()
        study = Study(project_id=project.id, title="Access", pathway=vault.seal(default_pathway().model_dump()), status="approved", approved_at=now_ts())
        person = Participant(phone_hash=vault.phone_hash("15551234567"), phone_cipher=vault.seal("15551234567"))
        db.add_all([study, person]); db.flush()
        invitation = Invitation(study_id=study.id, token_hash=token_hash("invite-token"), kind="general", max_uses=10, expires_at=now_ts()+3600)
        db.add(invitation)
        ids = person.id, study.id
    c = SimpleNamespace(sessions=sessions, vault=vault, settings=settings, ai=AI(), gateway=Gateway(), person=ids[0], study=ids[1])
    yield c
    engine.dispose()


async def send(c, text=None, kind="text", event_id=None):
    event_id = event_id or f"event-{now_ts()}-{len(c.ai.calls)}-{text}"
    with c.sessions.begin() as db:
        db.add(InboundEvent(id=event_id, participant_id=c.person, payload_cipher=c.vault.seal(dict(id=event_id, wa_id="15551234567", timestamp=now_ts(), kind=kind, text=text, media_id="media" if kind=="audio" else None, mime_type="audio/ogg")), expires_at=now_ts()+3600))
    await process_event(event_id, c.settings, c.sessions, c.vault, c.ai, c.gateway)
    with c.sessions() as db:
        out = db.scalar(select(Outbox).where(Outbox.event_id==event_id))
        event = db.get(InboundEvent,event_id)
        return c.vault.open(out.text_cipher) if out else None, event.error_code


async def consent(c):
    await send(c,"START invite-token", event_id="start")
    return await send(c,"I CONSENT", event_id="consent")


@pytest.mark.asyncio
async def test_start_validates_invitation_and_requires_explicit_scoped_consent(context):
    c=context
    text,_=await send(c,"START invite-token", event_id="start")
    assert "AI" in text and "I CONSENT" in text
    assert all(scope in text.lower() for scope in ["participation", "recording", "transcription", "data use", "7 days", "research@example.org"])
    await send(c,kind="audio",event_id="preconsent-audio")
    assert c.ai.calls==[] and c.gateway.calls==[]
    text,_=await send(c,"I CONSENT",event_id="consent")
    assert text==default_pathway().nodes[0].primary_question
    with c.sessions() as db:
        interview=db.scalar(select(Interview))
        consent_data=c.vault.open(interview.consent_cipher)
        assert consent_data["status"]=="granted"
        assert consent_data["version"]=="2026-11-10-v2"
        assert all(consent_data[key] is True for key in ["participation","recording","transcription","data_use"])
        assert interview.status=="in_progress"


@pytest.mark.asyncio
async def test_voice_transcribes_then_analyzes_and_atomically_saves_real_evidence(context):
    c=context
    await consent(c)
    text,error=await send(c,kind="audio",event_id="voice")
    assert c.gateway.calls==["media"]
    assert c.ai.calls==["transcribe","analyze"]
    assert text=="What made reconciling those reports difficult?" and error is None
    with c.sessions() as db:
        turn=db.scalar(select(Turn).where(Turn.event_id=="voice"))
        data=c.vault.open(turn.payload_cipher)
        assert data["answer"]=="I reconcile appointment reports."
        assert data["transcript"]=="I reconcile appointment reports."
        assert data["source"]=="audio"
        assert data["decision"]["evidence"]==[{"criterion":"workflow_tasks","quote":"reconcile appointment reports"}]
        assert db.get(InboundEvent,"voice").status=="done"
    await process_event("voice", c.settings,c.sessions,c.vault,c.ai,c.gateway)
    assert c.ai.calls==["transcribe","analyze"]


@pytest.mark.asyncio
async def test_analysis_failure_keeps_actual_transcript_and_requests_human_support(context):
    c=context
    await consent(c);c.ai.failure="analyze"
    text,error=await send(c,kind="audio",event_id="failure")
    assert error=="quota_exhausted"
    assert "support" in text.lower() and "research@example.org" in text
    with c.sessions() as db:
        data=c.vault.open(db.scalar(select(Turn).where(Turn.event_id=="failure")).payload_cipher)
        assert data["answer"]=="I reconcile appointment reports."
        assert data["decision"]["action"]=="REQUEST_HUMAN_SUPPORT"
        interview=db.scalar(select(Interview))
        assert interview.status=="human_support"
        assert c.vault.open(interview.state_cipher)["status"]=="human_support"


@pytest.mark.asyncio
async def test_transcription_failure_never_fabricates_text_or_consumes_answer_turn(context):
    c=context
    await consent(c);c.ai.failure="transcribe"
    text,error=await send(c,kind="audio",event_id="failure")
    assert error=="quota_exhausted" and "text" in text.lower()
    assert c.ai.calls==["transcribe"]
    with c.sessions() as db:
        assert db.scalar(select(Turn)) is None
        assert c.vault.open(db.scalar(select(Interview)).state_cipher)["answered_turns"]==0


@pytest.mark.asyncio
async def test_optout_during_analysis_discards_result_and_enqueues_no_question(context):
    c=context
    await consent(c)
    def stop_during_call():
        with c.sessions.begin() as db:
            db.get(Participant,c.person).opted_out=True
    c.ai.on_analyze=stop_during_call
    text,error=await send(c,"I reconcile appointment reports.",event_id="race")
    assert text is None and error=="participant_opted_out"
    with c.sessions() as db:
        assert db.scalar(select(Turn)) is None


@pytest.mark.asyncio
async def test_stale_analysis_failure_does_not_overwrite_newer_question(context):
    c=context
    await consent(c)
    c.ai.failure="analyze"
    def skip_during_call():
        with c.sessions.begin() as db:
            interview=db.scalar(select(Interview))
            state=InterviewState.model_validate(c.vault.open(interview.state_cipher))
            state=apply_command(default_pathway(),state,"SKIP").state
            interview.state_cipher=c.vault.seal(state.model_dump())
    c.ai.on_analyze=skip_during_call
    text,error=await send(c,"I reconcile appointment reports.",event_id="stale")
    assert text is None and error=="state_changed"
    with c.sessions() as db:
        interview=db.scalar(select(Interview))
        assert c.vault.open(interview.state_cipher)["current_node"]=="ai_deployment"
        assert interview.status=="in_progress"
        assert db.scalar(select(Turn)) is None


@pytest.mark.asyncio
async def test_human_support_state_never_calls_ai_or_downloads_more_audio(context):
    c=context
    await consent(c)
    await send(c,"HELP",event_id="help")
    text,error=await send(c,kind="audio",event_id="support-audio")
    assert "research@example.org" in text
    assert error=="interview_inactive"
    assert c.ai.calls==[] and c.gateway.calls==[]


@pytest.mark.asyncio
async def test_after_withdrawal_scrubbed_state_never_reenters_engine_or_ai(context):
    c=context
    await consent(c)
    await send(c,"WITHDRAW",event_id="withdraw")
    text,error=await send(c,"RESUME",event_id="resume-after-withdraw")
    assert text is None and error=="participant_opted_out"
    await send(c,kind="audio",event_id="voice-after-withdraw")
    assert c.ai.calls==[] and c.gateway.calls==[]


@pytest.mark.asyncio
@pytest.mark.parametrize("command,status",[("STOP.","stopped"),("withdraw!","withdrawn"),("pause.","paused"),("HELP?","human_support")])
async def test_spoken_exact_command_uses_deterministic_control_without_analysis(context,command,status):
    c=context
    await consent(c)
    c.ai.transcript=command
    text,error=await send(c,kind="audio",event_id="spoken-control")
    assert error is None and text
    assert c.ai.calls==["transcribe"]
    with c.sessions() as db:
        assert db.scalar(select(Interview)).status==status
        assert db.scalar(select(Turn)) is None
        if status in {"stopped","withdrawn"}:
            assert db.get(Participant,c.person).opted_out


@pytest.mark.asyncio
async def test_spoken_embedded_command_is_not_guessed_as_participant_instruction(context):
    c=context
    await consent(c)
    c.ai.transcript='The report said "STOP" but I continued working.'
    await send(c,kind="audio",event_id="quoted-command")
    assert c.ai.calls==["transcribe","analyze"]
    with c.sessions() as db:
        assert db.scalar(select(Interview)).status=="in_progress"


@pytest.mark.asyncio
async def test_personalized_invitation_binds_to_first_participant(context):
    c=context
    with c.sessions.begin() as db:
        db.scalar(select(Invitation)).kind="personalized"
    text,error=await send(c,"START invite-token",event_id="personal-start")
    assert "I CONSENT" in text and error is None
    with c.sessions() as db:
        invitation=db.scalar(select(Invitation))
        assert invitation.bound_participant_id==c.person and invitation.uses==1


@pytest.mark.asyncio
async def test_turn_sequence_preserves_history_order_with_equal_timestamps(context):
    c=context
    await consent(c)
    await send(c,"First booking",event_id="first")
    await send(c,"Second barrier",event_id="second")
    with c.sessions.begin() as db:
        for turn in db.scalars(select(Turn)):
            turn.created_at=1
    await send(c,"Third detail",event_id="third")
    answers=[item["text"] for item in c.ai.histories[-1] if item["role"]=="user"]
    assert answers==["First booking","Second barrier"]
    with c.sessions() as db:
        turns=list(db.scalars(select(Turn).order_by(Turn.sequence)))
        assert [row.sequence for row in turns]==[1,2,3]


@pytest.mark.asyncio
async def test_withdraw_scrubs_material_and_cancels_pending_outbox_despite_optout(context):
    c=context
    await consent(c)
    await send(c,"I reconcile appointment reports.",event_id="answer")
    with c.sessions.begin() as db:
        db.get(Participant,c.person).opted_out=True
    text,_=await send(c,"WITHDRAW",event_id="withdraw")
    assert "withdraw" in text.lower()
    with c.sessions() as db:
        interview=db.scalar(select(Interview))
        assert interview.status=="withdrawn"
        assert c.vault.open(interview.state_cipher)=={}
        assert c.vault.open(interview.consent_cipher)=={}
        assert db.scalar(select(Turn)) is None
        assert all(row.status=="cancelled" for row in db.scalars(select(Outbox).where(Outbox.event_id!="withdraw")))
        assert db.scalar(select(Outbox).where(Outbox.event_id=="withdraw")).control_ack is True


@pytest.mark.asyncio
async def test_pause_resume_skip_and_stop_are_deterministic(context):
    c=context
    await consent(c)
    await send(c,"PAUSE",event_id="pause")
    await send(c,kind="audio",event_id="paused-audio")
    text,_=await send(c,"RESUME",event_id="resume")
    assert text==default_pathway().nodes[0].primary_question
    text,_=await send(c,"SKIP",event_id="skip")
    assert text==default_pathway().nodes[1].primary_question
    await send(c,"STOP",event_id="stop")
    await send(c,"RESUME",event_id="late-resume")
    assert c.ai.calls==[] and c.gateway.calls==[]
    with c.sessions() as db:
        assert db.scalar(select(Interview)).status=="stopped"
        assert db.get(Participant,c.person).opted_out


@pytest.mark.asyncio
async def test_repeated_start_does_not_consume_invitation_twice_or_duplicate_interview(context):
    c=context
    await consent(c)
    await send(c,"START invite-token",event_id="start-again")
    with c.sessions() as db:
        assert len(list(db.scalars(select(Interview))))==1
        assert db.scalar(select(Invitation)).uses==1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["expired", "revoked", "used", "draft", "bound"])
async def test_invalid_invitation_never_creates_interview(context,change):
    c=context
    with c.sessions.begin() as db:
        invitation=db.scalar(select(Invitation))
        if change=="expired":invitation.expires_at=now_ts()-1
        if change=="revoked":invitation.revoked=True
        if change=="used":invitation.uses=invitation.max_uses
        if change=="draft":db.get(Study,c.study).status="draft"
        if change=="bound":invitation.kind="personalized";invitation.bound_participant_id="someone-else"
    text,_=await send(c,"START invite-token",event_id="start")
    assert "invitation" in text.lower()
    with c.sessions() as db:
        assert db.scalar(select(Interview)) is None
