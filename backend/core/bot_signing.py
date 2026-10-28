"""HMAC signing shared by backend -> bot and bot -> backend internal calls.

Headers: X-Bot-Timestamp (unix seconds), X-Bot-Actor (Telegram id or empty),
X-Bot-Nonce (uuid4 hex, 32 chars), X-Bot-Signature (hex HMAC-SHA256 keyed with BOT_TOKEN).
Signed message: ts, METHOD, path_with_query, actor, nonce, each followed by a newline,
then the raw body (see docs/BOT_CONTRACT.md).
See docs/BOT_CONTRACT.md section 1.
"""

import hashlib
import hmac
import time
import uuid

from django.conf import settings

MAX_SKEW = 300  # seconds

HEADER_TS = "X-Bot-Timestamp"
HEADER_ACTOR = "X-Bot-Actor"
HEADER_NONCE = "X-Bot-Nonce"
HEADER_SIG = "X-Bot-Signature"


def _key(token: str | None = None) -> bytes:
    return (token if token is not None else (settings.TELEGRAM_BOT_TOKEN or "")).encode()


def sign(
    ts, method: str, path: str, actor, body: bytes = b"", token: str | None = None, nonce: str = ""
) -> str:
    actor = "" if actor is None else str(actor)
    msg = f"{int(ts)}\n{method.upper()}\n{path}\n{actor}\n{nonce}\n".encode() + (body or b"")
    return hmac.new(_key(token), msg, hashlib.sha256).hexdigest()


def verify(
    signature: str,
    ts,
    method: str,
    path: str,
    actor,
    body: bytes = b"",
    token: str | None = None,
    now: float | None = None,
    nonce: str = "",
) -> bool:
    """True when the timestamp is fresh (+-MAX_SKEW s) and the signature matches."""
    try:
        ts_int = int(ts)
    except (TypeError, ValueError):
        return False
    if abs((time.time() if now is None else now) - ts_int) > MAX_SKEW:
        return False
    if not settings.TELEGRAM_BOT_TOKEN and token is None:
        return False
    expected = sign(ts_int, method, path, actor, body, token, nonce)
    return hmac.compare_digest(expected, str(signature or ""))


def signed_headers(method: str, path: str, actor=None, body: bytes = b"") -> dict:
    ts = int(time.time())
    nonce = uuid.uuid4().hex
    return {
        HEADER_NONCE: nonce,
        HEADER_TS: str(ts),
        HEADER_ACTOR: "" if actor is None else str(actor),
        HEADER_SIG: sign(ts, method, path, actor, body, nonce=nonce),
    }
