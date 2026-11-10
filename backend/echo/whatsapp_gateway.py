"""Small, fail-closed adapter for the official WhatsApp Cloud API.

Webhook parsing is stateless. Callers must verify the raw body first, persist
message-ID deduplication, and check participant consent before any reply.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
from typing import Literal
from urllib.parse import urlsplit

import httpx


MAX_AUDIO_BYTES = 16 * 1024 * 1024  # Local safety cap; not a promise of platform limits.
SUPPORTED_AUDIO = frozenset({"audio/aac", "audio/mp4", "audio/mpeg", "audio/amr", "audio/ogg"})


class GatewayError(Exception):
    """Sanitized failure; ambiguous sends must never be retried automatically."""

    def __init__(self, code: str, retryable: bool = False, ambiguous: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class IncomingMessage:
    id: str
    wa_id: str
    timestamp: int
    kind: Literal["text", "audio", "unsupported"]
    text: str | None = None
    media_id: str | None = None
    mime_type: str | None = None
    errors: tuple[dict, ...] = ()


@dataclass(frozen=True)
class DeliveryStatus:
    id: str
    status: str
    timestamp: int
    error_code: int | None = None


def verify_signature(body: bytes, signature: str | None, app_secret: str) -> bool:
    if not app_secret or not isinstance(signature, str) or not re.fullmatch(r"sha256=[0-9a-fA-F]{64}", signature):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature[7:].lower())


def _values(payload: dict, phone_number_id: str):
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("changes"), list):
            continue
        for change in entry["changes"]:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            if isinstance(metadata, dict) and metadata.get("phone_number_id") == phone_number_id:
                yield value


def _timestamp(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}", value):
        return int(value)
    return None


def parse_messages(payload: dict, phone_number_id: str) -> list[IncomingMessage]:
    result = []
    for value in _values(payload, phone_number_id):
        messages = value.get("messages", [])
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            mid, sender, timestamp = message.get("id"), message.get("from"), _timestamp(message.get("timestamp"))
            if not isinstance(mid, str) or not mid or not isinstance(sender, str) or not sender or timestamp is None:
                continue
            raw_errors = message.get("errors", [])
            errors = tuple(error for error in raw_errors if isinstance(error, dict)) if isinstance(raw_errors, list) else ()
            kind, text, media_id, mime_type = "unsupported", None, None, None
            content = message.get(message.get("type")) if isinstance(message.get("type"), str) else None
            if not errors and isinstance(content, dict):
                if message["type"] == "text" and isinstance(content.get("body"), str):
                    kind, text = "text", content["body"]
                elif message["type"] == "audio" and isinstance(content.get("id"), str) and content["id"]:
                    kind, media_id = "audio", content["id"]
                    mime_type = content.get("mime_type") if isinstance(content.get("mime_type"), str) else None
            result.append(IncomingMessage(mid, sender, timestamp, kind, text, media_id, mime_type, errors))
    return result


def parse_statuses(payload: dict, phone_number_id: str) -> list[DeliveryStatus]:
    result = []
    for value in _values(payload, phone_number_id):
        statuses = value.get("statuses", [])
        if not isinstance(statuses, list):
            continue
        for status in statuses:
            if not isinstance(status, dict):
                continue
            mid, state, timestamp = status.get("id"), status.get("status"), _timestamp(status.get("timestamp"))
            if not isinstance(mid, str) or not mid or not isinstance(state, str) or not state or timestamp is None:
                continue
            errors = status.get("errors")
            error_code = None
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                candidate = errors[0].get("code")
                if isinstance(candidate, int) and not isinstance(candidate, bool):
                    error_code = candidate
            result.append(DeliveryStatus(mid, state, timestamp, error_code))
    return result


def _mime(value) -> str:
    return value.split(";", 1)[0].strip().lower() if isinstance(value, str) else ""


def _media_url(url) -> str:
    if not isinstance(url, str) or any(ord(char) < 33 for char in url):
        raise GatewayError("unsafe_media_url")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        allowed = host == "lookaside.fbsbx.com" or host.endswith(".lookaside.fbsbx.com")
        if parsed.scheme != "https" or not allowed or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment:
            raise GatewayError("unsafe_media_url")
    except ValueError:
        raise GatewayError("unsafe_media_url") from None
    return url


class MetaGateway:
    def __init__(self, access_token: str, phone_number_id: str, graph_api_version: str, client: httpx.AsyncClient | None = None):
        if not isinstance(graph_api_version, str) or not re.fullmatch(r"v[0-9]{2,3}\.[0-9]+", graph_api_version):
            raise ValueError("An explicit supported Graph API version (vNN.N) is required")
        if not access_token or not re.fullmatch(r"[0-9]+", phone_number_id):
            raise ValueError("Meta access token and numeric phone-number ID are required")
        self.phone_number_id = phone_number_id
        self.base_url = f"https://graph.facebook.com/{graph_api_version}"
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=30, follow_redirects=False)

    async def aclose(self):
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _response_error(response: httpx.Response, outbound: bool = False):
        if 200 <= response.status_code < 300:
            return
        code = f"http_{response.status_code}"
        try:
            error = response.json().get("error", {})
            if isinstance(error, dict) and isinstance(error.get("code"), int):
                code = f"meta_{error['code']}"
        except (ValueError, AttributeError):
            pass
        raise GatewayError(code, retryable=response.status_code == 429 or response.status_code >= 500,
                           ambiguous=outbound and response.status_code >= 500)

    async def download_audio(self, media_id: str) -> tuple[bytes, str]:
        if not isinstance(media_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", media_id):
            raise GatewayError("invalid_media_id")
        try:
            response = await self._client.get(f"{self.base_url}/{media_id}", params={"phone_number_id": self.phone_number_id},
                                              headers=self._headers, follow_redirects=False, timeout=30)
            self._response_error(response)
            if len(response.content) > 64 * 1024:
                raise GatewayError("invalid_media_metadata")
            try:
                metadata = response.json()
            except ValueError:
                raise GatewayError("invalid_media_metadata") from None
            if not isinstance(metadata, dict):
                raise GatewayError("invalid_media_metadata")
            url = _media_url(metadata.get("url"))
            mime = _mime(metadata.get("mime_type"))
            if mime not in SUPPORTED_AUDIO:
                raise GatewayError("unsupported_audio")
            size = metadata.get("file_size")
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                raise GatewayError("invalid_media_metadata")
            if size > MAX_AUDIO_BYTES:
                raise GatewayError("media_too_large")
            async with self._client.stream("GET", url, headers=self._headers, follow_redirects=False, timeout=30) as stream:
                if not 200 <= stream.status_code < 300:
                    raise GatewayError(f"media_http_{stream.status_code}", retryable=stream.status_code == 429 or stream.status_code >= 500)
                if _mime(stream.headers.get("content-type")) != mime:
                    raise GatewayError("unsupported_audio")
                length = stream.headers.get("content-length")
                if length is not None:
                    if not re.fullmatch(r"[0-9]+", length):
                        raise GatewayError("invalid_media_metadata")
                    if int(length) > MAX_AUDIO_BYTES:
                        raise GatewayError("media_too_large")
                data = bytearray()
                async for chunk in stream.aiter_bytes(chunk_size=64 * 1024):
                    if len(data) + len(chunk) > MAX_AUDIO_BYTES:
                        raise GatewayError("media_too_large")
                    data.extend(chunk)
                if not data:
                    raise GatewayError("invalid_audio")
                return bytes(data), mime
        except httpx.RequestError:
            raise GatewayError("media_transport_error", retryable=True) from None

    @staticmethod
    def _recipient(to: str) -> str:
        if not isinstance(to, str) or not re.fullmatch(r"\+?[0-9]{6,20}", to):
            raise GatewayError("invalid_recipient")
        return to.lstrip("+")

    async def _send(self, to: str, content: dict) -> str:
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": self._recipient(to), **content}
        try:
            response = await self._client.post(f"{self.base_url}/{self.phone_number_id}/messages", headers=self._headers,
                                               json=payload, follow_redirects=False, timeout=30)
        except httpx.RequestError:
            # A lost response cannot establish whether Meta accepted the message.
            raise GatewayError("send_transport_error", ambiguous=True) from None
        self._response_error(response, outbound=True)
        try:
            mid = response.json()["messages"][0]["id"]
            if isinstance(mid, str) and mid:
                return mid
        except (ValueError, KeyError, IndexError, TypeError):
            pass
        raise GatewayError("invalid_meta_response", ambiguous=True)

    async def send_text(self, to: str, text: str, last_inbound_at: datetime, now: datetime | None = None) -> str:
        """Reply only; the caller must also enforce research consent/opt-out."""
        now = now if now is not None else datetime.now(timezone.utc)
        if not isinstance(last_inbound_at, datetime) or last_inbound_at.tzinfo is None or last_inbound_at.utcoffset() is None or now.tzinfo is None or now.utcoffset() is None:
            raise GatewayError("invalid_window_timestamp")
        if not timedelta(0) <= now - last_inbound_at < timedelta(hours=24):
            raise GatewayError("window_closed")
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise GatewayError("invalid_text")
        return await self._send(to, {"type": "text", "text": {"preview_url": False, "body": text}})

    async def send_template(self, to: str, name: str, language_code: str, parameters: list[str], opted_in: bool, approved_templates: set[str]) -> str:
        if opted_in is not True:
            raise GatewayError("opt_in_required")
        if name not in approved_templates:
            raise GatewayError("template_not_approved")
        if not re.fullmatch(r"[a-z0-9_]{1,512}", name) or not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", language_code):
            raise GatewayError("invalid_template")
        if not isinstance(parameters, list) or any(not isinstance(value, str) or not value or len(value) > 4096 for value in parameters):
            raise GatewayError("invalid_template_parameters")
        template = {"name": name, "language": {"code": language_code}}
        if parameters:
            template["components"] = [{"type": "body", "parameters": [{"type": "text", "text": value} for value in parameters]}]
        return await self._send(to, {"type": "template", "template": template})
