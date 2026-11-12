"""Rover events for the Telegram bot (docs/BOT_CONTRACT.md, "Rover").

Data only: the DTO and the recipients - the bot renders the message. A failure here is
logged and never raised.
"""

from __future__ import annotations

import logging

from call_center.dto import user_ref
from call_center.events import _safe
from core.bot_notify import emit

from .dto import rover_task as _dto

log = logging.getLogger("rover.events")


def _checker_tgs() -> list[int]:
    from .services import rover_checkers

    out: list[int] = []
    for u in rover_checkers():
        if u.telegram_id and u.telegram_id not in out:
            out.append(u.telegram_id)
    return out


def tgs(users) -> list[int]:
    out: list[int] = []
    for u in users:
        if u.telegram_id and u.telegram_id not in out:
            out.append(u.telegram_id)
    return out


def _worker_tgs() -> list[int]:
    from .services import rover_workers

    return tgs(rover_workers())


def _head_tgs() -> list[int]:
    from .services import production_heads

    return tgs(production_heads())


@_safe
def rover_task(r):
    """A new rover job: the workers get the full task card."""
    to = _worker_tgs()
    if not to:
        log.warning("rover %s created but no worker has Telegram", r.pk)
        return
    emit("rover.task", {"rover": _dto(r), "to": to})


@_safe
def rover_due_ask(r):
    """A new rover job: the production heads are asked for a deadline."""
    to = _head_tgs()
    if not to:
        log.warning("rover %s created but no production head has Telegram", r.pk)
        return
    emit("rover.due_ask", {"rover": _dto(r), "presets": [3, 5, 7], "to": to})


@_safe
def rover_due_set(r, *, how, by):
    """The deadline was set ("set"), moved ("moved") or put automatically ("auto")."""
    emit(
        "rover.due_set",
        {
            "rover": _dto(r),
            "how": how,
            "by_name": user_ref(by)["name"] if by is not None else None,
            "to": _worker_tgs(),
            "heads": _head_tgs(),
        },
    )


@_safe
def rover_remind(r, *, what, workers, heads, today=None):
    """«1 day left» (workers) or «overdue» (workers + heads), every day while late."""
    from accounting.text import today as _today

    late = max(((today or _today()) - r.due_date).days, 0) if what == "overdue" else 0
    heads = heads if what == "overdue" else []
    if not workers and not heads:
        return
    emit(
        "rover.remind",
        {
            "rover": _dto(r),
            "what": what,
            "days_late": late,
            "to": workers,
            "heads": heads,
        },
    )


@_safe
def rover_check(r):
    """The worker handed the job in: the checkers get a card with «Tasdiqlash»."""
    to = _checker_tgs()
    if not to:
        log.warning("rover %s submitted but no checker has Telegram", r.pk)
        return
    emit("rover.check", {"rover": _dto(r), "to": to, "workers": _worker_tgs()})


@_safe
def rover_checked(r, *, by):
    """A checker confirmed: the other checkers' cards are now stale."""
    to = _checker_tgs()
    if not to:
        return
    emit(
        "rover.checked",
        {
            "rover": _dto(r),
            "by_name": user_ref(by)["name"],
            "to": to,
            "workers": _worker_tgs(),
        },
    )
