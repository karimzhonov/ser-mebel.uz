"""Assembly events (backend -> bot).

- `assembly.ready`: «pick the team» card to the production heads (`r{id}`, one button per
  assembler).
- `assembly.task`: full task card to the chosen assembler (store key `t{id}u{user_id}`); also
  closes the heads' `r{id}` cards (fires on every team pick).
- `assembly.unassigned`: the old assembler's card is edited into «boshqa yig'uvchiga o'tkazildi».
- `assembly.due_ask`: «set the deadline» card to the heads (`h{id}`); also turns the stored
  `r{id}` cards into «✅ Jamoa: …».
- `assembly.due_set`: edits the assembler / head cards, short message to the assembler.
- `assembly.remind`: soon / overdue messages, not stored.
- `assembly.done`: «O'rnatildi» message; edits the stored head / assembler cards.
Edits of stored cards go through `accept_rev` with `assembly.rev`, so a late event never
overwrites a newer card, and only the chats listed in the event are touched.
"""

from __future__ import annotations

import logging

from bot.notify.registry import Notifier, on

from . import keyboards as K
from . import messages
from . import texts as T

log = logging.getLogger("bot.assembly.notify")


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
    """Edit the assembler's `t{id}u{uid}` cards, rev-guarded (the assignee of the event)."""
    uid = _uid(t.get("assembler"))
    if not chats or uid is None:
        return
    key = messages.tkey(t["id"], uid)
    if not await messages.accept_rev(key, t.get("rev")):
        return
    await _edit_all(n, await messages.entries_for(key, chats), text, kb)


async def _close_team_cards(n: Notifier, t: dict) -> None:
    """Edit every stored `r{id}` «pick the team» card into «✅ Jamoa: …» (site link only)."""
    if not t.get("assembler"):
        return
    # record the rev so a `assembly.ready` delivered late doesn't send a fresh pick card
    await messages.accept_rev(messages.rkey(int(t["id"])), t.get("rev"))
    entries = await messages.take_all(messages.rkey(int(t["id"])))
    await _edit_all(n, entries, T.team_chosen(t), K.link_kb(t.get("url") or ""))


@on("assembly.task")
async def task(n: Notifier, d: dict) -> None:
    t = d["assembly"]
    pid = int(t["id"])
    uid = _uid(t.get("assembler"))
    key = messages.tkey(pid, uid) if uid is not None else None
    if key:
        await messages.accept_rev(key, t.get("rev"))
    # a team is picked (first time or reassigned, site or bot): the heads' «pick the team»
    # cards are done whatever the deadline state
    await _close_team_cards(n, t)
    text = T.task_card(t)
    kb = K.task_kb(pid, t.get("state") or "new", t.get("url") or "")
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None and key:
            await messages.remember(key, tg, mid, "task")


@on("assembly.unassigned")
async def unassigned(n: Notifier, d: dict) -> None:
    t = d["assembly"]
    prev = _uid(d.get("prev"))
    chats = _tgs(d.get("to"))
    if prev is None or not chats:
        return
    key = messages.tkey(t["id"], prev)
    if not await messages.accept_rev(key, t.get("rev")):
        return  # the job came back to this assembler meanwhile
    entries = await messages.take(key, chats)
    await _edit_all(n, entries, T.reassigned_card(t), K.link_kb(t.get("url") or ""))


@on("assembly.ready")
async def ready(n: Notifier, d: dict) -> None:
    t = d["assembly"]
    pid = int(t["id"])
    key = messages.rkey(pid)
    if not await messages.accept_rev(key, t.get("rev")):
        return
    assemblers = d.get("assemblers") or []
    text = T.ready_msg(t, bool(assemblers))
    kb = K.team_kb(pid, assemblers, t.get("url") or "")
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await messages.remember(key, tg, mid, "team")


@on("assembly.due_ask")
async def due_ask(n: Notifier, d: dict) -> None:
    t = d["assembly"]
    pid = int(t["id"])
    await _close_team_cards(n, t)
    key = messages.hkey(pid)
    await messages.accept_rev(key, t.get("rev"))
    text = T.head_card(t)
    kb = K.due_kb(pid, _presets(d), t.get("url") or "", t.get("state") or "new")
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await messages.remember(key, tg, mid, "head")


@on("assembly.due_set")
async def due_set(n: Notifier, d: dict) -> None:
    t = d["assembly"]
    pid = int(t["id"])
    url = t.get("url") or ""
    state = t.get("state") or "new"
    assemblers, heads = _tgs(d.get("to")), _tgs(d.get("heads"))
    uid = _uid(t.get("assembler"))
    if assemblers and uid is not None:
        key = messages.tkey(pid, uid)
        if await messages.accept_rev(key, t.get("rev")):
            await _edit_all(
                n,
                await messages.entries_for(key, assemblers),
                T.task_card(t),
                K.task_kb(pid, state, url),
            )
            msg = T.due_set_msg(t, d.get("how"), d.get("by_name"))
            for tg in assemblers:
                await n.send(tg, msg)
    if heads and await messages.accept_rev(messages.hkey(pid), t.get("rev")):
        await _edit_all(
            n,
            await messages.entries_for(messages.hkey(pid), heads),
            T.head_card(t),
            K.due_kb(pid, K.PRESETS, url, state),
        )


@on("assembly.remind")
async def remind(n: Notifier, d: dict) -> None:
    t = d["assembly"]
    pid = int(t["id"])
    url = t.get("url") or ""
    what = "overdue" if d.get("what") == "overdue" else "soon"
    late = d.get("days_late") or t.get("days_late") or 0
    text = T.remind_text(t, what, late)
    for tg in _tgs(d.get("to")):
        await n.send(tg, text, K.task_kb(pid, t.get("state") or "new", url))
    if what == "overdue":
        htext = T.remind_text(t, what, late, head=True)
        for tg in _tgs(d.get("heads")):
            await n.send(tg, htext, K.due_kb(pid, K.PRESETS, url))


@on("assembly.done")
async def done(n: Notifier, d: dict) -> None:
    t = d["assembly"]
    pid = int(t["id"])
    url = t.get("url") or ""
    text = T.done_msg(t, d.get("by_name"))
    kb = K.link_kb(url)
    for tg in _tgs(d.get("to")):
        await n.send(tg, text, kb)
    # finished before anyone picked a team (e.g. on the site): close the pick cards too
    await messages.accept_rev(messages.rkey(pid), t.get("rev"))
    await _edit_all(n, await messages.take_all(messages.rkey(pid)), text, kb)
    heads, assemblers = _tgs(d.get("heads")), _tgs(d.get("assemblers"))
    if heads and await messages.accept_rev(messages.hkey(pid), t.get("rev")):
        await _edit_all(
            n,
            await messages.entries_for(messages.hkey(pid), heads),
            T.head_card(t),
            K.due_kb(pid, K.PRESETS, url, "done"),
        )
    await _edit_task_cards(n, t, assemblers, T.task_card(t), K.task_kb(pid, "done", url))
