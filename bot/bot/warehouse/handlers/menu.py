"""Menu, search / lists, summary, generic cancel and the «another action is open» gate."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.common.actor import Actor
from bot.common.rds import get_redis
from bot.crm.handlers.lead import CMD_CANCEL

from .. import api
from .. import keyboards as K
from .. import photos as P
from .. import texts as T
from ..states import ALL, WhSearch
from . import util as U

log = logging.getLogger("bot.warehouse.handlers.menu")

MENU_RE = re.compile(r"^(/ombor(@\w+)?\s*|📦 Ombor)$", re.I)
LIST_RE = re.compile(r"^wh:(s|lo|al):(\d+)$")
SUM_RE = re.compile(r"^wh:sm:([dwm])$")
Q_TTL = 3600


async def warehouse_start(message: Message, actor: Actor) -> None:
    """Plain /start of a keeper who is nothing else: reply button + inline menu."""
    await message.answer(T.MENU, reply_markup=K.reply_menu())
    await message.answer("👇", reply_markup=K.menu_kb())


async def list_view(uid: int, kind: str, page: int):
    """(text, keyboard) of a result page, or None when the saved query is gone."""
    params: dict = {"page": page}
    query = ""
    if kind == "s":
        raw = await get_redis().get(f"wh:q:{uid}")
        if not raw:
            return None
        query = raw.decode() if isinstance(raw, bytes) else raw
        params["q"] = query
    elif kind == "lo":
        params["low"] = 1
    res = await api.call("GET", "warehouse/products/", actor=uid, params=params)
    if not res.get("items"):
        return T.NOTHING if kind != "s" else f"🔍 «{T.esc(query)}» — {T.NOTHING}", K.menu_kb()
    return T.list_title(kind, res, query), K.list_kb(kind, res)


async def search(message: Message, uid: int, query: str) -> None:
    await get_redis().set(f"wh:q:{uid}", query, ex=Q_TTL)
    try:
        res = await api.call(
            "GET", "warehouse/products/", actor=uid, params={"q": query, "page": 1}
        )
    except api.BackendError as e:
        await message.answer(api.err_text(e))
        return
    items = res.get("items") or []
    if len(items) == 1 and res.get("total", 1) == 1:
        try:
            p = (await U.get_product(uid, items[0]["id"]))["product"]
        except api.BackendError as e:
            await message.answer(api.err_text(e))
            return
        await P.show_card(message.bot, message.chat.id, uid, p)
        return
    if not items:
        await message.answer(f"🔍 «{T.esc(query)}» — {T.NOTHING}", reply_markup=K.menu_kb())
        return
    await message.answer(T.list_title("s", res, query), reply_markup=K.list_kb("s", res))


def build() -> Router:
    r = Router(name="warehouse_menu")

    # ---- a wh: button while another module's flow is open
    async def other_flow(cb: CallbackQuery, state: FSMContext) -> bool:
        cur = await state.get_state()
        return cur is not None and not U.is_wh_state(cur)

    @r.callback_query(F.data.startswith("wh:"), other_flow)
    async def busy(cb: CallbackQuery):
        await cb.answer(T.BUSY, show_alert=True)

    # ---- menu (also leaves any open flow)
    @r.message(F.text.regexp(MENU_RE))
    async def open_menu(message: Message, state: FSMContext, actor: Actor):
        await U.clear(state)
        if actor.member is None and not actor.employee and not actor.can_add_lead:
            await warehouse_start(message, actor)
        else:
            await message.answer(T.MENU, reply_markup=K.menu_kb())

    @r.callback_query(F.data == K.MENU_CB)
    async def menu_cb(cb: CallbackQuery, state: FSMContext):
        await U.clear(state)
        await cb.answer()
        await U.edit(cb, T.MENU, K.menu_kb())

    # ---- cancel (button and /bekor)
    @r.message(F.text.regexp(CMD_CANCEL), StateFilter(*ALL))
    async def cancel_cmd(message: Message, state: FSMContext):
        await U.clear(state)
        await message.answer(T.CANCELLED)

    @r.callback_query(F.data == "wh:x")
    async def cancel_cb(cb: CallbackQuery, state: FSMContext):
        cur = await state.get_state()
        if U.is_wh_state(cur):
            await U.clear(state)
        await cb.answer(T.CANCELLED)
        await U.drop_kb(cb)

    # ---- search
    @r.callback_query(F.data == "wh:q")
    async def ask_query(cb: CallbackQuery, state: FSMContext):
        await U.begin(state, WhSearch.query)
        await cb.answer()
        await U.edit(cb, T.ASK_QUERY, K.cancel_kb())

    @r.message(StateFilter(WhSearch.query), F.text & ~F.text.startswith("/"))
    async def got_query(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, _ = gate
        if not text:
            return
        await U.clear(state)
        await search(message, message.from_user.id, text[:100])

    # ---- lists
    @r.callback_query(F.data.regexp(LIST_RE))
    async def lists(cb: CallbackQuery):
        kind, page = LIST_RE.match(cb.data).groups()
        try:
            view = await list_view(cb.from_user.id, kind, int(page))
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        if view is None:
            await cb.answer(T.QUERY_GONE, show_alert=True)
            return
        await cb.answer()
        await U.edit(cb, *view)

    # ---- summary
    @r.callback_query(F.data.regexp(SUM_RE))
    async def summary(cb: CallbackQuery):
        code = SUM_RE.match(cb.data).group(1)
        try:
            s = await api.call(
                "GET",
                "warehouse/summary/",
                actor=cb.from_user.id,
                params={"period": api.PERIODS[code]},
            )
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        await cb.answer()
        await U.edit(cb, T.summary_text(s), K.summary_kb())

    return r
