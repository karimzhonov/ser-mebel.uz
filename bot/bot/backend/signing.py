"""HMAC signing shared with the backend (docs/BOT_CONTRACT.md, section 0).

msg = f"{ts}\n{METHOD}\n{path_with_query}\n{actor}\n" + raw_body, key = BOT_TOKEN.
"""

import hashlib
import hmac
import time
import uuid

MAX_SKEW = 300  # seconds

HEADER_TS = "X-Bot-Timestamp"
HEADER_ACTOR = "X-Bot-Actor"
HEADER_SIG = "X-Bot-Signature"
HEADER_NONCE = "X-Bot-Nonce"


def sign(
    ts, method: str, path: str, actor, body: bytes = b"", token: str | None = None, nonce: str = ""
) -> str:
    if token is None:
        from config import BOT_TOKEN

        token = BOT_TOKEN or ""
    actor = "" if actor is None else str(actor)
    msg = f"{int(ts)}\n{method.upper()}\n{path}\n{actor}\n{nonce}\n".encode() + (body or b"")
    return hmac.new(token.encode(), msg, hashlib.sha256).hexdigest()


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
    """True when the timestamp is fresh (+-300 s) and the signature matches."""
    if not nonce:
        return False
    try:
        ts_int = int(ts)
    except (TypeError, ValueError):
        return False
    if abs((time.time() if now is None else now) - ts_int) > MAX_SKEW:
        return False
    if token is None:
        from config import BOT_TOKEN

        if not BOT_TOKEN:
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
