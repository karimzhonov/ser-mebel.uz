"""Painter events (backend -> bot).

- `painter.task`: full task card to the assigned painter (store key `t{id}u{user_id}`).
- `painter.unassigned`: the old painter's card is edited into «boshqa molyarga o'tkazildi».
- `painter.ready`: plain message to the assembly managers (the rover is confirmed).
- `painter.due_ask`: «set the deadline» card to the production heads (`h{id}`).
- `painter.due_set`: edits the painter / head cards, short message to the painter.
- `painter.remind`: soon / overdue messages, not stored.
- `painter.done`: «Molyar tayyor» message; edits the stored head / painter cards.
Edits of stored cards go through `accept_rev` with `painter.rev`, so a late event never
overwrites a newer card, and only the chats listed in the event are touched.
"""

from __future__ import annotations

import logging

from bot.notify.registry import Notifier, on

from . import keyboards as K
from . import messages
from . import texts as T

log = logging.getLogger("bot.painter.notify")


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


def _uid(u) -> int | None:
    try:
        return int((u or {}).get("id"))
    except (TypeError, ValueError, AttributeError):
        return None


async def _edit_all(n: Notifier, entries: list[dict], text: str, kb) -> None:
    for e in entries:
        try:
            await n.edit(e["chat_id"], e["message_id"], text, kb)
        except (KeyError, TypeError):
            continue


async def _edit_task_cards(n: Notifier, t: dict, chats: list[int], text: str, kb) -> None:
    """Edit the painter's `t{id}u{uid}` cards, rev-guarded (the assignee of the event)."""
    uid = _uid(t.get("painter"))
    if not chats or uid is None:
        return
    key = messages.tkey(t["id"], uid)
    if not await messages.accept_rev(key, t.get("rev")):
        return
    await _edit_all(n, await messages.entries_for(key, chats), text, kb)


@on("painter.task")
async def task(n: Notifier, d: dict) -> None:
    t = d["painter"]
    pid = int(t["id"])
    uid = _uid(t.get("painter"))
    key = messages.tkey(pid, uid) if uid is not None else None
    if key:
        await messages.accept_rev(key, t.get("rev"))
    text = T.task_card(t)
    kb = K.task_kb(pid, t.get("state") or "new", t.get("url") or "")
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None and key:
            await messages.remember(key, tg, mid, "task")


@on("painter.unassigned")
async def unassigned(n: Notifier, d: dict) -> None:
    t = d["painter"]
    prev = _uid(d.get("prev"))
    chats = _tgs(d.get("to"))
    if prev is None or not chats:
        return
    key = messages.tkey(t["id"], prev)
    if not await messages.accept_rev(key, t.get("rev")):
        return  # the job came back to this painter meanwhile
    entries = await messages.take(key, chats)
    await _edit_all(n, entries, T.reassigned_card(t), K.link_kb(t.get("url") or ""))


@on("painter.ready")
async def ready(n: Notifier, d: dict) -> None:
    t = d["painter"]
    text = T.ready_msg(t)
    kb = K.link_kb(t.get("url") or "")
    for tg in _tgs(d.get("to")):
        await n.send(tg, text, kb)


@on("painter.due_ask")
async def due_ask(n: Notifier, d: dict) -> None:
    t = d["painter"]
    pid = int(t["id"])
    key = messages.hkey(pid)
    await messages.accept_rev(key, t.get("rev"))
    text = T.head_card(t)
    kb = K.due_kb(pid, _presets(d), t.get("url") or "", t.get("state") or "new")
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await messages.remember(key, tg, mid, "head")


@on("painter.due_set")
async def due_set(n: Notifier, d: dict) -> None:
    t = d["painter"]
    pid = int(t["id"])
    url = t.get("url") or ""
    state = t.get("state") or "new"
    painters, heads = _tgs(d.get("to")), _tgs(d.get("heads"))
    uid = _uid(t.get("painter"))
    if painters and uid is not None:
        key = messages.tkey(pid, uid)
        if await messages.accept_rev(key, t.get("rev")):
            await _edit_all(
                n,
                await messages.entries_for(key, painters),
                T.task_card(t),
                K.task_kb(pid, state, url),
            )
            msg = T.due_set_msg(t, d.get("how"), d.get("by_name"))
            for tg in painters:
                await n.send(tg, msg)
    if heads and await messages.accept_rev(messages.hkey(pid), t.get("rev")):
        await _edit_all(
            n,
            await messages.entries_for(messages.hkey(pid), heads),
            T.head_card(t),
            K.due_kb(pid, K.PRESETS, url, state),
        )


@on("painter.remind")
async def remind(n: Notifier, d: dict) -> None:
    t = d["painter"]
    pid = int(t["id"])
    url = t.get("url") or ""
    what = "overdue" if d.get("what") == "overdue" else "soon"
    late = d.get("days_late") or t.get("days_late") or 0
    text = T.remind_text(t, what, late)
    for tg in _tgs(d.get("to")):
        await n.send(tg, text, K.task_kb(pid, "new", url))
    if what == "overdue":
        htext = T.remind_text(t, what, late, head=True)
        for tg in _tgs(d.get("heads")):
            await n.send(tg, htext, K.due_kb(pid, K.PRESETS, url))


@on("painter.done")
async def done(n: Notifier, d: dict) -> None:
    t = d["painter"]
    pid = int(t["id"])
    url = t.get("url") or ""
    text = T.done_msg(t, d.get("by_name"))
    kb = K.link_kb(url)
    for tg in _tgs(d.get("to")):
        await n.send(tg, text, kb)
    heads, painters = _tgs(d.get("heads")), _tgs(d.get("painters"))
    if heads and await messages.accept_rev(messages.hkey(pid), t.get("rev")):
        await _edit_all(
            n,
            await messages.entries_for(messages.hkey(pid), heads),
            T.head_card(t),
            K.due_kb(pid, K.PRESETS, url, "done"),
        )
    await _edit_task_cards(n, t, painters, T.task_card(t), K.task_kb(pid, "done", url))
