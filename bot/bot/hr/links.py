"""Deep links used by the davomat bot."""

from __future__ import annotations

import logging

import config

from . import api

log = logging.getLogger("bot.hr")


async def connect_url() -> str:
    """https://t.me/<bot>?start=davomat : the «🤖 Botga ulanish» button of the work groups."""
    name = (getattr(config, "TELEGRAM_BOT_USERNAME", "") or "").lstrip("@")
    if not name:
        try:
            name = (await api.get_bot().me()).username or ""
        except Exception:  # noqa: BLE001
            log.warning("bot username unknown", exc_info=True)
    return f"https://t.me/{name}?start=davomat"


def site_url() -> str:
    """The HR page of the site (old hr/telegram.py:site_url)."""
    base = (getattr(config, "BASE_SITE", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/hr"
