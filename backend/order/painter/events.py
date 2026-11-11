"""Painter (molyar) events for the Telegram bot (docs/BOT_CONTRACT.md, "Painter").

Data only: the DTO and the recipients - the bot renders the message. A failure here is
logged and never raised.
"""

from __future__ import annotations

import logging

from call_center.dto import user_ref
from call_center.events import _safe
from core.bot_notify import emit
from order.rover.events import tgs

from .dto import painter_task as _dto

log = logging.getLogger("painter.events")

PRESETS = [5, 10, 14]


def _head_tgs() -> list[int]:
    from .services import production_heads

    return tgs(production_heads())


def _manager_tgs() -> list[int]:
    from .services import assembly_managers

    return tgs(assembly_managers())


def _painter_tgs(p) -> list[int]:
    user = p.type.user if p.type_id and p.type.user_id else None
    return tgs([user]) if user is not None else []


@_safe
def painter_task(p):
    """The job is active for its painter: the full task card."""
    to = _painter_tgs(p)
    if not to:
        log.warning("painter %s assigned but the painter has no Telegram", p.pk)
        return
    emit("painter.task", {"painter": _dto(p), "to": to})


@_safe
def painter_unassigned(p, *, prev):
    """The job moved to another painter (or lost its type): the old card is stale."""
    to = tgs([prev])
    if not to:
        return
    emit("painter.unassigned", {"painter": _dto(p), "prev": user_ref(prev), "to": to})


def _team_choices() -> list[dict]:
    """The teams (painter types) that have a responsible user, by name."""
    from .models import PainterType

    return [
        {"id": t.pk, "name": t.name, "user": user_ref(t.user)}
        for t in PainterType.objects.filter(user__isnull=False)
        .select_related("user")
        .order_by("name", "pk")
    ]


@_safe
def painter_ready(p):
    """The rover is confirmed: the production heads are asked which team gets the job."""
    to = _head_tgs()
    if not to:
        log.warning("painter %s ready but no production head has Telegram", p.pk)
        return
    emit("painter.ready", {"painter": _dto(p), "types": _team_choices(), "to": to})


@_safe
def painter_due_ask(p):
    """The job started: the production heads are asked for a deadline."""
    to = _head_tgs()
    if not to:
        log.warning("painter %s started but no production head has Telegram", p.pk)
        return
    emit("painter.due_ask", {"painter": _dto(p), "presets": PRESETS, "to": to})


@_safe
def painter_due_set(p, *, how, by):
    """The deadline was set ("set"), moved ("moved") or put automatically ("auto")."""
    to = _painter_tgs(p)
    heads = _head_tgs()
    if not to and not heads:
        return
    emit(
        "painter.due_set",
        {
            "painter": _dto(p),
            "how": how,
            "by_name": user_ref(by)["name"] if by is not None else None,
            "to": to,
            "heads": heads,
        },
    )


@_safe
def painter_remind(p, *, what, heads, today=None):
    """«1 day left» (painter) or «overdue» (painter + heads), every day while late."""
    from accounting.text import today as _today

    late = max(((today or _today()) - p.due_date).days, 0) if what == "overdue" else 0
    to = _painter_tgs(p)
    heads = heads if what == "overdue" else []
    if not to and not heads:
        return
    emit(
        "painter.remind",
        {"painter": _dto(p), "what": what, "days_late": late, "to": to, "heads": heads},
    )


@_safe
def painter_done(p, *, by):
    """The painter's work is done (panel or bot): heads and managers hear of it."""
    heads = _head_tgs()
    to = list(heads)
    for t in _manager_tgs():
        if t not in to:
            to.append(t)
    painters = _painter_tgs(p)
    if not to and not painters:
        return
    emit(
        "painter.done",
        {
            "painter": _dto(p),
            "by_name": user_ref(by)["name"] if by is not None else None,
            "to": to,
            "heads": heads,
            "painters": painters,
        },
    )
