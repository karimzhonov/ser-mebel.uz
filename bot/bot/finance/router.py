"""The finance Router: every private message and every button that the HR router did not
take. Strangers and blocked members get no reply (only «✅ Ro'yxatdan o'tish» works for
a stranger); the `/start` and `/moliya` screens live in bot.common.start.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.common.actor import Actor
from bot.finance.ctx import callback_handler, message_handler
from bot.finance.handlers import callbacks as CB
from bot.finance.handlers import menu as MN

logger = logging.getLogger(__name__)


def _is_member(event, actor: Actor | None = None) -> bool:
    return bool(actor and actor.member and not actor.blocked)


def _may_press(callback: CallbackQuery, actor: Actor | None = None) -> bool:
    if callback.data == "join":
        return True
    return _is_member(callback, actor)


def make_router() -> Router:
    r = Router(name="finance")
    r.message.filter(F.chat.type == "private", _is_member)

    @r.message(F.text.startswith("/"))
    @message_handler
    async def command(ctx, message: Message):
        await MN.on_command(ctx, message.text.strip())

    @r.message(F.text)
    @message_handler
    async def text(ctx, message: Message):
        await MN.on_text(ctx, message.text.strip())

    @r.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
    @message_handler
    async def photo(ctx, message: Message):
        fid = message.photo[-1].file_id if message.photo else message.document.file_id
        await MN.on_photo(ctx, fid, message.caption or "")

    @r.callback_query(F.message.chat.type == "private", _may_press)
    @callback_handler
    async def button(ctx, data: str):
        await CB.on_callback(ctx, data)

    @r.callback_query()
    async def stale(callback: CallbackQuery):
        # a button of a stranger / blocked member / group: just stop the spinner
        try:
            await callback.answer()
        except Exception:  # noqa: BLE001 - an expired query is fine
            pass

    return r


router = make_router()
