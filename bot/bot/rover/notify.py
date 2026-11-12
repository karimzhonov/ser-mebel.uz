"""Rover events (backend -> bot).

- `rover.check`: card to the checkers (store key `{id}`); `rover.checked` turns those cards
  into the done text. Both also edit the worker's `t{id}` cards (`workers`).
- `rover.task`: task card to the worker (`t{id}`); `rover.due_ask`: «set the deadline» card
  to the production heads (`h{id}`); `rover.due_set`: edits both and tells the worker;
  `rover.remind`: new message, not stored.
Edits of `t` / `h` cards go through `accept_rev`, so a late event never overwrites a newer
card.
"""

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


def _presets(d: dict) -> tuple:
    try:
        p = tuple(int(x) for x in d.get("presets") or ())
    except (TypeError, ValueError):
        p = ()
    return p or K.PRESETS


async def _edit_all(n: Notifier, entries: list[dict], text: str, kb) -> None:
    for e in entries:
        try:
            await n.edit(e["chat_id"], e["message_id"], text, kb)
        except (KeyError, TypeError):
            continue


async def _edit_workers(n: Notifier, t: dict, workers, text: str, kb) -> None:
    """Edit the workers' task cards (`t{id}`), recording the rev so a late event is skipped."""
    chats = _tgs(workers)
    if not chats:
        return
    key = messages.tkey(t["id"])
    if not await messages.accept_rev(key, t.get("rev")):
        return  # a newer card (checked / due_set) was already applied
    await _edit_all(n, await messages.entries_for(key, chats), text, kb)


@on("rover.check")
async def check(n: Notifier, d: dict) -> None:
    t = d["rover"]
    text = T.card(t)
    kb = K.card_kb(int(t["id"]), t.get("state") or "", t.get("url") or "")
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await messages.remember(messages.ckey(t["id"]), tg, mid, "check")
    await _edit_workers(
        n,
        t,
        d.get("workers"),
        T.task_card(t),
        K.task_kb(int(t["id"]), "checking", t.get("url") or ""),
    )


@on("rover.checked")
async def checked(n: Notifier, d: dict) -> None:
    t = d["rover"]
    entries = await messages.take(messages.ckey(t["id"]), _tgs(d.get("to")))
    text = T.card(t, d.get("by_name"))
    kb = K.card_kb(int(t["id"]), "done", t.get("url") or "")
    await _edit_all(n, entries, text, kb)
    await _edit_workers(
        n, t, d.get("workers"), T.task_card(t), K.task_kb(int(t["id"]), "done", t.get("url") or "")
    )


@on("rover.task")
async def task(n: Notifier, d: dict) -> None:
    t = d["rover"]
    rid = int(t["id"])
    key = messages.tkey(rid)
    await messages.accept_rev(key, t.get("rev"))
    text = T.task_card(t)
    kb = K.task_kb(rid, t.get("state") or "new", t.get("url") or "")
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await messages.remember(key, tg, mid, "task")


@on("rover.due_ask")
async def due_ask(n: Notifier, d: dict) -> None:
    t = d["rover"]
    rid = int(t["id"])
    key = messages.hkey(rid)
    await messages.accept_rev(key, t.get("rev"))
    text = T.head_card(t)
    kb = K.due_kb(rid, _presets(d), t.get("url") or "", t.get("state") or "new")
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await messages.remember(key, tg, mid, "head")


@on("rover.due_set")
async def due_set(n: Notifier, d: dict) -> None:
    t = d["rover"]
    rid = int(t["id"])
    url = t.get("url") or ""
    state = t.get("state") or "new"
    workers, heads = _tgs(d.get("to")), _tgs(d.get("heads"))
    if workers and await messages.accept_rev(messages.tkey(rid), t.get("rev")):
        await _edit_all(
            n,
            await messages.entries_for(messages.tkey(rid), workers),
            T.task_card(t),
            K.task_kb(rid, state, url),
        )
        msg = T.due_set_msg(t, d.get("how"), d.get("by_name"))
        for tg in workers:
            await n.send(tg, msg)
    if heads and await messages.accept_rev(messages.hkey(rid), t.get("rev")):
        await _edit_all(
            n,
            await messages.entries_for(messages.hkey(rid), heads),
            T.head_card(t),
            K.due_kb(rid, K.PRESETS, url, state),
        )


@on("rover.remind")
async def remind(n: Notifier, d: dict) -> None:
    t = d["rover"]
    rid = int(t["id"])
    url = t.get("url") or ""
    what = "overdue" if d.get("what") == "overdue" else "soon"
    late = d.get("days_late") or t.get("days_late") or 0
    text = T.remind_text(t, what, late)
    for tg in _tgs(d.get("to")):
        await n.send(tg, text, K.task_kb(rid, "new", url))
    if what == "overdue":
        htext = T.remind_text(t, what, late, head=True)
        for tg in _tgs(d.get("heads")):
            await n.send(tg, htext, K.due_kb(rid, K.PRESETS, url))
