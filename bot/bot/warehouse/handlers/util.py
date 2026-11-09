"""Shared helpers of the warehouse handlers: staleness gate, menu pass-through, alerts."""

from __future__ import annotations

import logging
import time

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.crm.texts import NEW_BTN
from bot.hr.texts import FINANCE_MENU_BUTTONS

from .. import api
from .. import texts as T

log = logging.getLogger("bot.warehouse.handlers")

TTL = 1800  # seconds a flow stays valid


def is_wh_state(cur: str | None) -> bool:
    return bool(cur) and cur.startswith("Wh")


FLOW_KEY = "_flow"  # finance's own FSM key: never wipe it


async def clear(state: FSMContext) -> None:
    """state.clear() that keeps finance's `_flow` draft marker."""
    flow = (await state.get_data()).get(FLOW_KEY)
    await state.clear()
    if flow is not None:
        await state.set_data({FLOW_KEY: flow})


async def begin(state: FSMContext, target, **data) -> None:
    flow = (await state.get_data()).get(FLOW_KEY)
    await state.set_state(target)
    keep = {FLOW_KEY: flow} if flow is not None else {}
    await state.set_data({**keep, **data, "ts": time.time()})


async def update(state: FSMContext, target=None, **data) -> dict:
    """Merge into the FSM data (refreshes ts) and optionally move to `target`."""
    d = await state.get_data()
    d.update(data)
    d["ts"] = time.time()
    await state.set_data(d)
    if target is not None:
        await state.set_state(target)
    return d


async def fresh_data(state: FSMContext) -> dict | None:
    """FSM data, or None (state cleared) when the flow is older than TTL."""
    d = await state.get_data()
    ts = d.get("ts")
    if not isinstance(ts, (int, float)) or time.time() - ts > TTL:
        await clear(state)
        return None
    return d


async def text_gate(message: Message, state: FSMContext) -> tuple[str, dict] | None:
    """For a typed answer: pass through a tap on another menu button (clears the flow and
    raises SkipHandler), answer when stale; otherwise (text, data)."""
    text = (message.text or "").strip()
    if (text in FINANCE_MENU_BUTTONS or text == NEW_BTN) and text != T.MENU_BTN:
        await clear(state)
        raise SkipHandler
    d = await fresh_data(state)
    if d is None:
        await message.answer(T.STALE)
        return None
    return text, d


async def cb_gate(cb: CallbackQuery, state: FSMContext) -> dict | None:
    d = await fresh_data(state)
    if d is None:
        await cb.answer(T.STALE, show_alert=True)
    return d


async def alert(cb: CallbackQuery, e: api.BackendError) -> None:
    await cb.answer(api.err_text(e).removeprefix("❗ ")[:200], show_alert=True)


async def drop_kb(cb: CallbackQuery) -> None:
    m = cb.message
    if isinstance(m, Message):
        try:
            await m.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass


async def edit(cb: CallbackQuery, text: str, markup=None) -> None:
    """Edit the pressed message (text or caption); a photo card gets a new message."""
    m = cb.message
    if not isinstance(m, Message):
        return
    try:
        if m.photo:
            await m.answer(text, reply_markup=markup)
        else:
            await m.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            log.info("edit failed: %s", e)
    except TelegramAPIError:
        log.info("edit failed", exc_info=True)


async def get_product(uid: int, pid: int) -> dict:
    res = await api.call("GET", f"warehouse/products/{pid}/", actor=uid)
    return res


def chat_id(cb: CallbackQuery) -> int:
    m = cb.message
    return m.chat.id if isinstance(m, Message) else cb.from_user.id
