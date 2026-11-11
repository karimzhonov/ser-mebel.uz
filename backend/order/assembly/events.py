"""Assembly (Yig'ish/O'rnatish) events for the Telegram bot (docs/BOT_CONTRACT.md, "Assembly").

Data only: the DTO and the recipients - the bot renders the message. A failure here is
logged and never raised.
"""

from __future__ import annotations

import logging

from call_center.dto import user_ref
from call_center.events import _safe
from core.bot_notify import emit
from order.rover.events import tgs

from .dto import assembly_task as _dto

log = logging.getLogger("assembly.events")

PRESETS = [5, 10, 14]


def _head_tgs() -> list[int]:
    from .services import production_heads

    return tgs(production_heads())


def _manager_tgs() -> list[int]:
    from .services import assembly_managers

    return tgs(assembly_managers())


def _assembler_tgs(a) -> list[int]:
    return tgs([a.user]) if a.user_id else []


@_safe
def assembly_ready(a):
    """The order is in «Сборка»: the production heads are asked which assembler gets it."""
    from .services import active_assemblers

    to = _head_tgs()
    if not to:
        log.warning("assembly %s ready but no production head has Telegram", a.pk)
        return
    assemblers = [user_ref(u) for u in active_assemblers().order_by("name", "pk")]
    emit("assembly.ready", {"assembly": _dto(a), "assemblers": assemblers, "to": to})


@_safe
def assembly_task(a):
    """The job is active for its assembler: the full task card."""
    to = _assembler_tgs(a)
    if not to:
        log.warning("assembly %s assigned but the assembler has no Telegram", a.pk)
        return
    emit("assembly.task", {"assembly": _dto(a), "to": to})


@_safe
def assembly_unassigned(a, *, prev):
    """The job moved to another assembler (or lost it): the old card is stale."""
    to = tgs([prev])
    if not to:
        return
    emit("assembly.unassigned", {"assembly": _dto(a), "prev": user_ref(prev), "to": to})


@_safe
def assembly_due_ask(a):
    """The job started: the production heads are asked for a deadline."""
    to = _head_tgs()
    if not to:
        log.warning("assembly %s started but no production head has Telegram", a.pk)
        return
    emit("assembly.due_ask", {"assembly": _dto(a), "presets": PRESETS, "to": to})


@_safe
def assembly_due_set(a, *, how, by):
    """The deadline was set ("set"), moved ("moved") or put automatically ("auto")."""
    to = _assembler_tgs(a)
    heads = _head_tgs()
    if not to and not heads:
        return
    emit(
        "assembly.due_set",
        {
            "assembly": _dto(a),
            "how": how,
            "by_name": user_ref(by)["name"] if by is not None else None,
            "to": to,
            "heads": heads,
        },
    )


@_safe
def assembly_remind(a, *, what, heads, today=None):
    """«1 day left» (assembler) or «overdue» (assembler + heads), every day while late."""
    from accounting.text import today as _today

    late = max(((today or _today()) - a.due_date).days, 0) if what == "overdue" else 0
    to = _assembler_tgs(a)
    heads = heads if what == "overdue" else []
    if not to and not heads:
        return
    emit(
        "assembly.remind",
        {"assembly": _dto(a), "what": what, "days_late": late, "to": to, "heads": heads},
    )


@_safe
def assembly_done(a, *, by):
    """The installation is finished (panel or bot): heads and managers hear of it."""
    heads = _head_tgs()
    to = list(heads)
    for t in _manager_tgs():
        if t not in to:
            to.append(t)
    assemblers = _assembler_tgs(a)
    if not to and not assemblers:
        return
    emit(
        "assembly.done",
        {
            "assembly": _dto(a),
            "by_name": user_ref(by)["name"] if by is not None else None,
            "to": to,
            "heads": heads,
            "assemblers": assemblers,
        },
    )
