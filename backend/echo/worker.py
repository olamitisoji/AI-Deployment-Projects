"""Single-sender durable inbox/outbox worker; run with ``python -m echo.worker``."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import fcntl
from pathlib import Path
import secrets
import signal
import sys

from sqlalchemy import delete, select, text, update
from sqlalchemy.engine import make_url

from .audio_transcription import AIClient
from .config import get_settings
from .database import DeliveryEvent, InboundEvent, Interview, Outbox, Participant, Turn, database, now_ts
from .security import Vault
from .whatsapp_gateway import GatewayError, MetaGateway


async def process_event(event_id, settings, session_factory, vault, ai, gateway):
    # Import at execution time so maintenance/retention can run without starting AI work.
    from .interview_service import process_event as handle_event
    await handle_event(event_id, settings, session_factory, vault, ai, gateway)


class WorkerAlreadyRunning(RuntimeError):
    pass


class WorkerLockLost(RuntimeError):
    pass


class SingletonWorker:
    """Hold the sender lock for the entire process, including all network awaits.

    PostgreSQL's session advisory lock lives on a dedicated held connection.
    Local SQLite uses an OS file lock alongside the database, across processes.
    """
    LOCK_ID = 1162037327

    def __init__(self, engine, database_url: str):
        self.engine, self.url = engine, make_url(database_url)
        self._connection = self._file = None
        self._backend_pid = None
        self._lost = False

    def __enter__(self):
        if self.url.get_backend_name() == "postgresql":
            connection = self.engine.connect()
            try:
                acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": self.LOCK_ID})
                if not acquired:
                    raise WorkerAlreadyRunning("worker_already_running")
                self._backend_pid = connection.scalar(text("SELECT pg_backend_pid()"))
                connection.commit()  # Session-level lock survives; avoid an idle transaction.
                self._connection = connection
            except BaseException:
                connection.close()
                raise
        elif self.url.get_backend_name() == "sqlite":
            if not self.url.database or self.url.database == ":memory:":
                raise ValueError("Worker requires a persistent SQLite database")
            path = Path(self.url.database).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = Path(str(path) + ".worker.lock").open("a+")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._file = handle
            except BlockingIOError:
                handle.close()
                raise WorkerAlreadyRunning("worker_already_running") from None
        else:
            raise ValueError("Unsupported worker database")
        return self

    def assert_owned(self):
        if self._file is not None and not self._file.closed:
            return
        if self._connection is not None and not self._lost:
            try:
                row = self._connection.execute(text(
                    "SELECT pg_backend_pid(), EXISTS (SELECT 1 FROM pg_locks "
                    "WHERE locktype='advisory' AND pid=pg_backend_pid() "
                    "AND classid=0 AND objid=:key AND objsubid=1 AND granted)"), {"key": self.LOCK_ID}).one()
                self._connection.commit()
                if row[0] == self._backend_pid and row[1]:
                    return
            except Exception:
                pass
        self._lost = True
        raise WorkerLockLost("worker_lock_lost")

    def __exit__(self, *_):
        if self._connection is not None:
            try:
                if not self._lost:
                    self._connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.LOCK_ID})
            finally:
                self._connection.close()
                self._connection = None
        if self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()
            self._file = None


def recover_interrupted(sessions):
    """Call only after acquiring the singleton lock.

    Model/media reads can resume. An interrupted send has unknown delivery and
    must be reconciled instead of replayed, regardless of its provider ID.
    """
    with sessions.begin() as session:
        session.execute(update(InboundEvent).where(InboundEvent.status == "processing").values(status="queued", error_code=None))
        session.execute(update(Outbox).where(Outbox.status == "sending").values(status="uncertain", error_code="worker_interrupted_send"))


def scrub_retention(settings, sessions, *, now: int | None = None) -> dict:
    current = now_ts() if now is None else now
    counts = {"inbox": 0, "outbox": 0, "interviews": 0, "identities": 0, "delivery_events": 0}
    with sessions.begin() as session:
        expired = session.scalars(select(Interview).where(Interview.expires_at <= current)).all()
        expired_ids = [item.id for item in expired]
        expired_participants = {item.participant_id for item in expired}
        if expired_ids:
            event_ids = list(session.scalars(select(Turn.event_id).where(Turn.interview_id.in_(expired_ids))))
            if event_ids:
                counts["inbox"] += session.execute(delete(InboundEvent).where(InboundEvent.id.in_(event_ids))).rowcount
            session.execute(delete(Turn).where(Turn.interview_id.in_(expired_ids)))
            counts["outbox"] += session.execute(delete(Outbox).where(Outbox.interview_id.in_(expired_ids))).rowcount
            for interview in expired:
                if interview.pathway_cipher or interview.state_cipher or interview.consent_cipher or interview.status != "expired":
                    interview.pathway_cipher = interview.state_cipher = interview.consent_cipher = ""
                    interview.status = "expired"
                    counts["interviews"] += 1
        counts["inbox"] += session.execute(delete(InboundEvent).where(InboundEvent.expires_at <= current)).rowcount
        counts["outbox"] += session.execute(delete(Outbox).where(Outbox.expires_at <= current)).rowcount
        counts["delivery_events"] += session.execute(delete(DeliveryEvent).where(DeliveryEvent.expires_at <= current)).rowcount
        for participant in session.scalars(select(Participant).where(Participant.phone_cipher != "")):
            if participant.active_interview_id in expired_ids:
                participant.active_interview_id = None
            retained = session.scalar(select(Interview.id).where(Interview.participant_id == participant.id, Interview.expires_at > current).limit(1))
            pending_inbox = session.scalar(select(InboundEvent.id).where(InboundEvent.participant_id == participant.id).limit(1))
            pending_outbox = session.scalar(select(Outbox.id).where(Outbox.participant_id == participant.id).limit(1))
            old_contact = participant.last_inbound_at <= current - settings.retention_days * 86400
            if not retained and not pending_inbox and not pending_outbox and (old_contact or participant.id in expired_participants):
                participant.phone_cipher = ""
                participant.last_inbound_at = 0
                participant.active_interview_id = None
                if not participant.opted_out:
                    # Retain anonymized operational row, not a reidentifiable phone HMAC.
                    participant.phone_hash = secrets.token_hex(32)
                counts["identities"] += 1
    return counts


def reconcile_delivery(sessions, *, now: int | None = None) -> int:
    """Apply verified statuses after their provider IDs become known.

    Keep the evidence through retention expiry for deduplication. Positive
    delivery proof is monotonic, including when callbacks arrive out of order.
    """
    current = now_ts() if now is None else now
    changed = 0
    with sessions.begin() as session:
        records = session.execute(select(DeliveryEvent, Outbox).join(Outbox, Outbox.provider_id == DeliveryEvent.provider_id)
            .where(DeliveryEvent.expires_at > current).order_by(DeliveryEvent.timestamp, DeliveryEvent.id))
        for event, outbox in records:
            if event.status == "read":
                allowed = True
            elif event.status == "delivered":
                allowed = outbox.status != "read"
            elif event.status == "failed":
                allowed = outbox.status not in {"delivered", "read"} and event.timestamp >= outbox.delivery_at
            elif event.status == "sent":
                allowed = outbox.status not in {"delivered", "read", "failed"} and event.timestamp >= outbox.delivery_at
            else:
                allowed = False
            if not allowed:
                continue
            error = f"meta_{event.error_code}" if event.status == "failed" and event.error_code is not None else None
            delivery_at = max(outbox.delivery_at, event.timestamp)
            if (outbox.status, outbox.delivery_at, outbox.error_code) != (event.status, delivery_at, error):
                outbox.status, outbox.delivery_at, outbox.error_code = event.status, delivery_at, error
                changed += 1
    return changed


async def _deliver(outbox_id, settings, sessions, vault, gateway, current, lock_guard=None):
    with sessions.begin() as session:
        row = session.get(Outbox, outbox_id)
        if row is None or row.status != "pending":
            return
        participant = session.get(Participant, row.participant_id)
        if participant is None or not participant.phone_cipher:
            row.status, row.error_code = "failed", "recipient_unavailable"
            return
        if participant.opted_out and not row.control_ack:
            row.status, row.error_code = "suppressed", "opted_out"
            return
        if row.expires_at <= current:
            row.status, row.error_code = "expired", "retention_expired"
            return
        if not 0 <= current - participant.last_inbound_at < 86400:
            row.status, row.error_code = "expired", "window_closed"
            return
        try:
            phone, message = vault.open(participant.phone_cipher), vault.open(row.text_cipher)
        except Exception:
            row.status, row.error_code = "failed", "stored_data_unavailable"
            return
        if settings.whatsapp_test_mode and phone not in settings.test_recipients:
            row.status, row.error_code = "suppressed", "test_recipient_not_allowed"
            return
        if lock_guard is not None:
            lock_guard()
        inbound_at = datetime.fromtimestamp(participant.last_inbound_at, timezone.utc)
        row.status, row.error_code = "sending", None
    # The transaction is committed before the external side effect. On crash the
    # startup recovery marks this attempt uncertain, never pending.
    provider_id, status, error = None, "sent", None
    try:
        provider_id = await gateway.send_text(phone, message, inbound_at, now=datetime.fromtimestamp(current, timezone.utc))
    except GatewayError as failure:
        status, error = ("uncertain" if failure.ambiguous else "failed"), failure.code
    except Exception:
        status, error = "uncertain", "worker_send_error"
    with sessions.begin() as session:
        row = session.get(Outbox, outbox_id)
        if row is not None and row.status == "sending":
            row.status, row.provider_id, row.error_code = status, provider_id, error
    reconcile_delivery(sessions, now=current)


async def run_once(settings, sessions, vault, ai, gateway, *, now: int | None = None, lock_guard=None) -> dict:
    """Process one bounded sequential batch; caller owns the singleton lock."""
    current = now_ts() if now is None else now
    if lock_guard is not None:
        lock_guard()
    result = {"inbox": 0, "outbox": 0, "waiting": False, "retention": scrub_retention(settings, sessions, now=current)}
    result["delivery"] = reconcile_delivery(sessions, now=current)
    if gateway is None or not settings.whatsapp_configured:
        result["waiting"] = True
        return result
    with sessions() as session:
        incoming = list(session.scalars(select(InboundEvent.id).where(InboundEvent.status == "queued").order_by(InboundEvent.received_order, InboundEvent.id).limit(100)))
    for event_id in incoming:
        if lock_guard is not None:
            lock_guard()
        with sessions.begin() as session:
            event = session.get(InboundEvent, event_id)
            if event is None or event.status != "queued":
                continue
            event.status = "processing"
        try:
            await process_event(event_id, settings, sessions, vault, ai, gateway)
        except Exception:
            with sessions.begin() as session:
                event = session.get(InboundEvent, event_id)
                if event is not None and event.status == "processing":
                    event.status, event.error_code = "failed", "worker_processing_error"
        result["inbox"] += 1
    with sessions() as session:
        outgoing = list(session.scalars(select(Outbox.id).where(Outbox.status == "pending").order_by(Outbox.created_order, Outbox.id).limit(100)))
    for outbox_id in outgoing:
        # Re-read wall clock after potentially slow AI/media work. Test callers
        # can freeze the clock explicitly, production always checks at send time.
        await _deliver(outbox_id, settings, sessions, vault, gateway, now_ts() if now is None else now, lock_guard)
        result["outbox"] += 1
    return result


async def _serve():
    settings = get_settings()
    engine, sessions = database(settings.database_url)
    vault = Vault(settings.encryption_key.get_secret_value())
    ai = AIClient(settings.openai_api_key.get_secret_value(), settings.transcription_model, settings.decision_model)
    gateway = MetaGateway(settings.whatsapp_access_token.get_secret_value(), settings.whatsapp_phone_number_id, settings.whatsapp_api_version) if settings.whatsapp_configured else None
    stop, loop = asyncio.Event(), asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        with SingletonWorker(engine, settings.database_url) as owner:
            recover_interrupted(sessions)
            print("worker_started" if gateway is not None else "worker_waiting_for_whatsapp_configuration", flush=True)
            while not stop.is_set():
                try:
                    await run_once(settings, sessions, vault, ai, gateway, lock_guard=owner.assert_owned)
                except WorkerLockLost:
                    raise
                except Exception:
                    # No SQL parameters, participant data, token, or provider body.
                    print("worker_cycle_failed", file=sys.stderr, flush=True)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except TimeoutError:
                    pass
    finally:
        if gateway is not None:
            await gateway.aclose()
        engine.dispose()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


def main():
    try:
        asyncio.run(_serve())
    except WorkerAlreadyRunning:
        print("worker_already_running", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        pass
    except Exception:
        print("worker_startup_failed", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
