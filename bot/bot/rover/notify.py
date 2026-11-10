"""Rover events (backend -> bot): `rover.check` sends the card to the checkers,
`rover.checked` turns the cards sent earlier (only the chats in `to`) into the done text."""

from __future__ import annotations

import logging

from bot.notify.registry import Notifier, on

from . import keyboards as K
from . import messages
from . import texts as T

log = logging.getLogger("bot.rover.notify")


def _tgs(value) -> list[int]:
    if isinstance(value, (int, str)) and str(value).lstrip("-").isdigit():
        return [int(value)]
    return [int(x) for x in (value or [])]


@on("rover.check")
async def check(n: Notifier, d: dict) -> None:
    t = d["rover"]
    text = T.card(t)
    kb = K.card_kb(int(t["id"]), t.get("state") or "", t.get("url") or "")
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await messages.remember(int(t["id"]), tg, mid, "check")


@on("rover.checked")
async def checked(n: Notifier, d: dict) -> None:
    t = d["rover"]
    entries = await messages.take(int(t["id"]), _tgs(d.get("to")))
    text = T.card(t, d.get("by_name"))
    kb = K.card_kb(int(t["id"]), "done", t.get("url") or "")
    for e in entries:
        try:
            await n.edit(e["chat_id"], e["message_id"], text, kb)
        except (KeyError, TypeError):
            continue
