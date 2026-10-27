"""Update-level middlewares: dedup, per-user lock, and the actor (`whoami`).

Order on `dp.update.outer_middleware`: Dedup -> UserLock. The actor middleware is an OUTER
middleware on `dp.message` / `dp.callback_query` (private chats only), so router filters
(`actor` in their kwargs) already see it.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update, User
from redis.exceptions import LockError

from bot.backend.client import BackendDown, BackendError, backend
from bot.common.actor import Actor
from bot.common.rds import get_redis

logger = logging.getLogger(__name__)

DEDUP_TTL = 86400
LOCK_TIMEOUT = 60
LOCK_WAIT = 30
WHOAMI_TTL = 30

DOWN_TEXT = "⚠️ Server vaqtincha ishlamayapti. Birozdan keyin qayta urinib ko'ring."


class DedupMiddleware(BaseMiddleware):
    """A Telegram retry of an already handled update is dropped. When the handler
    raises, the key is deleted again so Telegram's retry is processed."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        uid = getattr(event, "update_id", None)
        if uid is None:
            return await handler(event, data)
        r = get_redis()
        key = f"dedup:upd:{uid}"
        if not await r.set(key, 1, nx=True, ex=DEDUP_TTL):
            logger.info("duplicate update %s dropped", uid)
            return None
        try:
            return await handler(event, data)
        except BaseException:
            await r.delete(key)
            raise


class UserLockMiddleware(BaseMiddleware):
    """One update per person at a time (two quick button presses must not both save)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        lock = get_redis().lock(
            f"lock:user:{user.id}", timeout=LOCK_TIMEOUT, blocking_timeout=LOCK_WAIT
        )
        try:
            acquired = await lock.acquire()
        except Exception:  # noqa: BLE001 - Redis hiccup: better late than never
            logger.exception("user lock failed for %s", user.id)
            return await handler(event, data)
        if not acquired:
            logger.warning("user lock timeout for %s, processing anyway", user.id)
            return await handler(event, data)
        try:
            return await handler(event, data)
        finally:
            try:
                await lock.release()
            except LockError:
                pass  # expired while a slow handler ran


class ActorMiddleware(BaseMiddleware):
    """Private chats: `POST whoami/` -> data["actor"] (an `Actor`). Also refreshes the
    username server-side. Backend down: a friendly answer, the handler is skipped."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        msg = event if isinstance(event, Message) else getattr(event, "message", None)
        chat = getattr(msg, "chat", None)
        user: User | None = data.get("event_from_user")
        if chat is None or chat.type != "private" or user is None or user.is_bot:
            return await handler(event, data)
        try:
            who = await self._whoami(user)
        except BackendError as e:
            logger.error("whoami failed for %s: %s", user.id, e)
            await self._say(event, DOWN_TEXT if isinstance(e, BackendDown) else f"❗ {e.detail}")
            return None
        data["actor"] = Actor.from_whoami(user, who or {})
        return await handler(event, data)

    @staticmethod
    async def _whoami(user: User) -> dict:
        """Cached per person for WHOAMI_TTL s; the backend client drops the entry after
        any write made for that person."""
        r = get_redis()
        key = f"whoami:{user.id}"
        try:
            raw = await r.get(key)
            if raw:
                return json.loads(raw)
        except Exception:  # noqa: BLE001 - the cache is optional
            logger.warning("whoami cache read failed")
        who = await backend.request(
            "POST",
            "whoami/",
            actor=user.id,
            json={
                "user": {
                    "id": user.id,
                    "username": user.username or "",
                    "first_name": user.first_name or "",
                    "last_name": user.last_name or "",
                }
            },
        )
        try:
            await r.set(key, json.dumps(who or {}), ex=WHOAMI_TTL)
        except Exception:  # noqa: BLE001
            logger.warning("whoami cache write failed")
        return who or {}

    @staticmethod
    async def _say(event: TelegramObject, text: str) -> None:
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(text[:190], show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
        except Exception:  # noqa: BLE001
            logger.exception("could not tell the user the backend is down")
