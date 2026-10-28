import hashlib
import hmac
import logging
import re

from django.conf import settings

log = logging.getLogger("core.telegram")

_LINK_RE = re.compile(r"^u(\d+)_([0-9a-f]{10})$")


def bot_link(start: str | int = "") -> str:
    """t.me deep link to the site bot (settings.TELEGRAM_BOT_USERNAME)."""
    url = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}"
    return f"{url}?start={start}" if start != "" else url


def _link_mac(pk: int) -> str:
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, f"tg-link:{int(pk)}".encode(), hashlib.sha256).hexdigest()[:10]


def link_token(pk: int) -> str:
    """Signed `/start` payload that links a Telegram account to site user `pk`:
    `u{pk}_{hmac10}` (HMAC-SHA256 of the pk keyed with SECRET_KEY, first 10 hex chars).
    Only the backend signs and verifies; the bot just forwards the payload."""
    return f"u{int(pk)}_{_link_mac(pk)}"


def parse_link_token(token) -> int | None:
    """User pk when `token` is a genuine signed link token, else None. The old unsigned
    `/start <pk>` payload is refused: it let anyone bind any site account."""
    m = _LINK_RE.match(str(token or "").strip())
    if not m:
        return None
    pk = int(m.group(1))
    return pk if hmac.compare_digest(_link_mac(pk), m.group(2)) else None


def user_bot_link(pk: int) -> str:
    """Deep link that connects the Telegram account of site user `pk`."""
    return bot_link(link_token(pk))
