"""Buttons under the rover cards.

Checker: «✅ Bajarildi» asks to confirm, «✅ Ha, tasdiqlayman» posts `rovers/{id}/confirm/`.
Worker: «✅ Bajardim» (`rv:dn`) opens the FSM `RoverDone:amount -> note -> confirm` (30 min
TTL), «✅ Yuborish» posts `rovers/{id}/submit/ {amount, note}`.
Production head: `rv:dd:{days}:{id}` posts `rovers/{id}/due/ {days}`.
The backend decides (403 not linked / no role, 409 already done, 400 field, 404); we show it
as an alert / re-ask."""

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
from .parse import NOTE_MAX, note_ok, parse_amount
from .states import RoverDone

log = logging.getLogger("bot.rover.handlers")

TTL = 1800  # seconds a «Bajardim» flow stays valid
RV_RE = re.compile(r"^rv:(ok|oky|bk):(\d+)$")
DN_RE = re.compile(r"^rv:dn:(\d+)$")
SY_RE = re.compile(r"^rv:sy:(\d+)$")
SE_RE = re.compile(r"^rv:se:(\d+)$")
DD_RE = re.compile(r"^rv:dd:(\d+):(\d+)$")


def _url(cb: CallbackQuery) -> str:
    """The site link of the message's own keyboard, so intermediate screens keep it."""
    m = cb.message
    if isinstance(m, Message) and m.reply_markup:
        for row in m.reply_markup.inline_keyboard:
            for btn in row:
                if btn.url and btn.text == K.OPEN_PANEL:
                    return btn.url
    return ""


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
    await cb.answer(api.err_text(e).removeprefix("❗ ")[:200], show_alert=True)


async def _edit_card(bot, d: dict, text: str | None, kb) -> None:
    """Edit the stored task card (chat_id / message_id of the FSM data)."""
    try:
        if text is None:
            await bot.edit_message_reply_markup(
                chat_id=d.get("chat_id"), message_id=d.get("message_id"), reply_markup=kb
            )
        else:
            await bot.edit_message_text(
                text, chat_id=d.get("chat_id"), message_id=d.get("message_id"), reply_markup=kb
            )
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            log.info("edit of the rover card failed: %s", e)
    except TelegramAPIError:
        log.info("edit of the rover card failed", exc_info=True)


def _fresh(d: dict) -> bool:
    ts = d.get("ts")
    return isinstance(ts, (int, float)) and time.time() - ts <= TTL


def build() -> Router:
    r = Router(name="rover_buttons")

    @r.callback_query(F.data.regexp(RV_RE))
    async def press(cb: CallbackQuery):
        action, rid = RV_RE.match(cb.data).groups()
        rid_i = int(rid)
        url = _url(cb)
        if action == "ok":
            await _set_kb(cb, K.confirm_kb(rid_i, url))
            await cb.answer(T.CONFIRM_ASK)
            return
        if action == "bk":
            await _set_kb(cb, K.card_kb(rid_i, "checking", url))
            await cb.answer()
            return
        try:
            res = await api.call("POST", f"rovers/{rid_i}/confirm/", actor=cb.from_user.id, json={})
        except api.Conflict as e:
            await _set_kb(cb, K.card_kb(rid_i, "done", url))  # already confirmed: no action
            await _alert(cb, e)
            return
        except api.NotFound as e:
            await _set_kb(cb, K.card_kb(rid_i, "done", url))  # rover is gone: link only
            await _alert(cb, e)
            return
        except api.BackendError as e:
            await _set_kb(cb, K.card_kb(rid_i, "checking", url))  # retry possible: normal card
            await _alert(cb, e)
            return
        except Exception:  # noqa: BLE001
            log.exception("rover confirm %s failed", rid_i)
            await _set_kb(cb, K.card_kb(rid_i, "checking", url))
            await cb.answer(api.DOWN_TEXT, show_alert=True)
            return
        task = (res or {}).get("rover") or {}
        m = cb.message
        if task and isinstance(m, Message):
            try:
                await m.edit_text(
                    T.card(task), reply_markup=K.card_kb(rid_i, "done", task.get("url") or url)
                )
            except TelegramBadRequest as e:
                if "not modified" not in str(e).lower():
                    log.info("edit card failed: %s", e)
            except TelegramAPIError:
                log.info("edit card failed", exc_info=True)
        else:
            await _set_kb(cb, K.card_kb(rid_i, "done", url))
        await cb.answer(T.DONE_OK)

    # ---- head: deadline presets
    @r.callback_query(F.data.regexp(DD_RE))
    async def set_due(cb: CallbackQuery):
        days, rid = DD_RE.match(cb.data).groups()
        rid_i = int(rid)
        url = _url(cb)
        try:
            res = await api.call(
                "POST", f"rovers/{rid_i}/due/", actor=cb.from_user.id, json={"days": int(days)}
            )
        except (api.Conflict, api.NotFound) as e:
            await _set_kb(cb, K.due_kb(rid_i, (), url, "done"))  # nothing to set any more
            await _alert(cb, e)
            return
        except api.BackendError as e:
            await _alert(cb, e)
            return
        except Exception:  # noqa: BLE001
            log.exception("rover due %s failed", rid_i)
            await cb.answer(api.DOWN_TEXT, show_alert=True)
            return
        task = (res or {}).get("rover") or {}
        m = cb.message
        if task and isinstance(m, Message):
            try:
                await m.edit_text(
                    T.head_card(task),
                    reply_markup=K.due_kb(
                        rid_i, K.PRESETS, task.get("url") or url, task.get("state") or "new"
                    ),
                )
            except TelegramBadRequest as e:
                if "not modified" not in str(e).lower():
                    log.info("edit card failed: %s", e)
            except TelegramAPIError:
                log.info("edit card failed", exc_info=True)
        await cb.answer(T.DUE_SAVED)

    # ---- worker: «Bajardim» -> amount -> note -> confirm
    @r.callback_query(F.data.regexp(DN_RE))
    async def start_done(cb: CallbackQuery, state: FSMContext):
        rid = int(DN_RE.match(cb.data).group(1))
        cur = await state.get_state()
        if cur is not None and not cur.startswith("RoverDone"):
            await cb.answer(T.BUSY, show_alert=True)
            return
        m = cb.message
        if not isinstance(m, Message):
            await cb.answer(T.STALE)
            return
        await state.set_state(RoverDone.amount)
        await state.set_data(
            {
                "rid": rid,
                "chat_id": m.chat.id,
                "message_id": m.message_id,
                "url": _url(cb),
                "ts": time.time(),
            }
        )
        await cb.answer()
        await m.answer(T.ASK_AMOUNT, reply_markup=K.cancel_kb())

    @r.callback_query(F.data.regexp(SE_RE))
    async def restart(cb: CallbackQuery, state: FSMContext):
        rid = int(SE_RE.match(cb.data).group(1))
        d = await state.get_data()
        cur = await state.get_state()
        if not (cur and cur.startswith("RoverDone") and d.get("rid") == rid and _fresh(d)):
            if cur and cur.startswith("RoverDone"):
                await state.clear()
            await _set_kb(cb, None)
            await cb.answer(T.STALE, show_alert=True)
            return
        await state.update_data(ts=time.time())
        await state.set_state(RoverDone.amount)
        await _set_kb(cb, None)
        await cb.answer()
        m = cb.message
        if isinstance(m, Message):
            await m.answer(T.ASK_AMOUNT, reply_markup=K.cancel_kb())

    @r.callback_query(F.data == "rv:q")
    async def cancel_typed(cb: CallbackQuery, state: FSMContext):
        cur = await state.get_state()
        if cur and cur.startswith("RoverDone"):
            await state.clear()
        await cb.answer(T.CANCELLED)
        await _set_kb(cb, None)

    @r.callback_query(F.data.regexp(SY_RE))
    async def submit(cb: CallbackQuery, state: FSMContext):
        rid = int(SY_RE.match(cb.data).group(1))
        d = await state.get_data()
        cur = await state.get_state()
        if (
            cur != RoverDone.confirm.state
            or d.get("rid") != rid
            or not _fresh(d)
            or not d.get("amount")
            or not d.get("note")
        ):
            if cur and cur.startswith("RoverDone"):
                await state.clear()
            await _set_kb(cb, None)
            await cb.answer(T.STALE, show_alert=True)
            return
        url = d.get("url") or ""
        try:
            res = await api.call(
                "POST",
                f"rovers/{rid}/submit/",
                actor=cb.from_user.id,
                json={"amount": d["amount"], "note": d["note"]},
            )
        except api.ServiceRefusal as e:
            if e.field in ("amount", "note"):
                target = RoverDone.amount if e.field == "amount" else RoverDone.note
                await state.set_state(target)
                await state.update_data(ts=time.time())
                await _set_kb(cb, None)
                await cb.answer()
                m = cb.message
                if isinstance(m, Message):
                    ask = T.ASK_AMOUNT if e.field == "amount" else T.ASK_NOTE
                    await m.answer(api.err_text(e) + "\n\n" + ask, reply_markup=K.cancel_kb())
                return
            await state.clear()
            await _set_kb(cb, None)
            await _alert(cb, e)
            return
        except (api.Conflict, api.NotFound) as e:
            await state.clear()
            await _edit_card(cb.bot, d, None, K.task_kb(rid, "checking", url))
            await _set_kb(cb, None)
            await _alert(cb, e)
            return
        except api.BackendError as e:
            await state.clear()
            await _set_kb(cb, None)
            await _alert(cb, e)
            return
        except Exception:  # noqa: BLE001
            log.exception("rover submit %s failed", rid)
            await state.clear()
            await _set_kb(cb, None)
            await cb.answer(api.DOWN_TEXT, show_alert=True)
            return
        await state.clear()
        task = dict((res or {}).get("rover") or {})
        task.setdefault("id", rid)
        if url and not task.get("url"):
            task["url"] = url
        await _edit_card(
            cb.bot, d, T.task_card(task), K.task_kb(rid, "checking", task.get("url") or "")
        )
        m = cb.message
        if isinstance(m, Message):
            try:
                await m.edit_text(T.SUBMITTED, reply_markup=None)
            except TelegramAPIError:
                log.info("edit of the summary failed", exc_info=True)
        await cb.answer(T.SUBMITTED)

    # ---- typed amount / note
    typed = StateFilter(RoverDone.amount, RoverDone.note, RoverDone.confirm)

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
        if not _fresh(d):
            await state.clear()
            await message.answer(T.STALE)
            return
        cur = await state.get_state()
        if cur == RoverDone.amount.state:
            amount = parse_amount(text)
            if amount is None:
                await message.answer(
                    T.BAD_AMOUNT + "\n\n" + T.ASK_AMOUNT, reply_markup=K.cancel_kb()
                )
                return
            await state.update_data(amount=str(amount), ts=time.time())
            await state.set_state(RoverDone.note)
            await message.answer(T.ASK_NOTE, reply_markup=K.cancel_kb())
            return
        if cur == RoverDone.note.state:
            if not note_ok(text):
                bad = T.LONG_NOTE if len(text) > NOTE_MAX else T.BAD_NOTE
                await message.answer(bad + "\n\n" + T.ASK_NOTE, reply_markup=K.cancel_kb())
                return
            await state.update_data(note=text, ts=time.time())
            await state.set_state(RoverDone.confirm)
            await message.answer(
                T.summary(d.get("amount"), text), reply_markup=K.summary_kb(int(d["rid"]))
            )
            return
        await message.answer(T.USE_BUTTONS, reply_markup=K.summary_kb(int(d["rid"])))

    return r
