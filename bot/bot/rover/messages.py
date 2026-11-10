"""Remember the rover cards sent (`CardStore("rov")`, `rov:msg:{id}`, kind `check`), so
`rover.checked` can edit them into the done card."""

from __future__ import annotations

from bot.common.cards import CardStore

_store = CardStore("rov")


async def remember(rover_id, chat_id, message_id, kind: str = "check") -> None:
    await _store.remember(int(rover_id), chat_id, message_id, kind)


async def entries_for(rover_id, chat_ids) -> list[dict]:
    return await _store.entries_for(int(rover_id), chat_ids)


async def take(rover_id, chat_ids) -> list[dict]:
    return await _store.take(int(rover_id), chat_ids)
