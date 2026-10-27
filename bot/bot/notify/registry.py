"""Registry of backend -> bot events (`POST /notify`, docs/BOT_CONTRACT.md section 1.5).

Renderers are plain async functions registered with `@on("finance.operation_created")`::

    @on("hr.morning")
    async def morning(n: Notifier, data: dict) -> None:
        await n.send(data["chat_id"], "text", kb=ik([...]))

`Notifier` sends through the Bot API and records one `delivered` entry per send
(`{chat_id, ok, message_id, error_code, blocked}`); a Telegram 403 / "chat not found" is
`blocked: true`, never an exception. `dispatch()` returns that list.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import BufferedInputFile, Message

from bot.common.fmt import clip
from bot.common.rds import get_redis

logger = logging.getLogger(__name__)

Renderer = Callable[["Notifier", dict], Awaitable[None]]
_REGISTRY: dict[str, Renderer] = {}


class UnknownEvent(Exception):
    """The event name has no renderer (answered 400 by the route, never retried)."""


class BadEventData(Exception):
    """The payload misses fields the renderer needs (answered 400)."""


def on(event: str) -> Callable[[Renderer], Renderer]:
    def deco(fn: Renderer) -> Renderer:
        if event in _REGISTRY:
            raise RuntimeError(f"event {event} is registered twice")
        _REGISTRY[event] = fn
        return fn

    return deco


def events() -> list[str]:
    return sorted(_REGISTRY)


def _is_blocked(e: TelegramAPIError) -> bool:
    if isinstance(e, TelegramForbiddenError):
        return True
    msg = str(e).lower()
    return isinstance(e, TelegramBadRequest) and (
        "chat not found" in msg or "user is deactivated" in msg or "bot was blocked" in msg
    )


class Notifier:
    def __init__(self, bot: Bot, event_id: str | None = None):
        self.bot = bot
        self.event_id = event_id
        self.delivered: list[dict] = []
        self._n = 0  # index of the send within this renderer run

    # ---- bookkeeping
    def _ok(self, chat_id, msg: Message | None) -> None:
        self.delivered.append(
            {
                "chat_id": chat_id,
                "ok": True,
                "message_id": getattr(msg, "message_id", None),
                "error_code": None,
                "blocked": False,
            }
        )

    def _fail(self, chat_id, e: Exception) -> None:
        code = getattr(e, "error_code", None)
        blocked = isinstance(e, TelegramAPIError) and _is_blocked(e)
        logger.warning("notify to %s failed: %s", chat_id, e)
        self.delivered.append(
            {
                "chat_id": chat_id,
                "ok": False,
                "message_id": None,
                "error_code": code or (403 if blocked else None),
                "blocked": blocked,
            }
        )

    async def _try(self, chat_id, make: Callable[[], Awaitable]):
        """Run one Bot API call; one retry after a flood-control wait. Never raises on
        Telegram errors. With an event id, every (chat, n) is sent once: when a retry of
        the same envelope comes after a partial failure, finished sends are skipped."""
        key = None
        if self.event_id:
            self._n += 1
            key = f"dedup:evt:{self.event_id}:{chat_id}:{self._n}"
            try:
                if not await get_redis().set(key, "-", nx=True, ex=86400):
                    raw = await get_redis().get(key)
                    raw = raw.decode() if isinstance(raw, bytes) else str(raw or "")
                    mid = int(raw) if raw.isdigit() else None
                    self.delivered.append(
                        {"chat_id": chat_id, "ok": True, "message_id": mid,
                         "error_code": None, "blocked": False}
                    )
                    return SimpleNamespace(message_id=mid)  # already sent: a success
            except Exception:  # noqa: BLE001 - no Redis: send (maybe twice) rather than lose it
                logger.warning("per-recipient dedup unavailable")
                key = None
        res = await self._try_send(chat_id, make)
        if key:
            try:
                if res is None:
                    await get_redis().delete(key)  # failed: a retry must send it again
                else:
                    mid = getattr(res, "message_id", None)
                    if mid is not None:
                        await get_redis().set(key, str(mid), ex=86400)
            except Exception:  # noqa: BLE001
                pass
        return res

    async def _try_send(self, chat_id, make: Callable[[], Awaitable]):
        for attempt in range(2):
            try:
                res = await make()
            except TelegramRetryAfter as e:
                if attempt == 0:
                    await asyncio.sleep(min(int(e.retry_after), 5))
                    continue
                self._fail(chat_id, e)
                return None
            except TelegramAPIError as e:
                self._fail(chat_id, e)
                return None
            except (asyncio.TimeoutError, OSError) as e:
                self._fail(chat_id, e)
                return None
            self._ok(chat_id, res if isinstance(res, Message) else None)
            return res
        return None

    # ---- senders
    async def send(self, chat_id, text: str, kb=None) -> Message | None:
        return await self._try(
            chat_id, lambda: self.bot.send_message(chat_id, clip(text, 4096), reply_markup=kb)
        )

    async def many(self, chat_ids, text: str, kb=None) -> list[Message | None]:
        return [await self.send(c, text, kb) for c in dict.fromkeys(chat_ids or [])]

    async def photo(self, chat_id, photo, caption: str = "", kb=None) -> Message | None:
        """photo: a Telegram file_id (str) or PNG bytes."""
        if isinstance(photo, (bytes, bytearray)):
            photo = BufferedInputFile(bytes(photo), filename="image.png")
        return await self._try(
            chat_id,
            lambda: self.bot.send_photo(chat_id, photo, caption=clip(caption, 1024), reply_markup=kb),
        )

    async def document(self, chat_id, content: bytes, filename: str, caption: str = ""):
        doc = BufferedInputFile(content, filename=filename)
        return await self._try(
            chat_id, lambda: self.bot.send_document(chat_id, doc, caption=clip(caption, 1024))
        )

    async def edit(self, chat_id, message_id: int, text: str, kb=None) -> bool:
        """Edit a sent message; failures (deleted, not modified) are logged, not recorded."""
        try:
            await self.bot.edit_message_text(
                clip(text, 4096), chat_id=chat_id, message_id=message_id, reply_markup=kb
            )
            return True
        except TelegramAPIError as e:
            logger.info("edit %s/%s failed: %s", chat_id, message_id, e)
            return False

    async def photo_or_text(self, chat_id, photo, text: str, kb=None) -> Message | None:
        """A photo with caption; when the photo can't be sent, the text alone."""
        if photo is not None:
            mark = len(self.delivered)
            msg = await self.photo(chat_id, photo, text, kb)
            if msg is not None:
                return msg
            del self.delivered[mark:]
        return await self.send(chat_id, text, kb)


async def dispatch(envelope: dict, bot: Bot) -> list[dict]:
    """Render one envelope `{id, event, data}`; returns the delivered list."""
    event = envelope.get("event")
    fn = _REGISTRY.get(event)
    if fn is None:
        raise UnknownEvent(str(event))
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise BadEventData("data must be an object")
    n = Notifier(bot, envelope.get("id"))
    try:
        await fn(n, data)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        logger.exception("event %s: bad data", event)
        raise BadEventData(f"{type(e).__name__}: {e}") from e
    return n.delivered
