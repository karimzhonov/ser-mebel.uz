"""Remember the painter cards sent (`CardStore("pnt")`, `pnt:msg:{key}` + `pnt:ver:{key}`).
Keys: `t{id}u{user_id}` task cards, one key per assignee (task and unassigned events share a
rev, so separate keys let both apply and reject a late «unassigned» after A -> B -> A),
`h{id}` head «set the deadline» cards, `r{id}` head «pick the team» cards (rover ready).
Split jobs (one job, several teams, each team = a *part*): `p{part}u{user_id}` part worker
cards and `q{part}` part deadline cards, rev-guarded by the PART's rev; `r{id}` / `h{id}` /
`t{id}u{uid}` stay guarded by the JOB's rev."""

from __future__ import annotations

from bot.common.cards import CardStore

_store = CardStore("pnt")


def tkey(painter_id, user_id) -> str:
    return f"t{int(painter_id)}u{int(user_id)}"


def hkey(painter_id) -> str:
    return f"h{int(painter_id)}"


def rkey(painter_id) -> str:
    return f"r{int(painter_id)}"


def pkey(part_id, user_id) -> str:
    return f"p{int(part_id)}u{int(user_id)}"


def qkey(part_id) -> str:
    return f"q{int(part_id)}"


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
