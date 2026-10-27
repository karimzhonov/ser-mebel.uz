"""Per-update context of the finance handlers: sending/editing messages in the current
chat, the draft (FSM data) and the backend calls made on behalf of the actor.

`Ctx` is the port of the old `Ctx` + `api.send/edit/...`; the handler wrappers at the
bottom turn backend errors into the user-visible «❗ ...» lines.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from bot.backend.client import (
    BackendDown,
    BackendError,
    Conflict,
    Forbidden,
    NotFound,
    ServiceRefusal,
    backend,
)
from bot.common.actor import Actor
from bot.common.fmt import clip, esc
from bot.common.middlewares import DOWN_TEXT
from bot.finance.states import STEP_STATE

logger = logging.getLogger(__name__)

FLOW_KEY = "_flow"
FLOW_MAX = 80


class Ctx:
    def __init__(
        self,
        bot: Bot,
        actor: Actor,
        state: FSMContext,
        chat_id: int,
        *,
        cb: CallbackQuery | None = None,
        msg: Message | None = None,
    ):
        self.bot = bot
        self.actor = actor
        self.state = state
        self.chat = chat_id
        self.cb = cb
        self.msg = msg
        self.cb_msg: int | None = None
        self.cb_photo = False
        if cb is not None and cb.message is not None:
            self.cb_msg = cb.message.message_id
            self.cb_photo = bool(getattr(cb.message, "photo", None))
        self.tracked: list[int] = [msg.message_id] if msg is not None else []
        self.flow0: list[int] = []
        self.done = False  # «Bekor qilish» deleted the flow already

    # ------------------------------------------------------------ identity
    @property
    def tg_id(self) -> int:
        return self.actor.tg_id

    @property
    def uid(self) -> str:
        return str(self.actor.tg_id)

    @property
    def member(self) -> dict | None:
        return self.actor.member

    @property
    def admin(self) -> bool:
        return self.actor.is_admin

    @property
    def active(self) -> bool:
        return self.actor.active

    @property
    def name(self) -> str:
        return self.actor.name

    # ------------------------------------------------------------ backend
    async def api(self, method: str, path: str, **kw):
        return await backend.request(method, path, actor=self.tg_id, **kw)

    async def get(self, path: str, **params):
        return await backend.request(
            "GET", path, actor=self.tg_id, params={k: v for k, v in params.items() if v is not None}
        )

    # ------------------------------------------------------------ draft (FSM data)
    async def load(self) -> None:
        self.flow0 = list((await self.state.get_data()).get(FLOW_KEY) or [])

    async def st(self) -> dict | None:
        data = await self.state.get_data()
        d = {k: v for k, v in data.items() if k != FLOW_KEY}
        return d or None

    async def set_st(self, d: dict) -> None:
        step = d.get("step")
        st = STEP_STATE.get(step)
        await self.state.set_data({**d, FLOW_KEY: self.flow0})
        if st is not None:
            await self.state.set_state(st)

    async def clr_st(self) -> None:
        await self.state.clear()

    async def finish(self) -> None:
        """Remember the ids of this flow's messages so «❌ Bekor qilish» can delete them."""
        if self.done:
            return
        data = await self.state.get_data()
        if any(k != FLOW_KEY for k in data):
            ids = (self.flow0 + self.tracked)[-FLOW_MAX:]
            await self.state.update_data({FLOW_KEY: ids})

    # ------------------------------------------------------------ sending
    def _track(self, m: Message | None) -> Message | None:
        if m is not None:
            self.tracked.append(m.message_id)
        return m

    async def send(self, text: str, kb=None) -> Message | None:
        try:
            return self._track(
                await self.bot.send_message(self.chat, clip(text, 4096), reply_markup=kb)
            )
        except TelegramAPIError as e:
            logger.warning("send to %s failed: %s", self.chat, e)
            return None

    async def show(self, text: str, kb=None) -> Message | None:
        """Edit the message whose button was pressed, else send a new one (show_)."""
        if self.cb_msg and not self.cb_photo:
            try:
                await self.bot.edit_message_text(
                    clip(text, 4096),
                    chat_id=self.chat,
                    message_id=self.cb_msg,
                    reply_markup=kb if isinstance(kb, InlineKeyboardMarkup) else None,
                )
                return None
            except TelegramBadRequest as e:
                if "not modified" in str(e).lower():
                    return None
            except TelegramAPIError as e:
                logger.info("edit failed, sending instead: %s", e)
        return await self.send(text, kb)

    async def show_photo(self, png: bytes | None, caption: str, kb=None) -> Message | None:
        if not png:
            return await self.show(caption, kb)
        if self.cb_msg and self.cb_photo:
            try:
                await self.bot.edit_message_media(
                    InputMediaPhoto(
                        media=BufferedInputFile(png, filename="image.png"),
                        caption=clip(caption, 1024),
                    ),
                    chat_id=self.chat,
                    message_id=self.cb_msg,
                    reply_markup=kb,
                )
                return None
            except TelegramAPIError as e:
                logger.info("edit_media failed, sending instead: %s", e)
        return await self.photo(png, caption, kb)

    async def photo(self, photo, caption: str = "", kb=None) -> Message | None:
        if isinstance(photo, (bytes, bytearray)):
            photo = BufferedInputFile(bytes(photo), filename="image.png")
        try:
            return self._track(
                await self.bot.send_photo(
                    self.chat, photo, caption=clip(caption, 1024), reply_markup=kb
                )
            )
        except TelegramAPIError as e:
            logger.warning("send_photo to %s failed: %s", self.chat, e)
            return None

    async def document(self, content: bytes, filename: str, caption: str = "") -> Message | None:
        try:
            return self._track(
                await self.bot.send_document(
                    self.chat,
                    BufferedInputFile(content, filename=filename),
                    caption=clip(caption, 1024),
                )
            )
        except TelegramAPIError as e:
            logger.warning("send_document to %s failed: %s", self.chat, e)
            return None

    async def clear_kb(self, kb=None) -> None:
        if not self.cb_msg:
            return
        try:
            await self.bot.edit_message_reply_markup(
                chat_id=self.chat, message_id=self.cb_msg, reply_markup=kb
            )
        except TelegramAPIError:
            pass

    async def delete(self, message_id: int) -> bool:
        try:
            return bool(await self.bot.delete_message(self.chat, message_id))
        except TelegramAPIError:
            return False

    async def dm(self, chat_id, text: str, kb=None) -> Message | None:
        """A message to somebody else (not tracked in this flow)."""
        try:
            return await self.bot.send_message(chat_id, clip(text, 4096), reply_markup=kb)
        except TelegramAPIError as e:
            logger.warning("dm to %s failed: %s", chat_id, e)
            return None


# ====================================================================== handler wrappers
async def _report_error(ctx: Ctx, e: BackendError) -> None:
    if isinstance(e, BackendDown):
        await ctx.send(DOWN_TEXT)
    elif isinstance(e, ServiceRefusal):
        await ctx.send(f"❗ {esc(e.detail)}")
    elif isinstance(e, (Forbidden, Conflict)):
        await ctx.send(f"ℹ️ {esc(e.detail)}")
    elif isinstance(e, NotFound):
        await ctx.send(f"❗ {esc(e.detail or 'Topilmadi.')}")
    else:  # pragma: no cover - BackendError subclasses are covered above
        await ctx.send(f"❗ {esc(e.detail)}")


async def run(ctx: Ctx, coro) -> Any:
    try:
        return await coro
    except BackendError as e:
        await _report_error(ctx, e)
    except Exception:
        logger.exception("finance handler failed")
        await ctx.send("❗ Xatolik yuz berdi. Birozdan keyin qayta urinib ko'ring.")
    finally:
        await ctx.finish()


def message_handler(fn):
    """`async def fn(ctx, message)` -> aiogram message handler."""

    async def handler(message: Message, state: FSMContext, actor: Actor, bot: Bot):
        ctx = Ctx(bot, actor, state, message.chat.id, msg=message)
        await ctx.load()
        return await run(ctx, fn(ctx, message))

    handler.__name__ = fn.__name__
    return handler


def callback_handler(fn):
    """`async def fn(ctx, data)` -> aiogram callback handler (answers the query first)."""

    async def handler(callback: CallbackQuery, state: FSMContext, actor: Actor, bot: Bot):
        data = callback.data or ""
        try:
            await callback.answer("❌ Bekor qilindi" if data == "cancel" else "")
        except TelegramAPIError:
            pass  # an expired query is fine
        if callback.message is None:
            return None
        ctx = Ctx(bot, actor, state, callback.message.chat.id, cb=callback)
        await ctx.load()
        return await run(ctx, fn(ctx, data))

    handler.__name__ = fn.__name__
    return handler
