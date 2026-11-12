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

from .dto import painter_part_task as _part_dto
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
    """Telegram ids of the molyars of every team of the job (deduped)."""
    users = [x.user for x in p.parts.all() if x.user is not None]
    return tgs(users)


def _part_tgs(part) -> list[int]:
    user = part.user
    return tgs([user]) if user is not None else []


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


# --- part-level events (one team's share of a job) -----------------------------------


@_safe
def painter_part_task(part, *, reason="assigned"):
    """A part is active for its molyar ("assigned") or its m² changed ("resized")."""
    to = _part_tgs(part)
    if not to:
        log.warning("painter part %s assigned but the molyar has no Telegram", part.pk)
        return
    emit("painter.part_task", {"part": _part_dto(part), "reason": reason, "to": to})


@_safe
def painter_part_unassigned(part, *, prev):
    """The part moved to another molyar or was removed: the old card is stale."""
    to = tgs([prev])
    if not to:
        return
    emit("painter.part_unassigned", {"part": _part_dto(part), "prev": user_ref(prev), "to": to})


@_safe
def painter_part_due_ask(part):
    """The part started: the production heads are asked for its deadline."""
    to = _head_tgs()
    if not to:
        log.warning("painter part %s started but no production head has Telegram", part.pk)
        return
    emit("painter.part_due_ask", {"part": _part_dto(part), "presets": PRESETS, "to": to})


@_safe
def painter_part_due_set(part, *, how, by):
    """The part's deadline was set ("set"), moved ("moved") or put automatically ("auto")."""
    to = _part_tgs(part)
    heads = _head_tgs()
    if not to and not heads:
        return
    emit(
        "painter.part_due_set",
        {
            "part": _part_dto(part),
            "how": how,
            "by_name": user_ref(by)["name"] if by is not None else None,
            "to": to,
            "heads": heads,
        },
    )


@_safe
def painter_part_remind(part, *, what, heads, today=None):
    """«1 day left» (molyar) or «overdue» (molyar + heads) for one part."""
    from accounting.text import today as _today

    late = max(((today or _today()) - part.due_date).days, 0) if what == "overdue" else 0
    to = _part_tgs(part)
    heads = heads if what == "overdue" else []
    if not to and not heads:
        return
    emit(
        "painter.part_remind",
        {"part": _part_dto(part), "what": what, "days_late": late, "to": to, "heads": heads},
    )


@_safe
def painter_part_done(part, *, by, job_done):
    """A molyar finished their part. With `job_done` the `painter.done` that follows carries
    the message; the bot only edits cards."""
    heads = _head_tgs()
    emit(
        "painter.part_done",
        {
            "part": _part_dto(part),
            "by_name": user_ref(by)["name"] if by is not None else None,
            "job_done": bool(job_done),
            "to": heads,
            "heads": heads,
            "painters": _part_tgs(part),
        },
    )


@_safe
def painter_assigned(p):
    """The split changed: the heads' stored team-choice cards become «Jamoalar: ...»."""
    to = _head_tgs()
    if not to:
        return
    emit("painter.assigned", {"painter": _dto(p), "to": to})


@_safe
def painter_remainder(p, *, remainder):
    """Every part is done but `remainder` m² were never given to a team: the heads are asked
    to hand it out (the job is not done)."""
    to = _head_tgs()
    if not to:
        log.warning(
            "painter %s has %s m2 left but no production head has Telegram", p.pk, remainder
        )
        return
    emit("painter.remainder", {"painter": _dto(p), "remainder": remainder, "to": to})
