"""Rover events for the Telegram bot (docs/BOT_CONTRACT.md, "Rover").

Data only: the DTO and the recipients - the bot renders the message. A failure here is
logged and never raised.
"""

from __future__ import annotations

import logging

from call_center.dto import user_ref
from call_center.events import _safe
from core.bot_notify import emit

from .dto import rover_task

log = logging.getLogger("rover.events")


def _checker_tgs() -> list[int]:
    from .services import rover_checkers

    out: list[int] = []
    for u in rover_checkers():
        if u.telegram_id and u.telegram_id not in out:
            out.append(u.telegram_id)
    return out


@_safe
def rover_check(r):
    """The worker handed the job in: the checkers get a card with «Tasdiqlash»."""
    to = _checker_tgs()
    if not to:
        log.warning("rover %s submitted but no checker has Telegram", r.pk)
        return
    emit("rover.check", {"rover": rover_task(r), "to": to})


@_safe
def rover_checked(r, *, by):
    """A checker confirmed: the other checkers' cards are now stale."""
    to = _checker_tgs()
    if not to:
        return
    emit("rover.checked", {"rover": rover_task(r), "by_name": user_ref(by)["name"], "to": to})
