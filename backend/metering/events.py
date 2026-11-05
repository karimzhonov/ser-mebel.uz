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


# --- Stage 2: dizayn va narx (docs/BOT_CONTRACT.md, "Dizayn va narx") -------------------


def _bosses() -> list:
    """«Bosh menejer» (metering.manage_metering): copied on the few cards that matter -
    «tayyor» (once, no daily reminders) and «buyurtma yarating» (owner: not too many)."""
    from .services import bosses

    return list(bosses())


def _base() -> str:
    from django.conf import settings

    return (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")


def design_url(design_id) -> str:
    return f"{_base()}/designs/{design_id}"


def price_url(price_id) -> str:
    return f"{_base()}/prices/{price_id}"


def offer_url(kind, obj_id) -> str:
    return design_url(obj_id) if kind == "design" else price_url(obj_id)


def present_url(kind, obj_id) -> str:
    """The manager's page: «Mijozga ko'rsatish», the row opened."""
    return f"{_base()}/presentations?open={kind[0]}{obj_id}"


def order_url(price) -> str:
    design = getattr(price.metering, "design", None)
    url = f"{_base()}/orders/new?metering={price.metering_id}"
    return f"{url}&design={design.pk}" if design is not None else url


@_safe
def offer_assigned(obj, kind, *, how, comment=None):
    """The designer / pricer got (or got back) a task.
    how: "new" | "reassigned" | "changes"."""
    to = _tg(obj.user)
    if not to:
        return
    emit(
        "offer.assigned",
        {"task": dto.offer_task(obj, kind), "how": how, "comment": comment or None, "to": to},
    )


@_safe
def offer_reminder(obj, kind, *, what):
    """what: "soon" | "late" | "overdue"."""
    to = _tg(obj.user)
    if not to:
        return
    emit("offer.reminder", {"task": dto.offer_task(obj, kind), "kind": what, "to": to})


@_safe
def offer_present(obj, kind, *, how, to_users):
    """The manager must show the design / price to the client. how: "ready" | "reminder".
    The Bosh menejer gets a copy of "ready" only (they may record the answer too)."""
    to = _tg(*to_users, *(_bosses() if how == "ready" else ()))
    if not to:
        return
    emit("offer.present", {"task": dto.offer_task(obj, kind), "how": how, "to": to})


@_safe
def offer_changed(obj, kind, *, how, by=None, to_users=(), to_name=None, answer=None, watchers=()):
    """A task the bot may have shown changed. `to` = the chats whose cards are now stale
    (the OLD assignee for "reassigned", the manager for "answered"), plus the Bosh
    menejer for "answered" (their copy of the «tayyor» card). The bot edits only the cards
    it stored for a chat, so a chat without one is a no-op.
    how: "done" | "due_moved" | "reassigned" | "answered" | "cancelled"."""
    to = _tg(*to_users, *(_bosses() if how == "answered" else ()))
    watch = _tg(*watchers)
    if not to and not watch:
        return
    emit(
        "offer.changed",
        {
            "task": dto.offer_task(obj, kind),
            "how": how,
            "answer": answer,
            "by_name": user_ref(by)["name"] if by is not None else None,
            "to_name": to_name,
            "to": to,
            "watchers": watch,
        },
    )


@_safe
def offer_order_ready(price, *, to_users):
    """The client agreed to the price: someone must make the order. The Bosh menejer
    is always told."""
    to = _tg(*to_users, *_bosses())
    if not to:
        return
    emit(
        "offer.order_ready",
        {"task": dto.offer_task(price, "price"), "to": to, "url": order_url(price)},
    )
