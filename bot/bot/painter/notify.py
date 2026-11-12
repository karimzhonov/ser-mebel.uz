"""Painter events (backend -> bot).

- `painter.task`: full task card to the assigned painter (store key `t{id}u{user_id}`); also
  closes the heads' `r{id}` «pick the team» cards (fires on every team pick).
- `painter.unassigned`: the old painter's card is edited into «boshqa molyarga o'tkazildi».
- `painter.ready`: «pick the team» card to the production heads (`r{id}`, one button per team).
- `painter.due_ask`: «set the deadline» card to the production heads (`h{id}`); also turns
  the stored `r{id}` cards into «✅ Jamoa: …» (the team may be picked on the site).
- `painter.due_set`: edits the painter / head cards, short message to the painter.
- `painter.remind`: soon / overdue messages, not stored.
- `painter.done`: «Molyar tayyor» message; edits the stored head / painter cards.

Split jobs (one job, several teams = parts; ids below are PART ids, rev = the part's rev):
- `painter.part_task`: worker card (`p{part}u{uid}`, «✅ Bajardim» `pn:pd`); reason `resized`
  edits the stored cards + short «Maydon o'zgardi» message (fresh card when none stored).
- `painter.part_unassigned`: edits `p{part}u{prev}` into «boshqa molyarga o'tkazildi».
- `painter.part_due_ask` (`q{part}`), `painter.part_due_set`, `painter.part_remind`.
- `painter.part_done`: edits the `p` / `q` cards; message to `to` unless `job_done` (the
  `painter.done` that follows carries it).
- `painter.assigned`: edits the stored `r{id}` cards (job rev) into «✅ Jamoalar: …»; the
  cards stay (and keep a split link) while an unassigned remainder exists.
- `painter.remainder`: all parts done but m² left unassigned -> message to the heads.
- DEPRECATED, not emitted any more but still rendered for queued envelopes (one release):
  `painter.task|unassigned|due_ask|due_set|remind`.
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


async def _close_team_cards(n: Notifier, t: dict) -> None:
    """Edit every stored `r{id}` «pick the team» card into «✅ Jamoa: …» (site link only)."""
    if not t.get("type"):
        return
    # record the rev so a `painter.ready` delivered late doesn't send a fresh pick card
    await messages.accept_rev(messages.rkey(int(t["id"])), t.get("rev"))
    entries = await messages.take_all(messages.rkey(int(t["id"])))
    await _edit_all(n, entries, T.team_chosen(t), K.link_kb(t.get("url") or ""))


@on("painter.task")
async def task(n: Notifier, d: dict) -> None:
    t = d["painter"]
    pid = int(t["id"])
    uid = _uid(t.get("painter"))
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
    pid = int(t["id"])
    key = messages.rkey(pid)
    if not await messages.accept_rev(key, t.get("rev")):
        return
    text = T.ready_msg(t)
    kb = K.team_kb(pid, d.get("types") or [], t.get("url") or "", t.get("split_url") or "")
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await messages.remember(key, tg, mid, "team")


@on("painter.due_ask")
async def due_ask(n: Notifier, d: dict) -> None:
    t = d["painter"]
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
    parts = [p for p in t.get("parts") or [] if isinstance(p, dict)]
    if not parts:
        await _edit_task_cards(n, t, painters, T.task_card(t), K.task_kb(pid, "done", url))
        return
    # legacy `t{id}u{uid}` cards (sent before the split) of every team's painter
    for p in parts:
        legacy = dict(t, painter=p.get("painter"), type=p.get("type"), outsource=p.get("outsource"))
        await _edit_task_cards(
            n, legacy, painters, T.task_card(legacy), K.task_kb(pid, "done", url)
        )


# ---------------------------------------------------------------- split jobs: parts


def _part_url(p: dict) -> str:
    return p.get("url") or ""


@on("painter.part_task")
async def part_task(n: Notifier, d: dict) -> None:
    p = d["part"]
    part_id = int(p["id"])
    uid = _uid(p.get("painter"))
    key = messages.pkey(part_id, uid) if uid is not None else None
    chats = _tgs(d.get("to"))
    text = T.part_task_card(p)
    kb = K.part_task_kb(part_id, p.get("state") or "new", _part_url(p))
    if d.get("reason") == "resized":
        if key and not await messages.accept_rev(key, p.get("rev")):
            return  # an older resize arrived late
        stored = {
            e.get("chat_id"): e for e in (await messages.entries_for(key, chats) if key else [])
        }
        await _edit_all(n, list(stored.values()), text, kb)
        notice = T.resized_msg(p)
        for tg in chats:
            await n.send(tg, notice)
            if tg not in stored:  # no card to edit: send a fresh one
                msg = await n.send(tg, text, kb)
                mid = getattr(msg, "message_id", None)
                if mid is not None and key:
                    await messages.remember(key, tg, mid, "task")
        return
    # a late older envelope is dropped only when a card already exists; if a newer event
    # (e.g. a deadline) overtook the first card, the card is still sent
    if (
        key
        and not await messages.accept_rev(key, p.get("rev"))
        and await messages.entries_for(key, chats)
    ):
        return
    for tg in chats:
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None and key:
            await messages.remember(key, tg, mid, "task")


@on("painter.part_unassigned")
async def part_unassigned(n: Notifier, d: dict) -> None:
    p = d["part"]
    prev = _uid(d.get("prev"))
    chats = _tgs(d.get("to"))
    if prev is None or not chats:
        return
    key = messages.pkey(p["id"], prev)
    if not await messages.accept_rev(key, p.get("rev")):
        return  # the part came back to this painter meanwhile
    entries = await messages.take(key, chats)
    await _edit_all(n, entries, T.part_reassigned_card(p), K.link_kb(_part_url(p)))


@on("painter.part_due_ask")
async def part_due_ask(n: Notifier, d: dict) -> None:
    p = d["part"]
    part_id = int(p["id"])
    key = messages.qkey(part_id)
    await messages.accept_rev(key, p.get("rev"))
    text = T.part_head_card(p)
    kb = K.part_due_kb(part_id, _presets(d), _part_url(p), p.get("state") or "new")
    for tg in _tgs(d.get("to")):
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await messages.remember(key, tg, mid, "head")


@on("painter.part_due_set")
async def part_due_set(n: Notifier, d: dict) -> None:
    p = d["part"]
    part_id = int(p["id"])
    url = _part_url(p)
    state = p.get("state") or "new"
    workers, heads = _tgs(d.get("to")), _tgs(d.get("heads"))
    uid = _uid(p.get("painter"))
    if workers and uid is not None:
        key = messages.pkey(part_id, uid)
        if await messages.accept_rev(key, p.get("rev")):
            await _edit_all(
                n,
                await messages.entries_for(key, workers),
                T.part_task_card(p),
                K.part_task_kb(part_id, state, url),
            )
            msg = T.part_due_set_msg(p, d.get("how"), d.get("by_name"))
            for tg in workers:
                await n.send(tg, msg)
    if heads and await messages.accept_rev(messages.qkey(part_id), p.get("rev")):
        await _edit_all(
            n,
            await messages.entries_for(messages.qkey(part_id), heads),
            T.part_head_card(p),
            K.part_due_kb(part_id, K.PRESETS, url, state),
        )


@on("painter.part_remind")
async def part_remind(n: Notifier, d: dict) -> None:
    p = d["part"]
    part_id = int(p["id"])
    url = _part_url(p)
    what = "overdue" if d.get("what") == "overdue" else "soon"
    late = d.get("days_late") or p.get("days_late") or 0
    text = T.part_remind_text(p, what, late)
    for tg in _tgs(d.get("to")):
        await n.send(tg, text, K.part_task_kb(part_id, "new", url))
    if what == "overdue":
        htext = T.part_remind_text(p, what, late, head=True)
        for tg in _tgs(d.get("heads")):
            await n.send(tg, htext, K.part_due_kb(part_id, K.PRESETS, url))


@on("painter.part_done")
async def part_done(n: Notifier, d: dict) -> None:
    p = d["part"]
    part_id = int(p["id"])
    url = _part_url(p)
    heads, workers = _tgs(d.get("heads")), _tgs(d.get("painters"))
    uid = _uid(p.get("painter"))
    if workers and uid is not None:
        key = messages.pkey(part_id, uid)
        if await messages.accept_rev(key, p.get("rev")):
            await _edit_all(
                n,
                await messages.entries_for(key, workers),
                T.part_task_card(p),
                K.part_task_kb(part_id, "done", url),
            )
    if heads and await messages.accept_rev(messages.qkey(part_id), p.get("rev")):
        await _edit_all(
            n,
            await messages.entries_for(messages.qkey(part_id), heads),
            T.part_head_card(p),
            K.part_due_kb(part_id, K.PRESETS, url, "done"),
        )
    if not d.get("job_done"):
        text = T.part_done_msg(p, d.get("by_name"))
        for tg in _tgs(d.get("to")):
            await n.send(tg, text, K.link_kb(url))


@on("painter.assigned")
async def assigned(n: Notifier, d: dict) -> None:
    t = d["painter"]
    pid = int(t["id"])
    key = messages.rkey(pid)
    if not await messages.accept_rev(key, t.get("rev")):
        return
    text = T.team_chosen(t)
    url = t.get("url") or ""
    if T.remainder_of(t):
        # m² still to give: keep the cards (later `assigned` events edit them again)
        entries = await messages.entries_for(key, _tgs(d.get("to")))
        kb = K.split_kb(t.get("split_url") or "", url)
    else:
        entries = await messages.take_all(key)
        kb = K.link_kb(url)
    await _edit_all(n, entries, text, kb)


@on("painter.remainder")
async def remainder(n: Notifier, d: dict) -> None:
    t = d["painter"]
    left = d.get("remainder")
    text = T.remainder_msg(t, left)
    kb = K.split_kb(t.get("split_url") or "", t.get("url") or "")
    for tg in _tgs(d.get("to")):
        await n.send(tg, text, kb)
