"""Pictures: «📷 Rasm qo'shish» (WhPhoto.wait), the offer to attach a stray photo, and the
upload to the backend (which re-encodes and enforces the limits)."""

from __future__ import annotations

import logging
import re

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.common.rds import get_redis

from .. import api
from .. import keyboards as K
from .. import photos as P
from .. import texts as T
from ..states import WhPhoto
from . import util as U

log = logging.getLogger("bot.warehouse.handlers.photo")

PH_RE = re.compile(r"^wh:ph:(\d+)$")
AT_RE = re.compile(r"^wh:at:(\d+)$")
MAX_BYTES = 10 * 1024 * 1024
MIME_OK = {"image/jpeg", "image/png", "image/webp"}
PEND_TTL = 600
IMAGE = F.photo | (F.document & F.document.mime_type.startswith("image/"))


async def download(bot: Bot, file_id: str) -> bytes:
    buf = await bot.download(file_id)
    return buf.read() if buf is not None else b""


async def upload(bot: Bot, uid: int, pid: int, file_id: str, cache_id: str | None) -> dict:
    """Download from Telegram and hand to the backend. Returns its answer."""
    content = await download(bot, file_id)
    return await api.upload_photo(uid, pid, content, cache_id)


def build() -> Router:
    r = Router(name="warehouse_photo")

    # ---- start from a card
    @r.callback_query(F.data.regexp(PH_RE))
    async def start_photo(cb: CallbackQuery, state: FSMContext):
        pid = int(PH_RE.match(cb.data).group(1))
        cur = await state.get_state()
        if cur is not None and not U.is_wh_state(cur):
            await cb.answer(T.BUSY, show_alert=True)
            return
        try:
            p = (await U.get_product(cb.from_user.id, pid))["product"]
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        n = int(p.get("photos_count") or 0)
        if n >= T.MAX_PHOTOS:
            await cb.answer(T.LIMIT.format(n=T.MAX_PHOTOS), show_alert=True)
            return
        await U.begin(state, WhPhoto.wait, pid=pid, new=False, count=n)
        await cb.answer()
        await U.drop_kb(cb)
        await cb.message.answer(T.ASK_PHOTO, reply_markup=K.photo_kb())

    # ---- pictures in the state
    @r.message(StateFilter(WhPhoto.wait), IMAGE)
    async def got_photo(message: Message, state: FSMContext):
        d = await U.fresh_data(state)
        if d is None:
            await message.answer(T.STALE)
            return
        uid = message.from_user.id
        if message.photo:
            fid = message.photo[-1].file_id
            cache_id = fid
        else:
            doc = message.document
            if doc.mime_type not in MIME_OK:
                await message.answer(T.PHOTO_BAD)
                return
            if (doc.file_size or 0) > MAX_BYTES:
                await message.answer(T.PHOTO_BIG)
                return
            fid, cache_id = doc.file_id, None
        try:
            res = await upload(message.bot, uid, d["pid"], fid, cache_id)
        except api.BackendError as e:
            log.info("photo upload failed for %s: %s", uid, e)
            await message.answer(api.err_text(e))
            return
        except TelegramAPIError:
            log.warning("photo download failed for %s", uid, exc_info=True)
            await message.answer(T.PHOTO_FAIL)
            return
        product = res["product"]
        n = int(product.get("photos_count") or len(product.get("photos") or []))
        await U.update(state, count=n)
        if n >= T.MAX_PHOTOS:
            await U.clear(state)
            if message.media_group_id:
                await get_redis().set(f"wh:mg:{uid}", message.media_group_id, ex=60)
            await message.answer(T.photo_added(n))
            await P.show_card(message.bot, message.chat.id, uid, product)
            return
        await message.answer(T.photo_added(n), reply_markup=K.photo_kb())

    @r.message(StateFilter(WhPhoto.wait), F.text & ~F.text.startswith("/"))
    async def photo_text(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        await message.answer(T.PHOTO_ONLY, reply_markup=K.photo_kb())

    @r.message(StateFilter(WhPhoto.wait))
    async def photo_other(message: Message, state: FSMContext):
        if message.text and message.text.startswith("/"):
            raise SkipHandler
        await message.answer(T.PHOTO_ONLY, reply_markup=K.photo_kb())

    @r.callback_query(F.data.in_({"wh:ok:ph", "wh:sk"}), StateFilter(WhPhoto.wait))
    async def photo_done(cb: CallbackQuery, state: FSMContext):
        d = await U.cb_gate(cb, state)
        if d is None:
            return
        await U.clear(state)
        await cb.answer()
        await U.drop_kb(cb)
        try:
            p = (await U.get_product(cb.from_user.id, d["pid"]))["product"]
        except api.BackendError as e:
            await cb.message.answer(api.err_text(e))
            return
        await P.show_card(cb.bot, U.chat_id(cb), cb.from_user.id, p)

    # ---- a stray photo (fallback router): offer + answer
    @r.callback_query(F.data.regexp(AT_RE))
    async def attach_yes(cb: CallbackQuery):
        pid = int(AT_RE.match(cb.data).group(1))
        uid = cb.from_user.id
        rds = get_redis()
        raw = await rds.get(f"wh:pend:{uid}")
        if not raw:
            await cb.answer(T.GONE, show_alert=True)
            await U.drop_kb(cb)
            return
        fid = raw.decode() if isinstance(raw, bytes) else raw
        await cb.answer()
        await U.drop_kb(cb)
        try:
            res = await upload(cb.bot, uid, pid, fid, fid)
        except api.BackendError as e:
            await cb.message.answer(api.err_text(e))
            return
        except TelegramAPIError:
            log.warning("pending photo download failed for %s", uid, exc_info=True)
            await cb.message.answer(T.PHOTO_FAIL)
            return
        await rds.delete(f"wh:pend:{uid}")
        product = res["product"]
        await cb.message.answer(T.photo_added(int(product.get("photos_count") or 0)))
        await P.show_card(cb.bot, U.chat_id(cb), uid, product)

    # ---- the rest of an album whose 5th picture already closed the flow: swallow it
    @r.message(F.photo, F.media_group_id, StateFilter(None))
    async def album_tail(message: Message):
        uid = message.from_user.id
        rds = get_redis()
        raw = await rds.get(f"wh:mg:{uid}")
        if (
            raw is None
            or (raw.decode() if isinstance(raw, bytes) else raw) != message.media_group_id
        ):
            raise SkipHandler
        if await rds.set(f"wh:mga:{uid}", "1", ex=60, nx=True):
            await message.answer(T.LIMIT.format(n=T.MAX_PHOTOS))

    @r.callback_query(F.data == "wh:atn")
    async def attach_no(cb: CallbackQuery):
        await get_redis().delete(f"wh:pend:{cb.from_user.id}")
        await cb.answer(T.CANCELLED)
        await U.drop_kb(cb)

    return r
