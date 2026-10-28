"""Authentication of the internal bot channel (`/api/v1/bot/...`).

The bot service signs every request with HMAC-SHA256 keyed with BOT_TOKEN (see
core/bot_signing.py and docs/BOT_CONTRACT.md). A valid signature authenticates the
*bot*; the Telegram user it acts for travels in `X-Bot-Actor` and is covered by the
signature, so it can't be swapped. A JWT alone never reaches these endpoints.
"""

import logging
import re

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import PermissionDenied

from core.bot_signing import HEADER_ACTOR, HEADER_NONCE, HEADER_SIG, HEADER_TS, MAX_SKEW, verify

log = logging.getLogger("api.bot_auth")

_redis_client = None


def _redis():
    global _redis_client
    if _redis_client is None:
        import redis

        _redis_client = redis.from_url(settings.REDIS_URL, socket_timeout=2)
    return _redis_client


def claim_nonce(nonce: str) -> bool:
    """True the first time a nonce is seen (Redis SET NX, TTL 2 x the clock window).
    A captured request therefore can't be replayed inside its validity window. Fails closed:
    if Redis is unreachable the request is refused (and logged)."""
    try:
        return bool(_redis().set(f"botnonce:{nonce}", 1, nx=True, ex=2 * MAX_SKEW))
    except Exception:  # noqa: BLE001
        log.exception("replay cache unavailable; refusing the bot request")
        return False


class BotPrincipal:
    """The authenticated bot (not a Django user)."""

    is_authenticated = True
    is_active = True
    is_staff = False
    is_superuser = False
    pk = None

    def __str__(self):
        return "bot"

    def has_perm(self, *args, **kwargs):
        return False


class BotSignatureAuthentication(BaseAuthentication):
    """Returns (BotPrincipal, actor_telegram_id | None); request.auth is the actor."""

    def authenticate(self, request):
        headers = request.headers
        sig = headers.get(HEADER_SIG)
        if not sig:
            return None  # IsBot refuses: 403
        actor = headers.get(HEADER_ACTOR, "")
        nonce = headers.get(HEADER_NONCE, "")
        django_request = request._request
        ok = verify(
            sig,
            headers.get(HEADER_TS),
            django_request.method,
            django_request.get_full_path(),
            actor,
            django_request.body,
            nonce=nonce,
        )
        if not ok:
            raise PermissionDenied("bad signature")
        # reads are idempotent; only state-changing methods are replay-protected by nonce
        if django_request.method not in ("GET", "HEAD", "OPTIONS") and not (
            re.fullmatch(r"[0-9a-f]{32}", nonce) and claim_nonce(nonce)
        ):
            raise PermissionDenied("replayed request")
        try:
            actor_tg = int(actor) if actor else None
        except ValueError:
            raise PermissionDenied("bad actor")
        return BotPrincipal(), actor_tg
