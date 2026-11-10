"""Durable inbox processing with deterministic consent and application-owned policy.

No database transaction remains open across an external provider await. Every
provider result is checked against current opt-out and interview state before use.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

from sqlalchemy import delete, func, select

from .audio_transcription import AIError
from .conversation_pathway_engine import Decision, InterviewState, StudyPathway, apply_command, apply_response, begin, initial_state
from .database import InboundEvent, Interview, Invitation, Outbox, Participant, Study, Turn, now_ts
from .security import token_hash
from .whatsapp_gateway import GatewayError


CONSENT_VERSION = "2026-11-10-v2"
SCOPES = ("participation", "recording", "transcription", "data_use")


def normalize_command(text):
    """Recognize only a standalone command, tolerating terminal STT punctuation."""
    match = re.fullmatch(r"(PAUSE|RESUME|SKIP|STOP|WITHDRAW|HELP|DECLINE)[.!?]*", text.strip(), re.IGNORECASE)
    return match.group(1).upper() if match else None


def _consent(settings, study):
    privacy = f" Privacy notice: {settings.privacy_notice_url}" if settings.privacy_notice_url else ""
    provider = "Provider handling follows the privacy notice. " if settings.privacy_notice_url else "Provider retention is separate; ask the researcher before sharing sensitive data. "
    return (
        f"You are invited to '{study.title}'. This is an AI-assisted research interview, not medical care. "
        "AI will help transcribe voice messages and select followup questions; a researcher can review the interview. "
        "Please decide whether you agree to all four scopes: (1) participation in this interview, "
        "(2) recording/processing the voice messages you choose to submit, (3) transcription of voice messages by OpenAI, "
        "and (4) data use of your answers and transcripts for the research study. Raw downloaded audio is transient and is not retained by Echo. "
        f"Echo retains interview records for {settings.retention_days} days. {provider}"
        "Avoid names, identity numbers, passwords and other identifying details. Participation is voluntary; you may skip any question. "
        "Reply I CONSENT to grant all four scopes, or DECLINE to refuse. Text PAUSE, RESUME, SKIP, STOP, WITHDRAW or HELP at any time. "
        "During an active consented interview you may also say a command alone in a voice note; recognition can make mistakes. Use text while paused. "
        f"WITHDRAW removes your stored interview material in Echo. For support contact {settings.support_contact}.{privacy}"
    )


def _support(settings):
    return f"The interview needs human support and has paused. Please contact {settings.support_contact}. You can still use STOP or WITHDRAW."


def _reply_for(decision, settings):
    if decision.question:
        return decision.question
    if decision.action == "REQUEST_HUMAN_SUPPORT":
        return _support(settings)
    if decision.state.status == "paused":
        return "The interview is paused. Reply RESUME when you want to continue, or STOP or WITHDRAW to leave."
    if decision.state.status == "completed":
        return "Thank you. Your research interview is complete. You can still use WITHDRAW to remove your stored interview material."
    return "The interview has stopped. Thank you for your time."


def _status(state):
    return "in_progress" if state.status == "active" else state.status


def _enqueue(db, event, person, text, vault, settings, interview=None, control=False):
    if not text or db.scalar(select(Outbox).where(Outbox.event_id == event.id)):
        return
    if person.opted_out and not control:
        return
    db.add(Outbox(event_id=event.id, participant_id=person.id, interview_id=interview.id if interview else None,
        text_cipher=vault.seal(text), control_ack=control, expires_at=min(event.expires_at, now_ts()+settings.retention_days*86400)))


def _done(event, error=None):
    event.status, event.error_code = "done", error


def _next_sequence(db, interview_id):
    return (db.scalar(select(func.max(Turn.sequence)).where(Turn.interview_id==interview_id)) or 0)+1


def _engine_command(db,event,person,interview,pathway,state,command,vault,settings):
    decision = apply_command(pathway,state,command)
    if decision is None:
        return False
    interview.state_cipher, interview.status, interview.updated_at = vault.seal(decision.state.model_dump()), _status(decision.state), now_ts()
    _enqueue(db,event,person,_reply_for(decision,settings),vault,settings,interview)
    _done(event)
    return True


def _cancel_outbox(db, participant_id, vault, scrub=False):
    for row in db.scalars(select(Outbox).where(Outbox.participant_id == participant_id)):
        if row.status in {"pending", "sending", "queued", "retry"}:
            row.status, row.error_code = "cancelled", "participant_opted_out"
        if scrub:
            row.text_cipher = vault.seal("")


def _control(db, event, person, interview, command, vault, settings):
    if command not in {"STOP", "DECLINE", "WITHDRAW"}:
        return False
    prior_status = interview.status if interview else None
    person.opted_out = True
    _cancel_outbox(db, person.id, vault, scrub=command == "WITHDRAW")
    if command == "WITHDRAW":
        # Inbound payloads also contain participant text and must be erased.
        for record in db.scalars(select(InboundEvent).where(InboundEvent.participant_id == person.id)):
            record.payload_cipher = vault.seal({})
        for record in db.scalars(select(Interview).where(Interview.participant_id == person.id)):
            db.execute(delete(Turn).where(Turn.interview_id == record.id))
            record.state_cipher, record.consent_cipher = vault.seal({}), vault.seal({})
            record.status, record.updated_at = "withdrawn", now_ts()
        reply = "You have withdrawn. Your stored interview answers, transcripts, state and consent records have been removed from Echo. No further research questions will be sent."
        changed = prior_status != "withdrawn"
    else:
        target = "declined" if command == "DECLINE" or (interview and interview.status == "started") else "stopped"
        if interview:
            interview.status, interview.updated_at = target, now_ts()
            consent = vault.open(interview.consent_cipher)
            consent.update(status="declined" if target == "declined" else "revoked", at=datetime.now(timezone.utc).isoformat())
            for scope in SCOPES:
                consent[scope] = False
            interview.consent_cipher = vault.seal(consent)
            state = vault.open(interview.state_cipher)
            if state:
                parsed = InterviewState.model_validate(state)
                parsed.status, parsed.outstanding_question = "stopped", None
                interview.state_cipher = vault.seal(parsed.model_dump())
        reply = "You have declined the interview. No further research questions will be sent." if target == "declined" else "The interview has stopped. No further research questions will be sent. You can still use WITHDRAW to remove your stored interview material."
        changed = prior_status not in {"declined", "stopped", "withdrawn"}
    if changed:
        _enqueue(db, event, person, reply, vault, settings, interview, control=True)
    _done(event)
    return True


def _start(db, event, person, token, settings, vault):
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash(token)).with_for_update())
    study = db.get(Study, invitation.study_id) if invitation else None
    existing = db.scalar(select(Interview).where(Interview.study_id == study.id, Interview.participant_id == person.id)) if study else None
    valid = invitation and study and study.status == "approved" and not invitation.revoked and invitation.expires_at > now_ts()
    valid = valid and invitation.kind in {"general", "personalized"} and (invitation.kind != "personalized" or invitation.bound_participant_id in {None, person.id})
    valid = valid and (existing is not None or invitation.uses < invitation.max_uses)
    if not valid:
        _enqueue(db,event,person,"That invitation is unavailable or expired. Please ask the researcher for a valid invitation.",vault,settings)
        _done(event,"invalid_invitation")
        return
    active = db.get(Interview, person.active_interview_id) if person.active_interview_id else None
    if active and active.status in {"started", "in_progress", "paused", "human_support"}:
        existing = active
    if existing:
        person.active_interview_id = existing.id
        if existing.status == "started":
            selected_study = db.get(Study, existing.study_id)
            reply = _consent(settings, selected_study)
        elif existing.status in {"in_progress", "paused", "human_support"}:
            state = InterviewState.model_validate(vault.open(existing.state_cipher))
            reply = state.outstanding_question if existing.status == "in_progress" else _support(settings) if existing.status == "human_support" else "Your interview is paused. Reply RESUME to continue."
        else:
            reply = "This interview is already closed. Please contact the researcher if you need help."
        _enqueue(db,event,person,reply,vault,settings,existing)
        _done(event)
        return
    pathway = StudyPathway.model_validate(vault.open(study.pathway))
    consent = {"version": CONSENT_VERSION, "status": "pending", "at": None, **{scope:False for scope in SCOPES}}
    interview = Interview(study_id=study.id, participant_id=person.id, status="started", pathway_cipher=vault.seal(pathway.model_dump()),
        state_cipher=vault.seal(initial_state(pathway).model_dump()), consent_cipher=vault.seal(consent), expires_at=now_ts()+settings.retention_days*86400)
    db.add(interview); db.flush()
    person.active_interview_id = interview.id
    invitation.uses += 1
    if invitation.kind == "personalized":
        invitation.bound_participant_id = person.id
    _enqueue(db,event,person,_consent(settings,study),vault,settings,interview)
    _done(event)


def _still_allowed(session_factory, participant_id, interview_id):
    with session_factory() as db:
        person, interview = db.get(Participant,participant_id), db.get(Interview,interview_id)
        if not person or person.opted_out or not interview or interview.status != "in_progress" or interview.expires_at <= now_ts():
            return False
        return True


def _provider_failure(event_id, settings, session_factory, vault, error, interview_id, answer=None, source=None, question=None, state=None):
    with session_factory.begin() as db:
        event = db.get(InboundEvent,event_id)
        if not event or event.status == "done":
            return
        person, interview = db.get(Participant,event.participant_id), db.get(Interview,interview_id)
        if not person or person.opted_out or not interview or interview.status != "in_progress":
            _done(event,"participant_opted_out" if person and person.opted_out else "interview_inactive")
            return
        if interview.expires_at <= now_ts():
            _done(event,"interview_expired")
            return
        if answer is not None:
            if vault.open(interview.state_cipher) != state.model_dump():
                _done(event,"state_changed")
                return
            state.status, state.outstanding_question = "human_support", None
            decision = {"action":"REQUEST_HUMAN_SUPPORT", "reason_code":error, "evidence":[]}
            payload = {"question":question, "answer":answer, "source":source, "transcript":answer if source == "audio" else None, "decision":decision}
            db.add(Turn(interview_id=interview.id,event_id=event.id,sequence=_next_sequence(db,interview.id),payload_cipher=vault.seal(payload)))
            interview.state_cipher, interview.status = vault.seal(state.model_dump()), "human_support"
            reply = _support(settings)
        else:
            reply = f"I could not transcribe that voice message. Please resend your answer as text, or contact {settings.support_contact} for support. No answer was recorded from that audio."
        interview.updated_at = now_ts()
        _enqueue(db,event,person,reply,vault,settings,interview)
        _done(event,error)


async def process_event(event_id, settings, session_factory, vault, ai, gateway) -> None:
    """Process one durable inbound message and atomically enqueue at most one reply."""
    with session_factory.begin() as db:
        event = db.scalar(select(InboundEvent).where(InboundEvent.id==event_id).with_for_update())
        if not event or event.status not in {"queued","processing"}:
            return
        event.status = "processing"
        person = db.get(Participant,event.participant_id)
        if not person:
            _done(event,"participant_missing");return
        body = vault.open(event.payload_cipher)
        text = body.get("text") if isinstance(body.get("text"),str) else ""
        command = normalize_command(text) or text.strip().upper()
        interview = db.get(Interview,person.active_interview_id) if person.active_interview_id else None
        if _control(db,event,person,interview,command,vault,settings):
            return
        if person.opted_out:
            _done(event,"participant_opted_out");return
        if event.expires_at <= now_ts():
            _done(event,"event_expired");return
        parts = text.strip().split()
        if len(parts)==2 and parts[0].upper()=="START":
            _start(db,event,person,parts[1],settings,vault);return
        if not interview:
            _enqueue(db,event,person,"Please use the START invitation shared by your researcher to begin.",vault,settings)
            _done(event,"invitation_required");return
        if interview.expires_at <= now_ts():
            _enqueue(db,event,person,"This interview has expired. Please contact the researcher for support.",vault,settings,interview)
            _done(event,"interview_expired");return
        pathway = StudyPathway.model_validate(vault.open(interview.pathway_cipher))
        state = InterviewState.model_validate(vault.open(interview.state_cipher))
        consent = vault.open(interview.consent_cipher)
        if interview.status == "started":
            if command == "I CONSENT":
                consent.update(status="granted",version=CONSENT_VERSION,at=datetime.now(timezone.utc).isoformat(), **{scope:True for scope in SCOPES})
                interview.consent_cipher = vault.seal(consent)
                decision = begin(pathway,state)
                interview.state_cipher, interview.status, interview.updated_at = vault.seal(decision.state.model_dump()), "in_progress", now_ts()
                _enqueue(db,event,person,_reply_for(decision,settings),vault,settings,interview)
            else:
                _enqueue(db,event,person,_support(settings) if command=="HELP" else _consent(settings,db.get(Study,interview.study_id)),vault,settings,interview)
            _done(event);return
        if not consent or consent.get("status") != "granted" or not all(consent.get(scope) is True for scope in SCOPES):
            _done(event,"consent_required");return
        if _engine_command(db,event,person,interview,pathway,state,command,vault,settings):
            return
        if interview.status != "in_progress":
            _enqueue(db,event,person,_support(settings) if interview.status=="human_support" else "The interview is paused or closed. Reply RESUME if it is paused, or HELP for support.",vault,settings,interview)
            _done(event,"interview_inactive");return
        if body.get("kind") not in {"text","audio"} or (body.get("kind")=="text" and not text.strip()):
            _enqueue(db,event,person,"Please reply with a text answer or a voice message. Commands such as SKIP or HELP are also available.",vault,settings,interview)
            _done(event,"unsupported_message");return
        # Only encrypted material is copied out; no transaction spans the await.
        source, interview_id, participant_id = body["kind"], interview.id, person.id
        question = state.outstanding_question
        history = []
        rows = list(db.scalars(select(Turn).where(Turn.interview_id==interview.id).order_by(Turn.sequence.desc()).limit(6)))
        for row in reversed(rows):
            turn = vault.open(row.payload_cipher)
            if turn.get("question"):
                history.append({"role":"assistant","text":turn["question"]})
            if turn.get("answer"):
                history.append({"role":"user","text":turn["answer"]})
    answer = text
    if source == "audio":
        try:
            if not _still_allowed(session_factory,participant_id,interview_id):
                _provider_failure(event_id,settings,session_factory,vault,"participant_opted_out",interview_id);return
            audio, mime = await gateway.download_audio(body.get("media_id"))
            if not _still_allowed(session_factory,participant_id,interview_id):
                del audio
                _provider_failure(event_id,settings,session_factory,vault,"participant_opted_out",interview_id);return
            try:
                answer = await ai.transcribe(audio,mime,before_upload=lambda: _still_allowed(session_factory,participant_id,interview_id))
            finally:
                del audio
        except (AIError,GatewayError) as error:
            _provider_failure(event_id,settings,session_factory,vault,error.code,interview_id);return
    if not _still_allowed(session_factory,participant_id,interview_id):
        _provider_failure(event_id,settings,session_factory,vault,"participant_opted_out",interview_id);return
    spoken_command = normalize_command(answer) if source == "audio" else None
    if spoken_command:
        with session_factory.begin() as db:
            event = db.get(InboundEvent,event_id)
            person, interview = db.get(Participant,participant_id), db.get(Interview,interview_id)
            if not event or event.status == "done":
                return
            if _control(db,event,person,interview,spoken_command,vault,settings):
                return
            if person.opted_out or interview.status != "in_progress" or vault.open(interview.state_cipher) != state.model_dump():
                _done(event,"participant_opted_out" if person.opted_out else "state_changed");return
            _engine_command(db,event,person,interview,pathway,state,spoken_command,vault,settings)
        return
    try:
        analysis = await ai.analyze(pathway,state,answer,history)
    except AIError as error:
        _provider_failure(event_id,settings,session_factory,vault,error.code,interview_id,answer,source,question,state);return
    decision = apply_response(pathway,state,answer,analysis)
    with session_factory.begin() as db:
        event = db.get(InboundEvent,event_id)
        person, interview = db.get(Participant,participant_id), db.get(Interview,interview_id)
        if not event or event.status == "done":
            return
        if not person or person.opted_out or not interview or interview.status != "in_progress":
            _done(event,"participant_opted_out" if person and person.opted_out else "interview_inactive");return
        if interview.expires_at <= now_ts():
            _done(event,"interview_expired");return
        # Reject stale provider results if a command changed state while awaiting.
        if vault.open(interview.state_cipher) != state.model_dump():
            _done(event,"state_changed");return
        payload = {"question":question,"answer":answer,"source":source,"transcript":answer if source=="audio" else None,
            "decision":{"action":decision.action,"reason_code":decision.reason_code,"evidence":[item.model_dump() for item in decision.evidence]}}
        db.add(Turn(interview_id=interview.id,event_id=event.id,sequence=_next_sequence(db,interview.id),payload_cipher=vault.seal(payload)))
        interview.state_cipher, interview.status, interview.updated_at = vault.seal(decision.state.model_dump()), _status(decision.state), now_ts()
        _enqueue(db,event,person,_reply_for(decision,settings),vault,settings,interview)
        _done(event)
