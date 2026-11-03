"""Zamer events for the Telegram bot (docs/BOT_CONTRACT.md, "Zamer").

Data only: ids, DTOs, recipients - the bot renders the message. A failure here is
logged and never raised.
"""

from __future__ import annotations

from call_center.dto import user_ref
from call_center.events import _safe, metering_url  # noqa: F401 (metering_url re-exported)
from core.bot_notify import emit

from . import dto


def agenda_url(tab: str) -> str:
    from django.conf import settings

    base = (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/meterings?tab={tab}"


def _tg(*users) -> list[int]:
    out = []
    for u in users:
        if u is not None and u.is_active and u.telegram_id and u.telegram_id not in out:
            out.append(u.telegram_id)
    return out


@_safe
def metering_assigned(m, *, how):
    """The measurer got a zamer. how: "new" | "reassigned"."""
    to = _tg(m.measurer)
    if not to:
        return
    emit("metering.assigned", {"metering": dto.metering_brief(m), "how": how, "to": to})


@_safe
def metering_reminder(m, *, kind):
    """kind: "soon" (about an hour before) | "late" (time passed, no answer)."""
    to = _tg(m.measurer)
    if not to:
        return
    emit("metering.reminder", {"metering": dto.metering_brief(m), "kind": kind, "to": to})


@_safe
def metering_digest(user, items, *, day):
    to = _tg(user)
    if not to:
        return
    emit(
        "metering.digest",
        {
            "date": day.isoformat(),
            "items": [dto.metering_brief(m) for m in items],
            "to": to,
            "url": agenda_url("tomorrow"),
        },
    )


@_safe
def metering_changed(m, *, how, by=None, to_users=(), to_name=None, watchers=()):
    """A zamer the bot may have shown changed. `to` = the measurer(s) whose earlier
    messages are now stale (the OLD measurer for "reassigned"); `watchers` get a short
    notice (the operator, when someone else moved the time).
    how: "measured" | "rescheduled" | "done" | "cancelled" | "reassigned"."""
    to, watch = _tg(*to_users), _tg(*watchers)
    if not to and not watch:
        return
    emit(
        "metering.changed",
        {
            "metering": dto.metering_brief(m),
            "how": how,
            "by_name": user_ref(by)["name"] if by is not None else None,
            "to_name": to_name,
            "to": to,
            "watchers": watch,
        },
    )
