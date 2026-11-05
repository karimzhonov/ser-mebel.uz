"""Buttons under the zamer card: «✅ O'lchov oldim» (asks to confirm), «🕒 Vaqtni
o'zgartirish» (presets or a typed time) and «❌ Bekor bo'ldi» (asks the reason). They work
for the person the backend links to this Telegram account; the backend says 403 (not your
zamer / not linked), 409 (already marked) or 400 and we show it as an alert / re-ask.

Stateless except the two typed answers (FSM `MeterTime:custom`, `MeterCancel:reason`, 10 min
TTL). No files here: photos / videos / PDFs are uploaded on the site only."""

from __future__ import annotations

import logging
import re
import time

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.crm.handlers.lead import CMD_CANCEL
from bot.crm.texts import NEW_BTN
from bot.hr.texts import FINANCE_MENU_BUTTONS

from . import api
from . import keyboards as K
from . import texts as T
from .states import MeterCancel, MeterTime

log = logging.getLogger("bot.metering.handlers")

TTL = 600  # seconds a typed-answer prompt stays valid
PRESETS = {"1h": "1h", "tm": "tomorrow", "2d": "2d"}
MS_RE = re.compile(r"^mt:ms:(\d+)$")
MSY_RE = re.compile(r"^mt:msy:(\d+)$")
RS_RE = re.compile(r"^mt:rs:(\d+)$")
RP_RE = re.compile(r"^mt:rp:(1h|tm|2d):(\d+)$")
RC_RE = re.compile(r"^mt:rc:(\d+)$")
CN_RE = re.compile(r"^mt:cn:(\d+)$")
BK_RE = re.compile(r"^mt:bk:(\d+)$")


def _links(cb: CallbackQuery) -> tuple[str, str]:
    """(site url, map url) of the message's own keyboard, so intermediate screens keep them."""
    url = map_url = ""
    m = cb.message
    if isinstance(m, Message) and m.reply_markup:
        for row in m.reply_markup.inline_keyboard:
            for btn in row:
                if btn.url and btn.text == K.OPEN_PANEL:
                    url = btn.url
                elif btn.url and btn.text == K.MAP_BTN:
                    map_url = btn.url
    return url, map_url


async def _set_kb(cb: CallbackQuery, markup) -> None:
    m = cb.message
    if not isinstance(m, Message):
        return
    try:
        await m.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            log.info("edit markup failed: %s", e)
    except TelegramAPIError:
        log.info("edit markup failed", exc_info=True)


async def _alert(cb: CallbackQuery, e: api.BackendError) -> None:
    text = api.err_text(e).removeprefix("❗ ")
    await cb.answer(text[:200], show_alert=True)


async def _show(cb: CallbackQuery, brief: dict, *, how: str | None = None, url: str = "") -> None:
    """Re-render the pressed card from the backend's MeteringBrief."""
    m = cb.message
    if not isinstance(m, Message):
        return
    kind = T.kind_of(m.text)
    brief = dict(brief)
    if url and not brief.get("url"):
        brief["url"] = url
    try:
        await m.edit_text(
            T.card(brief, kind, how=how),
            reply_markup=_kb(brief),
        )
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            log.info("edit failed: %s", e)
    except TelegramAPIError:
        log.info("edit failed", exc_info=True)


def _kb(brief: dict):
    return K.card_kb(
        int(brief["id"]),
        brief.get("status") or "",
        brief.get("url") or "",
        brief.get("map_url") or "",
    )


async def _drop_typed(state: FSMContext, metering_id: int) -> None:
    cur = await state.get_state()
    if cur and cur.startswith("Meter"):
        if (await state.get_data()).get("metering") == metering_id:
            await state.clear()


def build() -> Router:
    r = Router(name="metering_buttons")

    # ---- «O'lchov oldim»
    @r.callback_query(F.data.regexp(MS_RE))
    async def ask_measured(cb: CallbackQuery):
        mid = int(MS_RE.match(cb.data).group(1))
        url, map_url = _links(cb)
        await _set_kb(cb, K.confirm_kb(mid, url, map_url))
        await cb.answer(T.CONFIRM_ASK)

    @r.callback_query(F.data.regexp(MSY_RE))
    async def measured(cb: CallbackQuery, state: FSMContext):
        mid = int(MSY_RE.match(cb.data).group(1))
        try:
            res = await api.call("POST", f"meterings/{mid}/measured/", actor=cb.from_user.id)
        except api.BackendError as e:
            await _alert(cb, e)
            return
        await _drop_typed(state, mid)
        await cb.answer()
        res = res or {}
        await _show(cb, res.get("metering") or {"id": mid}, url=res.get("url") or "")

    # ---- «Vaqtni o'zgartirish»
    @r.callback_query(F.data.regexp(RS_RE))
    async def reschedule_menu(cb: CallbackQuery):
        mid = int(RS_RE.match(cb.data).group(1))
        url, map_url = _links(cb)
        await _set_kb(cb, K.resched_kb(mid, url, map_url))
        await cb.answer(T.PICK_TIME)

    @r.callback_query(F.data.regexp(RP_RE))
    async def preset(cb: CallbackQuery, state: FSMContext):
        code, tid = RP_RE.match(cb.data).groups()
        mid = int(tid)
        try:
            res = await api.call(
                "POST",
                f"meterings/{mid}/reschedule/",
                actor=cb.from_user.id,
                json={"preset": PRESETS[code]},
            )
        except api.BackendError as e:
            await _alert(cb, e)
            return
        await _drop_typed(state, mid)
        await cb.answer(T.SAVED_OK)
        await _show(cb, (res or {}).get("metering") or {"id": mid}, how="rescheduled")

    @r.callback_query(F.data.regexp(BK_RE))
    async def back(cb: CallbackQuery, state: FSMContext):
        mid = int(BK_RE.match(cb.data).group(1))
        await _drop_typed(state, mid)
        url, map_url = _links(cb)
        # "Orqaga" exists only on confirm_kb / resched_kb, and those are shown only from an
        # open card (created / other_day), so restoring the open keyboard is correct.
        await _set_kb(cb, K.card_kb(mid, "created", url, map_url))
        await cb.answer()

    async def _ask(cb: CallbackQuery, state: FSMContext, mid: int, target, prompt: str) -> None:
        cur = await state.get_state()
        if cur is not None and not cur.startswith("Meter"):
            await cb.answer(T.BUSY, show_alert=True)
            return
        m = cb.message
        if not isinstance(m, Message):
            await cb.answer(T.STALE)
            return
        await state.set_state(target)
        await state.set_data(
            {
                "metering": mid,
                "chat_id": m.chat.id,
                "message_id": m.message_id,
                "kind": T.kind_of(m.text),
                "ts": time.time(),
            }
        )
        await cb.answer()
        await m.answer(prompt, reply_markup=K.cancel_kb())

    @r.callback_query(F.data.regexp(RC_RE))
    async def ask_time(cb: CallbackQuery, state: FSMContext):
        mid = int(RC_RE.match(cb.data).group(1))
        await _ask(cb, state, mid, MeterTime.custom, T.ASK_TIME)

    # ---- «Bekor bo'ldi»
    @r.callback_query(F.data.regexp(CN_RE))
    async def ask_reason(cb: CallbackQuery, state: FSMContext):
        mid = int(CN_RE.match(cb.data).group(1))
        await _ask(cb, state, mid, MeterCancel.reason, T.ASK_REASON)

    @r.callback_query(F.data == "mt:q")
    async def cancel_typed(cb: CallbackQuery, state: FSMContext):
        cur = await state.get_state()
        if cur and cur.startswith("Meter"):
            await state.clear()
        await cb.answer(T.CANCELLED)
        await _set_kb(cb, None)

    # ---- typed answers
    typed = StateFilter(MeterTime.custom, MeterCancel.reason)

    @r.message(F.text.regexp(CMD_CANCEL), typed)
    async def typed_cancel(message: Message, state: FSMContext):
        await state.clear()
        await message.answer(T.CANCELLED)

    @r.message(F.text & ~F.text.startswith("/") & ~F.forward_origin, typed)
    async def typed_answer(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if text in FINANCE_MENU_BUTTONS or text == NEW_BTN:
            await state.clear()
            raise SkipHandler
        d = await state.get_data()
        ts = d.get("ts")
        if not isinstance(ts, (int, float)) or time.time() - ts > TTL:
            await state.clear()
            await message.answer(T.STALE)
            return
        is_time = (await state.get_state()) == MeterTime.custom.state
        uid = message.from_user.id
        mid = int(d.get("metering"))
        again = "\n\n" + (T.ASK_TIME if is_time else T.ASK_REASON)
        path, body, field = (
            (f"meterings/{mid}/reschedule/", {"text": text}, "time")
            if is_time
            else (f"meterings/{mid}/cancel/", {"reason": text}, "reason")
        )
        try:
            res = await api.call("POST", path, actor=uid, json=body)
        except api.BackendError as e:
            log.info("typed metering answer failed for %s: %s", uid, e)
            if isinstance(e, api.ServiceRefusal) and e.field == field:
                await message.answer(api.err_text(e) + again, reply_markup=K.cancel_kb())
                return
            await state.clear()
            await message.answer(api.err_text(e))
            return
        await state.clear()
        brief = (res or {}).get("metering") or {"id": mid}
        try:
            await message.bot.edit_message_text(
                chat_id=d.get("chat_id"),
                message_id=d.get("message_id"),
                text=T.card(
                    brief, d.get("kind") or "assigned", how="rescheduled" if is_time else None
                ),
                reply_markup=_kb(brief),
            )
        except TelegramAPIError:
            log.info("edit of the zamer card failed", exc_info=True)
        await message.answer(T.SAVED_OK)

    return r
