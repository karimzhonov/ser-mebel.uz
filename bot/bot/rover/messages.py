"""Remember the rover cards sent (`CardStore("rov")`, `rov:msg:{key}` + `rov:ver:{key}`).
Keys: `{id}` checker cards (kind `check`), `t{id}` worker task cards, `h{id}` head
«set the deadline» cards. Separate keys, so a chat that is both a checker and a worker keeps
its cards apart."""

from __future__ import annotations

from bot.common.cards import CardStore

_store = CardStore("rov")


def tkey(rover_id) -> str:
    return f"t{int(rover_id)}"


def hkey(rover_id) -> str:
    return f"h{int(rover_id)}"


def ckey(rover_id) -> str:
    return str(int(rover_id))


async def remember(key, chat_id, message_id, kind: str = "check") -> None:
    await _store.remember(key, chat_id, message_id, kind)


async def entries_for(key, chat_ids) -> list[dict]:
    return await _store.entries_for(key, chat_ids)


async def take(key, chat_ids) -> list[dict]:
    return await _store.take(key, chat_ids)


async def accept_rev(key, rev) -> bool:
    return await _store.accept_rev(key, rev)
