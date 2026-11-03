"""CRM events for the Telegram bot (docs/BOT_CONTRACT.md, "CRM").

Data only: ids, DTOs, recipients - the bot renders the message. A failure here is
logged and never raised.
"""

from __future__ import annotations

import functools
import logging

from core.bot_notify import emit

from . import dto

log = logging.getLogger("crm.events")


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            log.exception("event %s failed", fn.__name__)

    return wrapper


def lead_url(invoice_id) -> str:
    from django.conf import settings

    base = (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/call-center?open={invoice_id}"


def metering_url(metering_id) -> str:
    from django.conf import settings

    base = (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/meterings/{metering_id}"


@_safe
def task_due(task):
    """The task's time has come: remind its assignee in the bot."""
    emit(
        "crm.task_due",
        {
            "task": dto.task_dto(task),
            "invoice": dto.lead_brief(task.invoice),
            "to": [task.assigned_to.telegram_id],
            "url": lead_url(task.invoice_id),
        },
    )
