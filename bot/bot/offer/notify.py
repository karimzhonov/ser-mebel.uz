"""Design / price events (backend -> bot): `offer.assigned` / `offer.reminder` send the
card to the designer / pricer, `offer.present` the manager's card (client's answer buttons),
`offer.changed` keeps the cards sent earlier up to date, `offer.order_ready` tells who may
create the order. Wording lives here; the backend sends data only (docs/BOT_CONTRACT.md).
The edit rule: only the chats in `to` are edited, only when the event's `rev` (per kind and
id) is newer than the last applied one, and finished cards lose their keyboard and are
forgotten."""

from __future__ import annotations

import logging

from bot.common.cards import CardStore
from bot.notify.registry import Notifier, on

from . import keyboards as K
from . import texts as T

log = logging.getLogger("bot.offer.notify")

store = CardStore("off")

# how -> the role of the card that is finished by it
FINAL_ROLE = {
    "done": "work",
    "reassigned": "work",
    "cancelled": "work",
    "answered": "present",
}


def _tgs(value) -> list[int]:
    if isinstance(value, (int, str)) and str(value).lstrip("-").isdigit():
        return [int(value)]
    return [int(x) for x in (value or [])]


def _code(task: dict) -> str:
    return T.CODE.get(task.get("kind"), "d")


def work_kb(task: dict):
    if task.get("stage") != "work":
        return K.site_kb(task.get("url") or "")
    return K.work_kb(_code(task), int(task["id"]), task.get("url") or "")


def present_kb(task: dict):
    return K.present_kb(_code(task), int(task["id"]), task.get("present_url") or "")


async def _send(n: Notifier, tg: int, task: dict, text: str, kb, kind: str, role: str) -> None:
    msg = await n.send(tg, text, kb)
    mid = getattr(msg, "message_id", None)
    if mid is not None:
        await store.remember(T.key_of(task), tg, mid, kind, role)


@on("offer.assigned")
async def assigned(n: Notifier, d: dict) -> None:
    task = d["task"]
    how = d.get("how")
    kind = how if how in ("reassigned", "changes", "started") else "new"
    text = T.work_card(task, kind, comment=d.get("comment"))
    kb = work_kb(task)
    for tg in _tgs(d.get("to")):
        await _send(n, tg, task, text, kb, kind, "work")


@on("offer.reminder")
async def reminder(n: Notifier, d: dict) -> None:
    task = d["task"]
    kind = d.get("kind") if d.get("kind") in ("soon", "late", "overdue") else "soon"
    text = T.work_card(task, kind)
    kb = work_kb(task)
    for tg in _tgs(d.get("to")):
        await _send(n, tg, task, text, kb, kind, "work")


@on("offer.present")
async def present(n: Notifier, d: dict) -> None:
    task = d["task"]
    kind = "reminder" if d.get("how") == "reminder" else "ready"
    text = T.present_card(task, kind)
    kb = present_kb(task)
    for tg in _tgs(d.get("to")):
        await _send(n, tg, task, text, kb, kind, "present")


def _render(task: dict, e: dict, how: str, d: dict) -> tuple[str, object]:
    role = e.get("role") or "work"
    kind = e.get("kind") or "new"
    if how in FINAL_ROLE:
        line = T.final_line(role, how, task, answer=d.get("answer"), to_name=d.get("to_name"))
        if role == "present":
            return T.present_card(task, kind, final=line), None
        return T.work_card(task, kind, final=line), None
    # due_moved (and anything unknown): same card, fresh data, keyboard kept
    if role == "present":
        return T.present_card(task, kind), present_kb(task)
    return T.work_card(task, kind), work_kb(task)


@on("offer.changed")
async def changed(n: Notifier, d: dict) -> None:
    task = d["task"]
    key = T.key_of(task)
    how = d.get("how")
    if not await store.accept_rev(key, task.get("rev")):
        log.info("offer %s: event rev %s is not newer, skipped", key, task.get("rev"))
        return
    to = _tgs(d.get("to"))
    role = FINAL_ROLE.get(how)
    if role:
        entries = await store.take(key, to)
        # a person may hold both kinds of cards: only the finished role is edited
        for e in entries:
            if (e.get("role") or "work") != role:
                await store.remember(
                    key, e["chat_id"], e["message_id"], e.get("kind") or "new", e.get("role")
                )
        entries = [e for e in entries if (e.get("role") or "work") == role]
    else:
        entries = await store.entries_for(key, to)
    for e in entries:
        try:
            text, kb = _render(task, e, how, d)
            await n.edit(e["chat_id"], e["message_id"], text, kb)
        except (KeyError, TypeError):
            continue
    if how == "due_moved":
        text = T.moved_watch(task, d.get("by_name") or "")
        for tg in _tgs(d.get("watchers")):
            await n.send(tg, text, K.site_kb(task.get("url") or ""))


@on("offer.order_ready")
async def order_ready(n: Notifier, d: dict) -> None:
    task = d["task"]
    kb = K.site_kb(d.get("url") or task.get("url") or "")
    for tg in _tgs(d.get("to")):
        await n.send(tg, T.order_ready(task), kb)
