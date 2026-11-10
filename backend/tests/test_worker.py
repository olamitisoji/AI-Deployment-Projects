from datetime import datetime, timezone

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import select

from echo.config import Settings
from echo.database import Base, DeliveryEvent, InboundEvent, Interview, Outbox, Participant, Project, Study, Turn, database
from echo.security import Vault
from echo.whatsapp_gateway import GatewayError
from echo.worker import SingletonWorker, WorkerAlreadyRunning, WorkerLockLost, reconcile_delivery, recover_interrupted, run_once, scrub_retention


NOW = 1_794_312_000


@pytest.fixture
def local(tmp_path):
    settings = Settings(_env_file=None, encryption_key=Fernet.generate_key().decode(), researcher_token="r" * 32,
        database_url=f"sqlite:///{tmp_path / 'test.db'}", whatsapp_access_token="fake", whatsapp_app_secret="fake",
        whatsapp_verify_token="fake", whatsapp_phone_number_id="12345", whatsapp_api_version="v99.0",
        whatsapp_display_number="15550000000", test_recipient_allowlist="15551234567")
    engine, sessions = database(settings.database_url)
    Base.metadata.create_all(engine)
    vault = Vault(settings.encryption_key.get_secret_value())
    with sessions.begin() as session:
        project = Project(name="Test")
        session.add(project)
        session.flush()
        study = Study(project_id=project.id, title="Test", pathway="{}")
        participant = Participant(phone_hash=vault.phone_hash("15551234567"), phone_cipher=vault.seal("15551234567"), last_inbound_at=NOW - 60)
        session.add_all([study, participant])
        session.flush()
        ids = {"study": study.id, "participant": participant.id}
    yield settings, sessions, vault, ids, engine
    engine.dispose()


def add_outbox(local, **changes):
    _, sessions, vault, ids, _ = local
    fields = dict(event_id="event1", participant_id=ids["participant"], text_cipher=vault.seal("Hello"), expires_at=NOW + 1000)
    fields.update(changes)
    with sessions.begin() as session:
        row = Outbox(**fields)
        session.add(row)
        session.flush()
        return row.id


class FakeGateway:
    def __init__(self, sessions, error=None):
        self.sessions, self.error, self.sent = sessions, error, []

    async def send_text(self, to, text, last_inbound_at, now=None):
        # Durable intent must precede any external side effect.
        with self.sessions() as session:
            assert session.scalar(select(Outbox.status)) == "sending"
        self.sent.append((to, text, last_inbound_at))
        if self.error:
            raise self.error
        return "wamid.accepted"


@pytest.mark.asyncio
async def test_outbox_commits_sending_before_network_then_saves_provider_id(local):
    settings, sessions, vault, _, _ = local
    out_id = add_outbox(local)
    gateway = FakeGateway(sessions)
    await run_once(settings, sessions, vault, None, gateway, now=NOW)
    with sessions() as session:
        row = session.get(Outbox, out_id)
        assert (row.status, row.provider_id) == ("sent", "wamid.accepted")
    assert gateway.sent == [("15551234567", "Hello", datetime.fromtimestamp(NOW - 60, timezone.utc))]


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status,code", [
    (GatewayError("send_transport_error", ambiguous=True), "uncertain", "send_transport_error"),
    (GatewayError("meta_190"), "failed", "meta_190"),
])
async def test_failed_or_ambiguous_send_never_automatically_retried(local, error, status, code):
    settings, sessions, vault, _, _ = local
    out_id = add_outbox(local)
    gateway = FakeGateway(sessions, error)
    await run_once(settings, sessions, vault, None, gateway, now=NOW)
    await run_once(settings, sessions, vault, None, gateway, now=NOW)
    with sessions() as session:
        row = session.get(Outbox, out_id)
        assert (row.status, row.error_code) == (status, code)
    assert len(gateway.sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("opted_out,last_inbound,control_ack,wanted", [
    (True, NOW - 60, False, "suppressed"),
    (True, NOW - 60, True, "sent"),
    (False, NOW - 86400, False, "expired"),
    (False, NOW + 1, False, "expired"),
])
async def test_send_rechecks_stop_and_genuine_latest_inbound_window(local, opted_out, last_inbound, control_ack, wanted):
    settings, sessions, vault, ids, _ = local
    out_id = add_outbox(local, control_ack=control_ack)
    with sessions.begin() as session:
        participant = session.get(Participant, ids["participant"])
        participant.opted_out, participant.last_inbound_at = opted_out, last_inbound
    gateway = FakeGateway(sessions)
    await run_once(settings, sessions, vault, None, gateway, now=NOW)
    with sessions() as session:
        assert session.get(Outbox, out_id).status == wanted
    assert len(gateway.sent) == (1 if wanted == "sent" else 0)


@pytest.mark.asyncio
async def test_inbox_processes_before_pending_outbox_and_can_suppress_it(local, monkeypatch):
    settings, sessions, vault, ids, _ = local
    out_id = add_outbox(local)
    with sessions.begin() as session:
        session.add(InboundEvent(id="stop-event", participant_id=ids["participant"], payload_cipher=vault.seal({"text": "STOP"}), expires_at=NOW + 1000))
    async def process(event_id, settings, session_factory, vault, ai, gateway):
        with session_factory.begin() as session:
            event = session.get(InboundEvent, event_id)
            assert event.status == "processing"
            session.get(Participant, event.participant_id).opted_out = True
            event.status = "done"
    monkeypatch.setattr("echo.worker.process_event", process)
    gateway = FakeGateway(sessions)
    await run_once(settings, sessions, vault, None, gateway, now=NOW)
    with sessions() as session:
        assert session.get(InboundEvent, "stop-event").status == "done"
        assert session.get(Outbox, out_id).status == "suppressed"
    assert not gateway.sent


@pytest.mark.asyncio
async def test_missing_whatsapp_configuration_does_not_attempt_external_work(local, monkeypatch):
    settings, sessions, vault, ids, _ = local
    settings.whatsapp_phone_number_id = ""
    add_outbox(local)
    with sessions.begin() as session:
        session.add(InboundEvent(id="event", participant_id=ids["participant"], payload_cipher=vault.seal({}), expires_at=NOW + 1000))
    async def forbidden(*args):
        raise AssertionError("must wait for configuration")
    monkeypatch.setattr("echo.worker.process_event", forbidden)
    gateway = FakeGateway(sessions)
    result = await run_once(settings, sessions, vault, None, gateway, now=NOW)
    assert result["waiting"]
    assert not gateway.sent
    with sessions() as session:
        assert session.get(InboundEvent, "event").status == "queued"


def test_startup_recovery_requeues_model_work_but_never_resends_unknown_sends(local):
    _, sessions, vault, ids, _ = local
    out_id = add_outbox(local, status="sending")
    with sessions.begin() as session:
        session.add(InboundEvent(id="event", participant_id=ids["participant"], payload_cipher=vault.seal({}), status="processing", expires_at=NOW + 1000))
    recover_interrupted(sessions)
    with sessions() as session:
        assert session.get(InboundEvent, "event").status == "queued"
        row = session.get(Outbox, out_id)
        assert (row.status, row.error_code) == ("uncertain", "worker_interrupted_send")


@pytest.mark.parametrize("opted_out", [True, False])
def test_retention_scrubs_content_and_identity_but_preserves_only_optout_hash(local, opted_out):
    settings, sessions, vault, ids, _ = local
    original_hash = vault.phone_hash("15551234567")
    with sessions.begin() as session:
        participant = session.get(Participant, ids["participant"])
        participant.opted_out = opted_out
        participant.last_inbound_at = NOW - 10 * 86400
        interview = Interview(study_id=ids["study"], participant_id=participant.id, pathway_cipher=vault.seal({"secret": "path"}), state_cipher=vault.seal({"secret": "state"}), consent_cipher=vault.seal({"secret": "consent"}), expires_at=NOW - 1)
        session.add(interview)
        session.flush()
        participant.active_interview_id = interview.id
        session.add(Turn(interview_id=interview.id, event_id="old", payload_cipher=vault.seal({"secret": "turn"})))
        session.add(InboundEvent(id="old", participant_id=participant.id, payload_cipher=vault.seal({"secret": "inbox"}), expires_at=NOW - 1))
        interview_id = interview.id
    old_out = add_outbox(local, interview_id=interview_id, expires_at=NOW - 1)
    scrub_retention(settings, sessions, now=NOW)
    with sessions() as session:
        participant = session.get(Participant, ids["participant"])
        interview = session.get(Interview, interview_id)
        assert (interview.pathway_cipher, interview.state_cipher, interview.consent_cipher, interview.status) == ("", "", "", "expired")
        assert participant.phone_cipher == ""
        assert participant.active_interview_id is None
        assert (participant.phone_hash == original_hash) is opted_out
        assert session.get(InboundEvent, "old") is None
        assert session.get(Outbox, old_out) is None
        assert session.scalars(select(Turn)).all() == []
        assert session.get(Study, ids["study"]) is not None


def test_retention_keeps_fresh_unprocessed_participant_contact(local):
    settings, sessions, vault, ids, _ = local
    with sessions.begin() as session:
        session.add(InboundEvent(id="fresh", participant_id=ids["participant"], payload_cipher=vault.seal({}), expires_at=NOW + 1000))
    scrub_retention(settings, sessions, now=NOW)
    with sessions() as session:
        assert vault.open(session.get(Participant, ids["participant"]).phone_cipher) == "15551234567"


def test_sqlite_worker_lock_prevents_two_senders(local):
    settings, _, _, _, engine = local
    with SingletonWorker(engine, settings.database_url):
        with pytest.raises(WorkerAlreadyRunning):
            with SingletonWorker(engine, settings.database_url):
                pass
    # Releasing the owner permits a clean restart.
    with SingletonWorker(engine, settings.database_url):
        pass


@pytest.mark.asyncio
async def test_lost_sender_lock_stops_before_dispatch(local):
    settings, sessions, vault, _, _ = local
    out_id = add_outbox(local)
    gateway = FakeGateway(sessions)
    def lost():
        raise WorkerLockLost("worker_lock_lost")
    with pytest.raises(WorkerLockLost):
        await run_once(settings, sessions, vault, None, gateway, now=NOW, lock_guard=lost)
    with sessions() as session:
        assert session.get(Outbox, out_id).status == "pending"
    assert not gateway.sent


def test_released_local_lock_no_longer_claims_ownership(local):
    settings, _, _, _, engine = local
    owner = SingletonWorker(engine, settings.database_url)
    with owner:
        owner.assert_owned()
    with pytest.raises(WorkerLockLost):
        owner.assert_owned()


@pytest.mark.asyncio
async def test_same_second_inbox_respects_receipt_order_not_lexical_message_id(local, monkeypatch):
    settings, sessions, vault, ids, _ = local
    with sessions.begin() as session:
        for message_id in ("z-first", "a-second"):
            session.add(InboundEvent(id=message_id, participant_id=ids["participant"], payload_cipher=vault.seal({}), created_at=NOW, expires_at=NOW + 1000))
            session.flush()
    processed = []
    async def process(event_id, settings, session_factory, vault, ai, gateway):
        processed.append(event_id)
        with session_factory.begin() as session:
            session.get(InboundEvent, event_id).status = "done"
    monkeypatch.setattr("echo.worker.process_event", process)
    await run_once(settings, sessions, vault, None, FakeGateway(sessions), now=NOW)
    assert processed == ["z-first", "a-second"]


@pytest.mark.asyncio
async def test_same_second_outbox_respects_creation_order_not_random_id(local):
    settings, sessions, vault, ids, _ = local
    with sessions.begin() as session:
        for row_id, message in (("z-first", "first"), ("a-second", "second")):
            session.add(Outbox(id=row_id, event_id=row_id, participant_id=ids["participant"], text_cipher=vault.seal(message), created_at=NOW, expires_at=NOW + 1000))
            session.flush()
    sent = []
    class Gateway:
        async def send_text(self, to, message, last_inbound_at, now=None):
            sent.append(message)
            return f"wamid.{len(sent)}"
    await run_once(settings, sessions, vault, None, Gateway(), now=NOW)
    assert sent == ["first", "second"]


@pytest.mark.asyncio
async def test_signed_status_before_send_response_is_reconciled_and_deduplicated(local, monkeypatch):
    import hashlib
    import hmac
    import json
    from fastapi.testclient import TestClient
    from echo.api import create_app

    settings, sessions, vault, _, _ = local
    monkeypatch.setattr("echo.api.now_ts", lambda: NOW)
    out_id = add_outbox(local)
    app = create_app(settings, initialize_schema=True)
    with TestClient(app) as client:
        class Gateway:
            async def send_text(self, to, message, last_inbound_at, now=None):
                # Meta posts delivery while its send response is still in flight.
                body = json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
                    "metadata": {"phone_number_id": "12345"},
                    "statuses": [{"id": "wamid.early", "status": "delivered", "timestamp": str(NOW)}]}}]}]}).encode()
                signature = "sha256=" + hmac.new(b"fake", body, hashlib.sha256).hexdigest()
                for _ in range(2):
                    assert client.post("/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": signature}).status_code == 200
                return "wamid.early"
        await run_once(settings, sessions, vault, None, Gateway(), now=NOW)
    with sessions() as session:
        row = session.get(Outbox, out_id)
        assert (row.status, row.provider_id, row.delivery_at) == ("delivered", "wamid.early", NOW)
        assert len(session.scalars(select(DeliveryEvent)).all()) == 1


def test_delivery_reconciliation_keeps_positive_proof_across_out_of_order_failure(local):
    _, sessions, _, _, _ = local
    out_id = add_outbox(local, status="sent", provider_id="wamid.order")
    with sessions.begin() as session:
        session.add(DeliveryEvent(id="failed", provider_id="wamid.order", status="failed", timestamp=NOW - 10, error_code=131047, expires_at=NOW + 1000))
    reconcile_delivery(sessions, now=NOW)
    with sessions() as session:
        assert session.get(Outbox, out_id).error_code == "meta_131047"
    # Positive proof can arrive late with an older provider timestamp.
    with sessions.begin() as session:
        session.add(DeliveryEvent(id="delivered", provider_id="wamid.order", status="delivered", timestamp=NOW - 20, expires_at=NOW + 1000))
    reconcile_delivery(sessions, now=NOW)
    with sessions() as session:
        row = session.get(Outbox, out_id)
        assert (row.status, row.error_code) == ("delivered", None)
    with sessions.begin() as session:
        session.add_all([
            DeliveryEvent(id="read", provider_id="wamid.order", status="read", timestamp=NOW - 5, expires_at=NOW + 1000),
            DeliveryEvent(id="latefailed", provider_id="wamid.order", status="failed", timestamp=NOW, error_code=131000, expires_at=NOW + 1000),
        ])
    reconcile_delivery(sessions, now=NOW)
    reconcile_delivery(sessions, now=NOW)
    with sessions() as session:
        row = session.get(Outbox, out_id)
        assert (row.status, row.error_code) == ("read", None)


def test_retention_removes_expired_unmatched_delivery_events(local):
    settings, sessions, _, _, _ = local
    with sessions.begin() as session:
        session.add_all([
            DeliveryEvent(id="expired", provider_id="unknown", status="sent", timestamp=NOW - 100, expires_at=NOW - 1),
            DeliveryEvent(id="retained", provider_id="unknown", status="sent", timestamp=NOW, expires_at=NOW + 1000),
        ])
    scrub_retention(settings, sessions, now=NOW)
    with sessions() as session:
        assert session.get(DeliveryEvent, "expired") is None
        assert session.get(DeliveryEvent, "retained") is not None
