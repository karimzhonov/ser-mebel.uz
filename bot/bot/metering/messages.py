"""Remember the zamer cards the bot sent, so they can follow the zamer (changed in the
panel / by the operator / by the measurer in another chat). Thin wrapper over the shared
`CardStore("met")` (bot/common/cards.py), keeping the Redis keys:

- `met:msg:{id}`: list of JSON `{chat_id, message_id, kind}` (kind: assigned|soon|late),
  30 days.
- `met:ver:{id}`: the last `rev` applied by a `metering.changed`.
"""

from __future__ import annotations

from bot.common.cards import TTL, CardStore  # noqa: F401

_store = CardStore("met")


def _key(metering_id) -> str:
    return _store._key(int(metering_id))


def _ver(metering_id) -> str:
    return _store._ver(int(metering_id))


async def remember(metering_id, chat_id, message_id, kind: str) -> None:
    await _store.remember(int(metering_id), chat_id, message_id, kind)


async def entries_for(metering_id, chat_ids) -> list[dict]:
    """The stored cards sent to these chats (read only)."""
    return await _store.entries_for(int(metering_id), chat_ids)


async def take(metering_id, chat_ids) -> list[dict]:
    return await _store.take(int(metering_id), chat_ids)


async def drop(metering_id, chat_ids) -> None:
    await _store.drop(int(metering_id), chat_ids)


async def accept_rev(metering_id, rev) -> bool:
    return await _store.accept_rev(int(metering_id), rev)
