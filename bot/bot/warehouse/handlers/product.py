"""«Yangi mahsulot» (name -> unit -> type -> code -> min stock -> create -> pictures) and the
edit of one field of an existing product."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api
from .. import keyboards as K
from .. import photos as P
from .. import texts as T
from ..parse import parse_qty
from ..states import WhEdit, WhNew, WhPhoto
from . import util as U

log = logging.getLogger("bot.warehouse.handlers.product")

TXT = F.text & ~F.text.startswith("/")
UN_RE = re.compile(r"^wh:un:(.+)$")
CT_RE = re.compile(r"^wh:ct:(\d+)$")
EF_RE = re.compile(r"^wh:ef:([nctum]):(\d+)$")
EU_RE = re.compile(r"^wh:eu:(.+):(\d+)$")
FIELD = {"n": "name", "c": "code", "t": "category", "m": "min_quantity"}
EDIT_ASK = {
    "n": T.ASK_EDIT_NAME,
    "c": T.ASK_EDIT_CODE,
    "t": T.ASK_EDIT_CATEGORY,
    "m": T.ASK_EDIT_MIN,
}
# the step to go back to for a 400 on a field
NEW_STEP = {
    "name": (WhNew.name, T.ASK_NAME),
    "code": (WhNew.code, T.ASK_CODE),
    "min_quantity": (WhNew.min_qty, T.ASK_MIN),
}


def build() -> Router:
    r = Router(name="warehouse_product")

    # ================================================================ new product
    @r.callback_query(F.data == "wh:n")
    async def start_new(cb: CallbackQuery, state: FSMContext):
        uid = cb.from_user.id
        try:
            meta = await api.call("GET", "warehouse/meta/", actor=uid)
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        await U.begin(
            state,
            WhNew.name,
            units=meta.get("units") or [],
            cats=(meta.get("categories") or [])[:40],
            body={},
        )
        await cb.answer()
        await U.edit(cb, T.ASK_NAME, K.cancel_kb())

    @r.message(StateFilter(WhNew.name), TXT)
    async def new_name(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, d = gate
        if not text:
            return
        await U.update(state, WhNew.unit, body={**d["body"], "name": text[:200]})
        await message.answer(T.ASK_UNIT, reply_markup=K.units_kb(d["units"]))

    @r.message(StateFilter(WhNew.unit), TXT)
    async def new_unit_text(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        _, d = gate
        await message.answer(T.ASK_UNIT, reply_markup=K.units_kb(d["units"]))

    async def _ask_category(target, d: dict) -> None:
        await target.answer(T.ASK_CATEGORY, reply_markup=K.categories_kb(d["cats"]))

    @r.callback_query(F.data.regexp(UN_RE), StateFilter(WhNew.unit))
    async def new_unit(cb: CallbackQuery, state: FSMContext):
        d = await U.cb_gate(cb, state)
        if d is None:
            return
        unit = UN_RE.match(cb.data).group(1)
        d = await U.update(state, WhNew.category, body={**d["body"], "unit": unit})
        await cb.answer()
        await U.drop_kb(cb)
        await _ask_category(cb.message, d)

    @r.message(StateFilter(WhNew.category), TXT)
    async def new_category_text(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, d = gate
        await U.update(state, WhNew.code, body={**d["body"], "category": text[:100]})
        await message.answer(T.ASK_CODE, reply_markup=K.skip_kb())

    @r.callback_query(F.data.regexp(CT_RE), StateFilter(WhNew.category))
    async def new_category_pick(cb: CallbackQuery, state: FSMContext):
        d = await U.cb_gate(cb, state)
        if d is None:
            return
        idx = int(CT_RE.match(cb.data).group(1))
        if idx >= len(d["cats"]):
            await cb.answer(T.GONE, show_alert=True)
            return
        await U.update(state, WhNew.code, body={**d["body"], "category": d["cats"][idx]})
        await cb.answer()
        await U.drop_kb(cb)
        await cb.message.answer(T.ASK_CODE, reply_markup=K.skip_kb())

    @r.message(StateFilter(WhNew.code), TXT)
    async def new_code(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, d = gate
        await U.update(state, WhNew.min_qty, body={**d["body"], "code": text[:50]})
        await message.answer(T.ASK_MIN, reply_markup=K.skip_kb())

    @r.message(StateFilter(WhNew.min_qty), TXT)
    async def new_min(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, d = gate
        qty = parse_qty(text, allow_zero=True)
        if qty is None:
            await message.answer(T.BAD_MIN, reply_markup=K.skip_kb())
            return
        body = {**d["body"], "min_quantity": str(qty)}
        await U.update(state, body=body)
        await _create(message, state, message.from_user.id, body)

    @r.callback_query(F.data == "wh:sk", StateFilter(WhNew.category, WhNew.code, WhNew.min_qty))
    async def new_skip(cb: CallbackQuery, state: FSMContext):
        d = await U.cb_gate(cb, state)
        if d is None:
            return
        cur = await state.get_state()
        await cb.answer()
        await U.drop_kb(cb)
        if cur == WhNew.category.state:
            await U.update(state, WhNew.code)
            await cb.message.answer(T.ASK_CODE, reply_markup=K.skip_kb())
        elif cur == WhNew.code.state:
            await U.update(state, WhNew.min_qty)
            await cb.message.answer(T.ASK_MIN, reply_markup=K.skip_kb())
        else:
            await _create(cb.message, state, cb.from_user.id, d["body"])

    async def _create(target: Message, state: FSMContext, uid: int, body: dict) -> None:
        try:
            res = await api.call("POST", "warehouse/products/", actor=uid, json=body)
        except api.BackendError as e:
            log.info("product create failed for %s: %s", uid, e)
            step = NEW_STEP.get(e.field) if isinstance(e, api.ServiceRefusal) else None
            if step is not None:
                await U.update(state, step[0])
                await target.answer(f"{api.err_text(e)}\n\n{step[1]}", reply_markup=K.skip_kb())
                return
            if isinstance(e, api.ServiceRefusal) and e.field == "unit":
                d = await U.update(state, WhNew.unit)
                await target.answer(
                    f"{api.err_text(e)}\n\n{T.ASK_UNIT}", reply_markup=K.units_kb(d["units"])
                )
                return
            await U.clear(state)
            await target.answer(api.err_text(e))
            return
        p = res["product"]
        await U.begin(state, WhPhoto.wait, pid=p["id"], new=True, count=0)
        await P.set_current(uid, int(p["id"]))
        await target.answer(
            f"✅ «{T.esc(p['name'])}» qo'shildi.\n\n{T.ASK_PHOTO}", reply_markup=K.photo_new_kb()
        )

    # ================================================================ edit one field
    @r.callback_query(F.data.regexp(EF_RE))
    async def edit_field(cb: CallbackQuery, state: FSMContext):
        key, pid = EF_RE.match(cb.data).groups()
        uid = cb.from_user.id
        cur = await state.get_state()
        if cur is not None and not U.is_wh_state(cur):
            await cb.answer(T.BUSY, show_alert=True)
            return
        if key == "u":
            try:
                meta = await api.call("GET", "warehouse/meta/", actor=uid)
            except api.BackendError as e:
                await U.alert(cb, e)
                return
            await cb.answer()
            await U.drop_kb(cb)
            await cb.message.answer(
                T.ASK_EDIT_UNIT,
                reply_markup=K.units_kb(meta.get("units") or [], "wh:eu:", f":{pid}"),
            )
            return
        await U.begin(state, WhEdit.value, pid=int(pid), field=FIELD[key])
        await cb.answer()
        await U.drop_kb(cb)
        await cb.message.answer(EDIT_ASK[key], reply_markup=K.cancel_kb())

    async def _patch(target: Message, uid: int, pid: int, body: dict) -> dict | None:
        try:
            res = await api.call("PATCH", f"warehouse/products/{pid}/", actor=uid, json=body)
        except api.BackendError as e:
            await target.answer(api.err_text(e))
            return None
        return res["product"]

    @r.callback_query(F.data.regexp(EU_RE))
    async def set_unit(cb: CallbackQuery):
        unit, pid = EU_RE.match(cb.data).groups()
        await cb.answer()
        await U.drop_kb(cb)
        p = await _patch(cb.message, cb.from_user.id, int(pid), {"unit": unit})
        if p:
            await P.show_card(cb.bot, U.chat_id(cb), cb.from_user.id, p)

    @r.message(StateFilter(WhEdit.value), TXT)
    async def edit_value(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, d = gate
        field = d["field"]
        if field == "min_quantity":
            qty = parse_qty(text, allow_zero=True)
            if qty is None:
                await message.answer(T.BAD_MIN, reply_markup=K.cancel_kb())
                return
            value = str(qty)
        elif field in ("code", "category") and text in ("-", "—"):
            value = ""
        else:
            value = text[:200]
        uid = message.from_user.id
        try:
            res = await api.call(
                "PATCH", f"warehouse/products/{d['pid']}/", actor=uid, json={field: value}
            )
        except api.BackendError as e:
            log.info("product edit failed for %s: %s", uid, e)
            if isinstance(e, api.ServiceRefusal) and e.field in (field, ""):
                await message.answer(api.err_text(e), reply_markup=K.cancel_kb())
                return
            await U.clear(state)
            await message.answer(api.err_text(e))
            return
        await U.clear(state)
        await message.answer(T.SAVED)
        await P.show_card(message.bot, message.chat.id, uid, res["product"])

    return r
