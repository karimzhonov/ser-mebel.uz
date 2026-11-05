"""Zamer events (backend -> bot): `metering.assigned` / `metering.reminder` send the card
to the measurer, `metering.digest` the evening list of tomorrow, `metering.changed` keeps
the cards sent earlier (and the operator) up to date. Wording lives here; the backend sends
data only (docs/BOT_CONTRACT.md). The edit rule: only the chats in `to` are edited, and only
when the event's `rev` is newer than the last applied one."""

from __future__ import annotations

import logging

from bot.notify.registry import Notifier, on

from . import keyboards as K
from . import messages
from . import texts as T

log = logging.getLogger("bot.metering.notify")

FINAL_HOW = ("done", "cancelled", "reassigned")


def _tgs(value) -> list[int]:
    if isinstance(value, (int, str)) and str(value).lstrip("-").isdigit():
        return [int(value)]
    return [int(x) for x in (value or [])]


def kb_for(m: dict):
    return K.card_kb(
        int(m["id"]), m.get("status") or "", m.get("url") or "", m.get("map_url") or ""
    )


async def _send_card(n: Notifier, d: dict, kind: str, header: str) -> None:
    m = d["metering"]
    text = T.card(m, header)
    kb = kb_for(m)
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await messages.remember(int(m["id"]), tg, mid, kind)


@on("metering.assigned")
async def assigned(n: Notifier, d: dict) -> None:
    header = "reassigned" if d.get("how") == "reassigned" else "assigned"
    await _send_card(n, d, "assigned", header)


@on("metering.reminder")
async def reminder(n: Notifier, d: dict) -> None:
    kind = "late" if d.get("kind") == "late" else "soon"
    await _send_card(n, d, kind, kind)


@on("metering.digest")
async def digest(n: Notifier, d: dict) -> None:
    items = d.get("items") or []
    if not items:
        return
    pages = T.digest_pages(items)
    for tg in _tgs(d.get("to")):
        for i, page in enumerate(pages):
            last = i == len(pages) - 1
            await n.send(tg, page, K.agenda_kb(d.get("url") or "") if last else None)


@on("metering.changed")
async def changed(n: Notifier, d: dict) -> None:
    m = d["metering"]
    mid = int(m["id"])
    how = d.get("how")
    if not await messages.accept_rev(mid, m.get("rev")):
        log.info("metering %s: event rev %s is not newer, skipped", mid, m.get("rev"))
        return
    to = _tgs(d.get("to"))
    # the entries of the chats in `to` only: for a reassignment `to` is the OLD measurer
    entries = (
        await messages.take(mid, to) if how in FINAL_HOW else await messages.entries_for(mid, to)
    )
    final = how in FINAL_HOW
    for e in entries:
        try:
            text = T.card(m, e.get("kind") or "assigned", how=how, to_name=d.get("to_name"))
            kb = None if final or how == "reassigned" else kb_for(m)
            await n.edit(e["chat_id"], e["message_id"], text, kb)
        except (KeyError, TypeError):
            continue
    if how == "rescheduled":
        text = T.moved_watch(m, d.get("by_name") or "")
        for tg in _tgs(d.get("watchers")):
            await n.send(tg, text, K.site_kb(m.get("url") or ""))
