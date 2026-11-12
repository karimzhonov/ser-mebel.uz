"""Remember the cards the bot sent, so they can follow the object they show (changed in the
panel / by somebody else / in another chat). Redis is shared by all uvicorn workers.

One `CardStore(prefix)` per feature:

- `{prefix}:msg:{key}`: list of JSON `{chat_id, message_id, kind}` (+ `role` when the
  feature has several kinds of recipients), 30 days.
- `{prefix}:ver:{key}`: the last `rev` applied by a `*.changed` event, so an event that
  arrives late (or twice) never overwrites a newer card.

Used by the zamer cards (`CardStore("met")`, keys `met:msg:{id}` / `met:ver:{id}`) and the
design / price cards (`CardStore("off")`, key `{d|p}{id}`).
"""

from __future__ import annotations

import json
import logging

from redis.exceptions import WatchError

from bot.common.rds import get_redis

log = logging.getLogger("bot.common.cards")

TTL = 30 * 24 * 3600


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


def _chat(e: dict):
    try:
        return int(e.get("chat_id"))
    except (TypeError, ValueError):
        return None


class CardStore:
    def __init__(self, prefix: str):
        self.prefix = prefix

    def _key(self, key) -> str:
        return f"{self.prefix}:msg:{key}"

    def _ver(self, key) -> str:
        return f"{self.prefix}:ver:{key}"

    async def remember(self, key, chat_id, message_id, kind: str, role: str | None = None) -> None:
        entry = {"chat_id": chat_id, "message_id": message_id, "kind": kind}
        if role is not None:
            entry["role"] = role
        try:
            r = get_redis()
            k = self._key(key)
            await r.rpush(k, json.dumps(entry))
            await r.expire(k, TTL)
        except Exception:  # noqa: BLE001 - losing the mapping only costs a stale keyboard
            log.warning("could not remember card of %s:%s", self.prefix, key, exc_info=True)

    async def entries_for(self, key, chat_ids) -> list[dict]:
        """The stored cards sent to these chats (read only)."""
        wanted = {int(c) for c in chat_ids or []}
        try:
            raw = await get_redis().lrange(self._key(key), 0, -1)
        except Exception:  # noqa: BLE001
            log.warning("could not load cards of %s:%s", self.prefix, key, exc_info=True)
            return []
        return [e for e in _load(raw) if _chat(e) in wanted]

    async def take(self, key, chat_ids) -> list[dict]:
        """Read AND delete the cards of these chats in one WATCH / MULTI / EXEC, so a card
        stored in between is neither lost nor left unedited. The other chats keep theirs."""
        wanted = {int(c) for c in chat_ids or []}
        k = self._key(key)
        try:
            r = get_redis()
            for _ in range(5):
                async with r.pipeline(transaction=True) as p:
                    try:
                        await p.watch(k)
                        raw = await p.lrange(k, 0, -1)
                        mine, keep = [], []
                        for item in raw or []:
                            e = _load([item])
                            (mine if e and _chat(e[0]) in wanted else keep).append(item)
                        p.multi()
                        p.delete(k)
                        if keep:
                            p.rpush(k, *keep)
                            p.expire(k, TTL)
                        await p.execute()
                    except WatchError:
                        continue
                return _load(mine)
        except Exception:  # noqa: BLE001
            log.warning("could not take cards of %s:%s", self.prefix, key, exc_info=True)
        return []

    async def take_all(self, key) -> list[dict]:
        """Read AND delete every stored card of the key, whatever the chat."""
        try:
            raw = await get_redis().lrange(self._key(key), 0, -1)
        except Exception:  # noqa: BLE001
            log.warning("could not load cards of %s:%s", self.prefix, key, exc_info=True)
            return []
        chats = {c for c in (_chat(e) for e in _load(raw)) if c is not None}
        return await self.take(key, chats) if chats else []

    async def drop(self, key, chat_ids) -> None:
        await self.take(key, chat_ids)

    async def accept_rev(self, key, rev) -> bool:
        """True when `rev` is newer than the last applied one (and remember it), atomically
        (WATCH / MULTI / EXEC: of concurrent equal revs only one wins). An event
        without a usable rev is accepted but not remembered."""
        try:
            rev = int(rev)
        except (TypeError, ValueError):
            return True
        k = self._ver(key)
        try:
            r = get_redis()
            for _ in range(5):
                async with r.pipeline(transaction=True) as p:
                    try:
                        await p.watch(k)
                        cur = await p.get(k)
                        if cur is not None:
                            cur = int(cur.decode() if isinstance(cur, bytes) else cur)
                            if rev <= cur:
                                return False
                        p.multi()
                        p.set(k, str(rev), ex=TTL)
                        await p.execute()
                        return True
                    except WatchError:
                        continue  # somebody moved it meanwhile: re-check against the new value
        except Exception:  # noqa: BLE001 - no Redis: apply (an extra edit is harmless)
            log.warning("rev check unavailable for %s:%s", self.prefix, key, exc_info=True)
        return True
