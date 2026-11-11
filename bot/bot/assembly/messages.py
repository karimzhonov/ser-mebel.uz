"""Remember the assembly cards sent (`CardStore("asm")`, `asm:msg:{key}` + `asm:ver:{key}`).
Keys: `t{id}u{user_id}` assembler task cards, one key per assignee (task and unassigned events
share a rev, so separate keys let both apply and reject a late «unassigned» after A -> B -> A),
`h{id}` head «set the deadline» cards, `r{id}` head «pick the team» cards (assembly ready), `c{id}` head «✅ Tayyor» confirm cards
(assembly done = installed, waiting for the head)."""

from __future__ import annotations

from bot.common.cards import CardStore

_store = CardStore("asm")


def tkey(assembly_id, user_id) -> str:
    return f"t{int(assembly_id)}u{int(user_id)}"


def hkey(assembly_id) -> str:
    return f"h{int(assembly_id)}"


def ckey(assembly_id) -> str:
    return f"c{int(assembly_id)}"


def rkey(assembly_id) -> str:
    return f"r{int(assembly_id)}"


async def remember(key, chat_id, message_id, kind: str = "task") -> None:
    await _store.remember(key, chat_id, message_id, kind)


async def entries_for(key, chat_ids) -> list[dict]:
    return await _store.entries_for(key, chat_ids)


async def take(key, chat_ids) -> list[dict]:
    return await _store.take(key, chat_ids)


async def accept_rev(key, rev) -> bool:
    return await _store.accept_rev(key, rev)


async def take_all(key) -> list[dict]:
    """Read AND delete every stored card of the key (whatever the chat)."""
    return await _store.take_all(key)
