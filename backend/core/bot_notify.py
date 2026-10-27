"""Backend -> bot channel (Telegram is rendered by the bot service, not here).

- `emit(event, data)`: queue a notification. It is sent after the surrounding DB
  transaction commits (`transaction.on_commit`), by the Celery task `core.tasks.notify_bot`.
- `send_event_sync(event, data)`: send now and return the bot's answer (jobs that need
  to know whether the person was reached).
- `fetch_file(file_id)`: bytes of a Telegram file (receipt, screenshot) via the bot.

Wire format and event catalogue: docs/BOT_CONTRACT.md. Calls are signed with
`core.bot_signing` (key = BOT_TOKEN).
"""

from __future__ import annotations

import json
import logging
import uuid
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from .bot_signing import HEADER_ACTOR, HEADER_SIG, HEADER_TS, signed_headers

log = logging.getLogger("core.bot_notify")


class BotUnavailable(Exception):
    """The bot could not be reached or answered 5xx: worth retrying."""


def _server() -> str:
    return (settings.TELEGRAM_BOT_SERVER or "").rstrip("/")


def _jsonable(data: dict) -> dict:
    """Decimals / dates / times -> JSON types (Celery's JSON serializer needs it)."""
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


def make_envelope(event: str, data: dict) -> dict:
    return {"id": str(uuid.uuid4()), "event": event, "data": _jsonable(data)}


def emit(event: str, data: dict) -> str:
    """Queue `event` for the bot once the current transaction commits. Never raises:
    a broken broker must not undo a booking. Returns the envelope id."""
    envelope = make_envelope(event, data)

    def _send():
        try:
            from .tasks import notify_bot

            notify_bot.delay(envelope)
        except Exception:  # noqa: BLE001
            log.exception("could not queue %s", event)

    transaction.on_commit(_send)
    return envelope["id"]


def _post(path: str, envelope: dict, timeout: float) -> requests.Response:
    body = json.dumps(envelope, ensure_ascii=False).encode()
    headers = signed_headers("POST", path, None, body)
    headers["Content-Type"] = "application/json"
    return requests.post(_server() + path, data=body, headers=headers, timeout=timeout)


def post_envelope(envelope: dict, timeout: float = 15) -> dict:
    """POST an envelope to the bot. Returns the bot's JSON answer.
    Raises BotUnavailable on connection errors / 5xx; for a 4xx returns
    {"ok": False, "status": <code>, "detail": ...} (not retried)."""
    if not _server():
        log.warning("BOT_SERVER is not set; %s dropped", envelope.get("event"))
        return {"ok": False, "status": 0, "detail": "BOT_SERVER is not set", "delivered": []}
    try:
        r = _post("/notify", envelope, timeout)
    except requests.RequestException as e:
        raise BotUnavailable(str(e)) from e
    if r.status_code >= 500:
        raise BotUnavailable(f"bot answered {r.status_code}")
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        log.error("bot refused %s: %s %s", envelope.get("event"), r.status_code, str(body)[:300])
        return {"ok": False, "status": r.status_code, "detail": body, "delivered": []}
    return body


def send_event_sync(
    event: str, data: dict, timeout: float = 10, envelope_id: str | None = None
) -> dict:
    """Send now (not after commit) and return the bot's answer
    `{"ok": True, "delivered": [...]}`. Raises BotUnavailable when the bot is down.
    `envelope_id`: a deterministic id (see deterministic_id) makes a resend after a timeout
    a duplicate the bot ignores."""
    env = make_envelope(event, data)
    if envelope_id:
        env["id"] = envelope_id
    return post_envelope(env, timeout=timeout)


def deterministic_id(*parts) -> str:
    """Stable uuid5 of `parts` (e.g. day, once-name, recipient)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "sermebel:" + ":".join(str(p) for p in parts)))


def fetch_file(file_id: str) -> tuple[bytes, str] | None:
    """(bytes, content-type) of a Telegram file, or None when it can't be served."""
    if not file_id or not _server():
        return None
    path = f"/files/{quote(str(file_id), safe='')}"
    try:
        r = requests.get(_server() + path, headers=signed_headers("GET", path), timeout=15)
    except requests.RequestException:
        log.warning("bot /files unreachable")
        return None
    if r.status_code != 200:
        return None
    return r.content, r.headers.get("Content-Type", "application/octet-stream")


__all__ = [
    "BotUnavailable",
    "HEADER_ACTOR",
    "HEADER_SIG",
    "HEADER_TS",
    "emit",
    "fetch_file",
    "make_envelope",
    "post_envelope",
    "send_event_sync",
]
