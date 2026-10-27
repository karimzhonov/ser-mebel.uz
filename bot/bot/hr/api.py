"""Plumbing shared by the davomat handlers: backend calls, error replies, Telegram sends.

Handlers stay thin: they relay Telegram facts to `/api/v1/bot/hr/...` (docs/BOT_CONTRACT.md)
and render the answer. All rules live in the backend.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging

from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import CallbackQuery, Message, User

from bot.backend.client import (  # noqa: F401  (re-exported for the handlers)
    BackendDown,
    BackendError,
    Conflict,
    Forbidden,
    NotFound,
    ServiceRefusal,
    backend,
)

log = logging.getLogger("bot.hr")

DOWN_TEXT = "⚠️ Server bilan aloqa yo'q. Birozdan keyin qayta urinib ko'ring."


# ------------------------------------------------------------------ backend
async def call(method: str, path: str, *, actor=None, json=None, params=None):
    return await backend.request(method, path, actor=actor, json=json, params=params)


def user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username or "",
        "first_name": u.first_name or "",
        "last_name": u.last_name or "",
        "is_bot": bool(u.is_bot),
    }


async def ensure_actor(actor, user: User):
    """The ActorMiddleware puts `actor` (common.actor.Actor, built from the whoami answer)
    into the handler data in private chats; call whoami ourselves if it is missing. Either
    form works with hr_of / employee_of / is_admin."""
    if actor is not None:
        return actor
    return await call("POST", "whoami/", actor=user.id, json={"user": user_dict(user)})


def hr_of(actor) -> dict:
    """{"employee": dict|None, "is_admin": bool} of an Actor object or a whoami dict."""
    if actor is None:
        return {}
    if isinstance(actor, dict):
        return actor.get("hr") or {}
    return getattr(actor, "hr", None) or {}


def employee_of(actor) -> dict | None:
    return hr_of(actor).get("employee")


def is_admin(actor) -> bool:
    return bool(hr_of(actor).get("is_admin"))


def err_text(e: BackendError) -> str:
    if isinstance(e, BackendDown):
        return DOWN_TEXT
    return f"❗ {e.detail}" if e.detail else "❗ Xatolik."


async def _report_error(event, e: BackendError) -> None:
    text = err_text(e)
    try:
        if isinstance(event, CallbackQuery):
            await event.answer(text[:200], show_alert=True)
        elif isinstance(event, Message):
            await event.answer(text)
    except TelegramAPIError:
        log.warning("could not report a backend error to the user", exc_info=True)


def guarded(fn):
    """Catch backend errors of a handler and tell the user (`❗ detail`). Data keys the
    handler does not declare are dropped."""
    params = inspect.signature(fn).parameters
    takes_all = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())

    @functools.wraps(fn)
    async def wrapper(event, **kwargs):
        if not takes_all:
            kwargs = {k: v for k, v in kwargs.items() if k in params}
        try:
            return await fn(event, **kwargs)
        except BackendError as e:
            await _report_error(event, e)

    return wrapper


def guarded_quiet(fn):
    """For automatic group handlers: never answer in the group. Backend errors are logged;
    BackendDown is re-raised so the update dedup key is dropped and Telegram's retry is
    processed (a check-in must not be lost)."""
    params = inspect.signature(fn).parameters
    takes_all = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())

    @functools.wraps(fn)
    async def wrapper(event, **kwargs):
        if not takes_all:
            kwargs = {k: v for k, v in kwargs.items() if k in params}
        try:
            return await fn(event, **kwargs)
        except BackendDown:
            log.error("backend down in %s", fn.__name__)
            raise
        except BackendError as e:
            log.warning("%s: backend refused: %s", fn.__name__, e.detail)

    return wrapper


# ------------------------------------------------------------------ telegram
def get_bot():
    from bot import bot

    return bot


def delivery(chat_id, ok=False, message_id=None, error_code=None, blocked=False) -> dict:
    return {
        "chat_id": chat_id,
        "ok": ok,
        "message_id": message_id,
        "error_code": error_code,
        "blocked": blocked,
    }


def _is_blocked(e: TelegramAPIError) -> bool:
    msg = str(getattr(e, "message", "") or e).lower()
    return isinstance(e, TelegramForbiddenError) or "chat not found" in msg or "blocked" in msg


async def send(chat_id, text: str, kb=None) -> dict:
    """Send HTML to a chat; never raises for Telegram refusals. Returns the `/notify`
    delivery entry {chat_id, ok, message_id, error_code, blocked}."""
    bot = get_bot()
    for attempt in (0, 1):
        try:
            m = await bot.send_message(
                chat_id,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
            return delivery(chat_id, True, m.message_id)
        except TelegramRetryAfter as e:
            if attempt == 0:
                await asyncio.sleep(min(float(e.retry_after), 5.0))
                continue
            return delivery(chat_id, error_code=429)
        except TelegramAPIError as e:
            code = 403 if isinstance(e, TelegramForbiddenError) else getattr(e, "error_code", None)
            blocked = _is_blocked(e)
            log.info("send to %s failed: %s", chat_id, e)
            if isinstance(e, TelegramBadRequest) and blocked:
                code = 400
            return delivery(chat_id, error_code=code, blocked=blocked)
    return delivery(chat_id)


async def send_dm(tg_id: int, text: str, kb=None, *, report: bool = False, actor=None) -> dict:
    """Private message to someone. With report=True the result also goes to
    `hr/dm-status/` so the backend keeps Employee.can_dm right (interactive DMs; the
    `/notify` path reports through its response instead)."""
    d = await send(tg_id, text, kb)
    if report:
        try:
            await call(
                "POST",
                "hr/dm-status/",
                actor=actor if actor is not None else tg_id,
                json={"telegram_id": tg_id, "ok": d["ok"], "blocked": d["blocked"]},
            )
        except BackendError:
            log.warning("dm-status for %s not recorded", tg_id)
    return d


async def edit(message: Message | None, text: str, kb=None) -> None:
    """editMessageText with HTML; an empty keyboard when none is given (the old edit())."""
    if message is None:
        return
    try:
        await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            log.info("edit failed: %s", e)
            raise


async def clear_kb(message: Message | None) -> None:
    if message is None:
        return
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        log.info("clear keyboard failed", exc_info=True)


async def answer(message: Message, text: str, kb=None):
    return await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
