"""Remember the zamer cards the bot sent, so they can follow the zamer (changed in the
panel / by the operator / by the measurer in another chat). Redis is shared by all uvicorn
workers.

- `met:msg:{id}`: list of JSON `{chat_id, message_id, kind}` (kind: assigned|soon|late),
  30 days.
- `met:ver:{id}`: the last `rev` applied by a `metering.changed`, so an event that arrives
  late (or twice) never overwrites a newer card.
"""

from __future__ import annotations

import json
import logging

from redis.exceptions import WatchError

from bot.common.rds import get_redis

log = logging.getLogger("bot.metering.messages")

TTL = 30 * 24 * 3600


def _key(metering_id) -> str:
    return f"met:msg:{int(metering_id)}"


def _ver(metering_id) -> str:
    return f"met:ver:{int(metering_id)}"


def _load(raw) -> list[dict]:
    out = []
    for item in raw or []:
        try:
            v = json.loads(item)
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict):
            out.append(v)
    return out


async def remember(metering_id, chat_id, message_id, kind: str) -> None:
    try:
        r = get_redis()
        key = _key(metering_id)
        await r.rpush(key, json.dumps({"chat_id": chat_id, "message_id": message_id, "kind": kind}))
        await r.expire(key, TTL)
    except Exception:  # noqa: BLE001 - losing the mapping only costs a stale keyboard
        log.warning("could not remember card of metering %s", metering_id, exc_info=True)


async def entries_for(metering_id, chat_ids) -> list[dict]:
    """The stored cards sent to these chats (read only)."""
    wanted = {int(c) for c in chat_ids or []}
    try:
        raw = await get_redis().lrange(_key(metering_id), 0, -1)
    except Exception:  # noqa: BLE001
        log.warning("could not load cards of metering %s", metering_id, exc_info=True)
        return []
    return [e for e in _load(raw) if _chat(e) in wanted]


def _chat(e: dict):
    try:
        return int(e.get("chat_id"))
    except (TypeError, ValueError):
        return None


async def take(metering_id, chat_ids) -> list[dict]:
    """Read AND delete the cards of these chats in one WATCH / MULTI / EXEC, so a card
    stored in between is neither lost nor left unedited. The other chats keep theirs."""
    wanted = {int(c) for c in chat_ids or []}
    key = _key(metering_id)
    try:
        r = get_redis()
        for _ in range(5):
            async with r.pipeline(transaction=True) as p:
                try:
                    await p.watch(key)
                    raw = await p.lrange(key, 0, -1)
                    mine, keep = [], []
                    for item in raw or []:
                        e = _load([item])
                        (mine if e and _chat(e[0]) in wanted else keep).append(item)
                    p.multi()
                    p.delete(key)
                    if keep:
                        p.rpush(key, *keep)
                        p.expire(key, TTL)
                    await p.execute()
                except WatchError:
                    continue
            return _load(mine)
    except Exception:  # noqa: BLE001
        log.warning("could not take cards of metering %s", metering_id, exc_info=True)
    return []


async def drop(metering_id, chat_ids) -> None:
    await take(metering_id, chat_ids)


async def accept_rev(metering_id, rev) -> bool:
    """True when `rev` is newer than the last applied one (and remember it), atomically
    (WATCH / MULTI / EXEC: of concurrent equal revs only one wins). An event
    without a usable rev is accepted but not remembered."""
    try:
        rev = int(rev)
    except (TypeError, ValueError):
        return True
    key = _ver(metering_id)
    try:
        r = get_redis()
        for _ in range(5):
            async with r.pipeline(transaction=True) as p:
                try:
                    await p.watch(key)
                    cur = await p.get(key)
                    if cur is not None:
                        cur = int(cur.decode() if isinstance(cur, bytes) else cur)
                        if rev <= cur:
                            return False
                    p.multi()
                    p.set(key, str(rev), ex=TTL)
                    await p.execute()
                    return True
                except WatchError:
                    continue  # somebody moved it meanwhile: re-check against the new value
    except Exception:  # noqa: BLE001 - no Redis: apply (an extra edit is harmless)
        log.warning("rev check unavailable for metering %s", metering_id, exc_info=True)
    return True
