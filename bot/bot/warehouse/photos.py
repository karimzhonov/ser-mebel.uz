"""Product cards and galleries with pictures. A picture is sent by its cached Telegram
`file_id` (WhPhoto.tg_file_id); when there is none or Telegram refuses it, the main file
is fetched from the backend, sent as bytes and the new file_id is cached back (a cache
only: the backend file is the truth)."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import BufferedInputFile, InputMediaPhoto, Message

from bot.common.rds import get_redis

from . import api
from . import keyboards as K
from . import texts as T

log = logging.getLogger("bot.warehouse.photos")

CUR_TTL = 1800


async def set_current(tg_id: int, pid: int) -> None:
    await get_redis().set(f"wh:cur:{tg_id}", str(pid), ex=CUR_TTL)


async def current(tg_id: int) -> int | None:
    raw = await get_redis().get(f"wh:cur:{tg_id}")
    if raw is None:
        return None
    try:
        return int(raw.decode() if isinstance(raw, bytes) else raw)
    except ValueError:
        return None


async def _cache(actor: int, photo_id: int, msg: Message | None) -> None:
    if msg is None or not msg.photo:
        return
    try:
        await api.cache_file_id(actor, photo_id, msg.photo[-1].file_id)
    except api.BackendError as e:
        log.info("tg-file cache failed for photo %s: %s", photo_id, e)


async def _bytes_input(actor: int, photo: dict) -> BufferedInputFile:
    data = await api.photo_bytes(actor, photo["id"])
    return BufferedInputFile(data, filename=f"{photo['id']}.jpg")


async def show_card(bot: Bot, chat_id: int, actor: int, product: dict, old: Message | None = None):
    """Send a fresh product card (cover + caption + buttons) and drop the old card's buttons."""
    await set_current(actor, int(product["id"]))
    if old is not None:
        try:
            await old.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
    text, kb = T.card(product), K.card_kb(product)
    cover = product.get("cover")
    if not cover:
        return await bot.send_message(chat_id, text, reply_markup=kb)
    fid = cover.get("tg_file_id") or ""
    if fid:
        try:
            return await bot.send_photo(chat_id, fid, caption=text, reply_markup=kb)
        except TelegramBadRequest:
            log.info("cached file_id of photo %s refused, re-uploading", cover["id"])
    try:
        msg = await bot.send_photo(
            chat_id, await _bytes_input(actor, cover), caption=text, reply_markup=kb
        )
    except (api.BackendError, TelegramAPIError) as e:
        log.warning("could not send the cover of product %s: %s", product["id"], e)
        return await bot.send_message(chat_id, text, reply_markup=kb)
    await _cache(actor, cover["id"], msg)
    return msg


async def send_gallery(bot: Bot, chat_id: int, actor: int, product: dict):
    """All pictures of the product (1: photo, 2-5: album), then the ⭐/🗑 buttons."""
    photos = product.get("photos") or []
    if not photos:
        await bot.send_message(chat_id, "Rasm yo'q.", reply_markup=K.card_kb(product))
        return
    await set_current(actor, int(product["id"]))
    name = T.esc(T.cut(product.get("name") or "", 200))
    if len(photos) == 1:
        ph = photos[0]
        msg = None
        if ph.get("tg_file_id"):
            try:
                msg = await bot.send_photo(chat_id, ph["tg_file_id"], caption=name)
            except TelegramBadRequest:
                msg = None
        if msg is None:
            msg = await bot.send_photo(chat_id, await _bytes_input(actor, ph), caption=name)
            await _cache(actor, ph["id"], msg)
    else:
        msgs = None
        if all(p.get("tg_file_id") for p in photos):
            try:
                msgs = await bot.send_media_group(
                    chat_id, [InputMediaPhoto(media=p["tg_file_id"]) for p in photos]
                )
            except TelegramBadRequest:
                msgs = None
        if msgs is None:
            media = [InputMediaPhoto(media=await _bytes_input(actor, p)) for p in photos]
            msgs = await bot.send_media_group(chat_id, media)
            for p, m in zip(photos, msgs):
                await _cache(actor, p["id"], m)
    await bot.send_message(
        chat_id,
        f"🖼 <b>{name}</b> — rasmlar: {len(photos)}",
        reply_markup=K.gallery_kb(photos, product["id"]),
    )
