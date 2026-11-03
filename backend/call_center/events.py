"""CRM events for the Telegram bot (docs/BOT_CONTRACT.md, "CRM").

Data only: ids, DTOs, recipients - the bot renders the message. A failure here is
logged and never raised.
"""

from __future__ import annotations

import functools
import logging

from core.bot_notify import emit
from core.i18n import solution

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


def _to(task) -> list[int]:
    user = task.assigned_to
    return [user.telegram_id] if user is not None and user.telegram_id else []


@_safe
def task_closed(task, *, how, by=None, invoice=None, next_task=None):
    """A reminder the bot already sent was closed elsewhere (panel done, or the lead was
    closed): the bot strips the buttons from that message and adds a status line.
    how: "done" | "auto"."""
    invoice = invoice or task.invoice
    emit(
        "crm.task_closed",
        {
            "task": {"id": task.pk},
            "how": how,
            "by_name": dto.user_ref(by)["name"] if by is not None else None,
            "solution_label": solution(invoice.solution) if invoice.solution else None,
            "next_due": dto.dt(next_task.due_at) if next_task is not None else None,
            "to": _to(task),
        },
    )


@_safe
def task_moved(task, *, how, by=None, to_user=None):
    """A reminder the bot already sent was rescheduled in the panel or handed to someone
    else. how: "rescheduled" | "reassigned"."""
    emit(
        "crm.task_moved",
        {
            "task": {"id": task.pk, "due_at": dto.dt(task.due_at)},
            "how": how,
            "by_name": dto.user_ref(by)["name"] if by is not None else None,
            "to_name": dto.user_ref(to_user)["name"] if to_user is not None else None,
            "to": _to(task),
        },
    )
