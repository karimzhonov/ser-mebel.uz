"""Detailing events for the Telegram bot (docs/BOT_CONTRACT.md, "Detailing").

Data only: the DTO and the recipients - the bot renders the message. A failure here is
logged and never raised.
"""

from __future__ import annotations

import logging

from call_center.events import _safe
from core.bot_notify import emit

from .dto import detailing_task as _dto

log = logging.getLogger("detailing.events")


def detailer_tgs() -> list[int]:
    from oauth.constants import DETAILING_PERMISSION
    from oauth.services import staff_with_permission

    out: list[int] = []
    for u in staff_with_permission(DETAILING_PERMISSION):
        if u.telegram_id and u.telegram_id not in out:
            out.append(u.telegram_id)
    return out


@_safe
def detailing_task(d, *, how="new"):
    """The order was sent to detailing ("new") or its deadline moved ("moved"): the
    detailers get the task card (deadline, client, «Bajardim» on the site)."""
    to = detailer_tgs()
    if not to:
        log.warning("detailing %s: no detailer has Telegram", d.pk)
        return
    emit("detailing.task", {"detailing": _dto(d), "how": how, "to": to})
