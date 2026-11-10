import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from echo.whatsapp_gateway import GatewayError, MetaGateway, parse_messages, parse_statuses, verify_signature


def event(messages=None, statuses=None, phone="12345"):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{
        "field": "messages", "value": {"metadata": {"phone_number_id": phone},
        "messages": messages or [], "statuses": statuses or []}}]}]}


def test_signature_uses_exact_raw_body_and_rejects_missing_or_wrong_secret():
    body = b'{"entry": []}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, signature, "secret")
    assert not verify_signature(body + b" ", signature, "secret")
    assert not verify_signature(body, signature, "wrong")
    assert not verify_signature(body, None, "secret")
    assert not verify_signature(body, "sha256=invalid", "secret")
    assert not verify_signature(body, signature, "")


def test_parse_text_audio_and_error_without_silently_dropping_unsupported():
    payload = event([
        {"id": "text1", "from": "15551234567", "timestamp": "1700000000", "type": "text", "text": {"body": "hello"}},
        {"id": "audio1", "from": "15551234567", "timestamp": "1700000001", "type": "audio", "audio": {"id": "9876", "mime_type": "audio/ogg; codecs=opus"}},
        {"id": "bad1", "from": "15551234567", "timestamp": "1700000002", "type": "unknown", "errors": [{"code": 131051, "title": "Unsupported message type"}]},
    ])
    text, audio, unsupported = parse_messages(payload, "12345")
    assert (text.id, text.wa_id, text.timestamp, text.kind, text.text) == ("text1", "15551234567", 1700000000, "text", "hello")
    assert (audio.kind, audio.media_id, audio.mime_type) == ("audio", "9876", "audio/ogg; codecs=opus")
    assert unsupported.kind == "unsupported"
    assert unsupported.errors[0]["code"] == 131051
    assert parse_messages(payload, "wrong-phone") == []
    # Parsing is deterministic; durable message-ID deduplication belongs to the inbox.
    assert parse_messages(payload, "12345") == parse_messages(payload, "12345")


def test_parse_statuses_including_failed_delivery_and_ignore_other_phone():
    payload = event(statuses=[
        {"id": "out1", "status": "delivered", "timestamp": "1700000000"},
        {"id": "out2", "status": "failed", "timestamp": "1700000001", "errors": [{"code": 131047, "title": "Window expired"}]},
    ])
    good, bad = parse_statuses(payload, "12345")
    assert (good.id, good.status, good.timestamp, good.error_code) == ("out1", "delivered", 1700000000, None)
    assert (bad.status, bad.error_code) == ("failed", 131047)
    assert parse_statuses(payload, "other") == []
    assert parse_messages({"entry": [None, {"changes": [None]}]}, "12345") == []


def gateway(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MetaGateway("not-a-real-token", "12345", "v99.0", client=client), client


def test_gateway_requires_explicit_well_formed_version():
    for version in ["", "latest", "26.0", "v26.0/evil"]:
        with pytest.raises(ValueError):
            MetaGateway("token", "12345", version)


@pytest.mark.asyncio
async def test_audio_download_uses_authenticated_metadata_then_allowlisted_media():
    seen = []
    def handler(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer not-a-real-token"
        if request.url.host == "graph.facebook.com":
            assert request.url.path == "/v99.0/9876"
            assert request.url.params["phone_number_id"] == "12345"
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=9876", "mime_type": "audio/ogg", "file_size": 4})
        return httpx.Response(200, content=b"OggS", headers={"content-type": "audio/ogg; codecs=opus"})
    gw, client = gateway(handler)
    async with client:
        assert await gw.download_audio("9876") == (b"OggS", "audio/ogg")
    assert len(seen) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://lookaside.fbsbx.com/file", "https://localhost/file", "https://127.0.0.1/file",
    "https://lookaside.fbsbx.com.evil.test/file", "https://evil.test@lookaside.fbsbx.com/file",
    "https://lookaside.fbsbx.com:444/file", "https://graph.facebook.com/file",
])
async def test_media_url_cannot_leak_token_to_arbitrary_host(url):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"url": url, "mime_type": "audio/ogg", "file_size": 4})
    gw, client = gateway(handler)
    async with client:
        with pytest.raises(GatewayError) as error:
            await gw.download_audio("9876")
    assert error.value.code == "unsafe_media_url"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("size,mime,body,headers,expected", [
    (16 * 1024 * 1024 + 1, "audio/ogg", b"", {}, "media_too_large"),
    (4, "image/png", b"", {}, "unsupported_audio"),
    (4, "audio/ogg", b"OggS", {"content-type": "text/html"}, "unsupported_audio"),
    (4, "audio/ogg", b"OggS", {"content-type": "audio/ogg", "content-length": "16777217"}, "media_too_large"),
    (4, "audio/ogg", b"x" * (16 * 1024 * 1024 + 1), {"content-type": "audio/ogg"}, "media_too_large"),
])
async def test_media_checks_metadata_and_actual_download(size, mime, body, headers, expected):
    def handler(request):
        if request.url.host == "graph.facebook.com":
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/file", "mime_type": mime, "file_size": size})
        return httpx.Response(200, content=body, headers=headers)
    gw, client = gateway(handler)
    async with client:
        with pytest.raises(GatewayError) as error:
            await gw.download_audio("9876")
    assert error.value.code == expected


@pytest.mark.asyncio
async def test_media_does_not_follow_redirects_even_if_client_default_does():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.host == "graph.facebook.com":
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/file", "mime_type": "audio/ogg", "file_size": 4})
        return httpx.Response(302, headers={"location": "https://evil.test/steal"})
    gw, client = gateway(handler)
    client.follow_redirects = True
    async with client:
        with pytest.raises(GatewayError):
            await gw.download_audio("9876")
    assert len(requests) == 2


NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_freeform_send_checks_window_and_emits_meta_text_payload():
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.path == "/v99.0/12345/messages"
        assert json.loads(request.content) == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": "15551234567", "type": "text", "text": {"preview_url": False, "body": "Hello"}}
        return httpx.Response(200, json={"messages": [{"id": "wamid.out1"}]})
    gw, client = gateway(handler)
    async with client:
        assert await gw.send_text("15551234567", "Hello", NOW - timedelta(hours=23), now=NOW) == "wamid.out1"
        for inbound in [NOW - timedelta(hours=24), NOW + timedelta(seconds=1), NOW.replace(tzinfo=None)]:
            with pytest.raises(GatewayError):
                await gw.send_text("15551234567", "Hello", inbound, now=NOW)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_template_requires_optin_and_configured_approval():
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.template"}]})
    gw, client = gateway(handler)
    async with client:
        for opted_in, approved in [(False, {"study_invite"}), (True, set())]:
            with pytest.raises(GatewayError):
                await gw.send_template("15551234567", "study_invite", "en_US", ["Alex"], opted_in, approved)
        assert await gw.send_template("15551234567", "study_invite", "en_US", ["Alex"], True, {"study_invite"}) == "wamid.template"
    assert len(sent) == 1
    assert sent[0]["template"] == {"name": "study_invite", "language": {"code": "en_US"}, "components": [{"type": "body", "parameters": [{"type": "text", "text": "Alex"}]}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("response,code,retryable,ambiguous", [
    (httpx.Response(401, json={"error": {"code": 190, "message": "secret-token"}}), "meta_190", False, False),
    (httpx.Response(400, json={"error": {"code": 131047}}), "meta_131047", False, False),
    (httpx.Response(429, json={"error": {"code": 130429}}), "meta_130429", True, False),
    (httpx.Response(503, text="bad gateway"), "http_503", True, True),
    (httpx.Response(200, json={}), "invalid_meta_response", False, True),
])
async def test_send_errors_are_sanitized_and_never_automatically_retried(response, code, retryable, ambiguous):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        return response
    gw, client = gateway(handler)
    async with client:
        with pytest.raises(GatewayError) as error:
            await gw.send_text("15551234567", "Hi", NOW, now=NOW)
    assert (error.value.code, error.value.retryable, error.value.ambiguous) == (code, retryable, ambiguous)
    assert "secret-token" not in str(error.value)
    assert count == 1


@pytest.mark.asyncio
async def test_send_timeout_is_ambiguous_and_not_retried():
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("possible accepted send", request=request)
    gw, client = gateway(handler)
    async with client:
        with pytest.raises(GatewayError) as error:
            await gw.send_text("15551234567", "Hi", NOW, now=NOW)
    assert error.value.ambiguous
    assert not error.value.retryable
    assert count == 1
