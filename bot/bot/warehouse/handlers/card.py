"""Card, gallery, picture cover / delete, edit menu, movement history and its undo."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery

from .. import api
from .. import keyboards as K
from .. import photos as P
from .. import texts as T
from . import util as U

log = logging.getLogger("bot.warehouse.handlers.card")

CARD_RE = re.compile(r"^wh:p:(\d+)$")
GAL_RE = re.compile(r"^wh:g:(\d+)$")
PC_RE = re.compile(r"^wh:pc:(\d+)$")
PD_RE = re.compile(r"^wh:pd:(\d+)$")
PDY_RE = re.compile(r"^wh:pdy:(\d+)$")
EDIT_RE = re.compile(r"^wh:e:(\d+)$")
ACT_RE = re.compile(r"^wh:ea:(\d+)$")
HIST_RE = re.compile(r"^wh:h:(\d+):(\d+)$")
CX_RE = re.compile(r"^wh:cx:(.+)$")
CY_RE = re.compile(r"^wh:cy:(.+)$")


async def fresh_card(cb: CallbackQuery, product: dict, *, drop_old: bool = True) -> None:
    m = cb.message
    await P.show_card(cb.bot, U.chat_id(cb), cb.from_user.id, product, old=m if drop_old else None)


def build() -> Router:
    r = Router(name="warehouse_card")

    @r.callback_query(F.data.regexp(CARD_RE))
    async def open_card(cb: CallbackQuery):
        pid = int(CARD_RE.match(cb.data).group(1))
        try:
            p = (await U.get_product(cb.from_user.id, pid))["product"]
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        await cb.answer()
        await fresh_card(cb, p, drop_old=False)

    @r.callback_query(F.data.regexp(GAL_RE))
    async def gallery(cb: CallbackQuery):
        pid = int(GAL_RE.match(cb.data).group(1))
        try:
            p = (await U.get_product(cb.from_user.id, pid))["product"]
            await cb.answer()
            await P.send_gallery(cb.bot, U.chat_id(cb), cb.from_user.id, p)
        except api.BackendError as e:
            await U.alert(cb, e)
        except TelegramAPIError:
            log.warning("gallery of product %s failed", pid, exc_info=True)

    # ---- cover / delete
    @r.callback_query(F.data.regexp(PC_RE))
    async def cover(cb: CallbackQuery):
        photo = int(PC_RE.match(cb.data).group(1))
        try:
            res = await api.call(
                "POST", f"warehouse/photos/{photo}/cover/", actor=cb.from_user.id, json={}
            )
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        await cb.answer("⭐ Asosiy rasm o'zgartirildi")
        await U.drop_kb(cb)
        await fresh_card(cb, res["product"], drop_old=False)

    @r.callback_query(F.data.regexp(PD_RE))
    async def ask_delete(cb: CallbackQuery):
        photo = int(PD_RE.match(cb.data).group(1))
        await cb.answer()
        await U.edit(cb, T.DELETE_ASK, K.delete_kb(photo))

    @r.callback_query(F.data.regexp(PDY_RE))
    async def delete(cb: CallbackQuery):
        photo = int(PDY_RE.match(cb.data).group(1))
        try:
            res = await api.call("DELETE", f"warehouse/photos/{photo}/", actor=cb.from_user.id)
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        await cb.answer("🗑 O'chirildi")
        await U.drop_kb(cb)
        await fresh_card(cb, res["product"], drop_old=False)

    # ---- edit menu + active toggle
    @r.callback_query(F.data.regexp(EDIT_RE))
    async def edit_menu(cb: CallbackQuery):
        pid = int(EDIT_RE.match(cb.data).group(1))
        try:
            p = (await U.get_product(cb.from_user.id, pid))["product"]
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        await cb.answer()
        await U.drop_kb(cb)
        await cb.message.answer(
            f"✏️ <b>{T.esc(p['name'])}</b> — nimani o'zgartiramiz?", reply_markup=K.edit_kb(p)
        )

    @r.callback_query(F.data.regexp(ACT_RE))
    async def toggle_active(cb: CallbackQuery):
        pid = int(ACT_RE.match(cb.data).group(1))
        uid = cb.from_user.id
        try:
            p = (await U.get_product(uid, pid))["product"]
            res = await api.call(
                "PATCH",
                f"warehouse/products/{pid}/",
                actor=uid,
                json={"is_active": p.get("is_active") is False},
            )
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        await cb.answer(T.SAVED)
        await U.drop_kb(cb)
        await fresh_card(cb, res["product"], drop_old=False)

    # ---- movements
    @r.callback_query(F.data.regexp(HIST_RE))
    async def history(cb: CallbackQuery):
        pid, page = (int(x) for x in HIST_RE.match(cb.data).groups())
        uid = cb.from_user.id
        try:
            p = (await U.get_product(uid, pid))["product"]
            res = await api.call(
                "GET", "warehouse/movements/", actor=uid, params={"product": pid, "page": page}
            )
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        await cb.answer()
        text, kb = T.moves_text(p["name"], res), K.moves_kb(pid, res)
        if cb.message is not None and getattr(cb.message, "photo", None):
            await U.drop_kb(cb)
            await cb.message.answer(text, reply_markup=kb)
        else:
            await U.edit(cb, text, kb)

    @r.callback_query(F.data.regexp(CX_RE))
    async def ask_cancel(cb: CallbackQuery):
        number = CX_RE.match(cb.data).group(1)
        await cb.answer()
        await U.edit(cb, T.CANCEL_ASK.format(n=T.esc(number)), K.cancel_move_kb(number))

    @r.callback_query(F.data.regexp(CY_RE))
    async def do_cancel(cb: CallbackQuery):
        number = CY_RE.match(cb.data).group(1)
        try:
            res = await api.call(
                "POST", f"warehouse/movements/{number}/cancel/", actor=cb.from_user.id, json={}
            )
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        await cb.answer(T.CANCEL_DONE)
        await U.drop_kb(cb)
        await fresh_card(cb, res["product"], drop_old=False)

    return r
