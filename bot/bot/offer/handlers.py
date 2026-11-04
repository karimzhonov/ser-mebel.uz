"""Buttons of the design / price cards.

Assignee (designer / pricer): «🕒 Muddatni o'zgartirish» (presets or a typed time). There is
NO «Tayyor» here: it is pressed on the site, and the card then updates itself
(`offer.changed`).

Manager (shows the work to the client): design «✅ Tasdiqladi» (asks to confirm) /
«✏️ O'zgartirish kerak» (typed comment) / «❌ Rad etdi» (typed reason); price «✅ Rozi» /
«🔁 Qayta hisoblash» / «❌ Narxi qoniqtirmadi». The backend says 403 (not yours / not
linked), 409 (already answered / not in work) or 400 and we show it as an alert / re-ask.

Stateless except the typed answers (FSM `OfferDue:custom`, `OfferAnswer:comment|reason`,
10 min TTL). No files here."""

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
from .states import OfferAnswer, OfferDue

log = logging.getLogger("bot.offer.handlers")

TTL = 600  # seconds a typed-answer prompt stays valid
DM_RE = re.compile(r"^of:dm:([dp]):(\d+)$")
DP_RE = re.compile(r"^of:dp:(1d|2d|3d):([dp]):(\d+)$")
DC_RE = re.compile(r"^of:dc:([dp]):(\d+)$")
BW_RE = re.compile(r"^of:bw:([dp]):(\d+)$")
OK_RE = re.compile(r"^of:ok:([dp]):(\d+)$")
OKY_RE = re.compile(r"^of:oky:([dp]):(\d+)$")
BK_RE = re.compile(r"^of:bk:([dp]):(\d+)$")
CH_RE = re.compile(r"^of:ch:([dp]):(\d+)$")
NO_RE = re.compile(r"^of:no:([dp]):(\d+)$")

# the answer word the backend expects, by kind and button
CHANGES = {"d": "changes", "p": "recalc"}


def _url(cb: CallbackQuery) -> str:
    """The site link of the pressed message's own keyboard, so intermediate screens keep it."""
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
    text = api.err_text(e).removeprefix("❗ ")
    await cb.answer(text[:200], show_alert=True)


def _work_kb(task: dict):
    if task.get("stage") != "work":
        return K.site_kb(task.get("url") or "")
    return K.work_kb(T.CODE.get(task.get("kind"), "d"), int(task["id"]), task.get("url") or "")


async def _show_work(cb: CallbackQuery, k: str, oid: int, task: dict, url: str) -> None:
    """Re-render the pressed assignee card from the backend's OfferTask."""
    m = cb.message
    if not isinstance(m, Message):
        return
    task = dict(task or {"id": oid, "kind": api.KIND_NAME[k]})
    task.setdefault("id", oid)
    task.setdefault("kind", api.KIND_NAME[k])
    if url and not task.get("url"):
        task["url"] = url
    try:
        await m.edit_text(T.work_card(task, T.kind_of(m.text)), reply_markup=_work_kb(task))
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            log.info("edit failed: %s", e)
    except TelegramAPIError:
        log.info("edit failed", exc_info=True)


def _final(task: dict, k: str, oid: int, answer: str) -> str:
    task = dict(task or {})
    task.setdefault("kind", api.KIND_NAME[k])
    task.setdefault("id", oid)
    return T.present_card(
        task, "ready", final=T.final_line("present", "answered", task, answer=answer)
    )


async def _drop_typed(state: FSMContext, k: str, oid: int) -> None:
    cur = await state.get_state()
    if cur and cur.startswith("Offer"):
        d = await state.get_data()
        if d.get("k") == k and d.get("oid") == oid:
            await state.clear()


def build() -> Router:
    r = Router(name="offer_buttons")

    # ---- assignee: «Muddatni o'zgartirish»
    @r.callback_query(F.data.regexp(DM_RE))
    async def due_menu(cb: CallbackQuery):
        k, oid = DM_RE.match(cb.data).groups()
        await _set_kb(cb, K.due_kb(k, int(oid), _url(cb)))
        await cb.answer(T.PICK_TIME)

    @r.callback_query(F.data.regexp(DP_RE))
    async def due_preset(cb: CallbackQuery, state: FSMContext):
        code, k, tid = DP_RE.match(cb.data).groups()
        oid = int(tid)
        url = _url(cb)
        try:
            res = await api.call(
                "POST", api.path(k, oid, "due"), actor=cb.from_user.id, json={"preset": code}
            )
        except api.BackendError as e:
            await _alert(cb, e)
            return
        await _drop_typed(state, k, oid)
        await cb.answer(T.SAVED_OK)
        await _show_work(cb, k, oid, (res or {}).get("task"), url)

    @r.callback_query(F.data.regexp(BW_RE))
    async def back_work(cb: CallbackQuery, state: FSMContext):
        k, tid = BW_RE.match(cb.data).groups()
        await _drop_typed(state, k, int(tid))
        await _set_kb(cb, K.work_kb(k, int(tid), _url(cb)))
        await cb.answer()

    async def _ask(cb: CallbackQuery, state: FSMContext, k: str, oid: int, target, prompt: str):
        cur = await state.get_state()
        if cur is not None and not cur.startswith("Offer"):
            await cb.answer(T.BUSY, show_alert=True)
            return
        m = cb.message
        if not isinstance(m, Message):
            await cb.answer(T.STALE)
            return
        await state.set_state(target)
        await state.set_data(
            {
                "k": k,
                "oid": oid,
                "chat_id": m.chat.id,
                "message_id": m.message_id,
                "kind": T.kind_of(m.text),
                "url": _url(cb),
                "ts": time.time(),
            }
        )
        await cb.answer()
        await m.answer(prompt, reply_markup=K.cancel_kb())

    @r.callback_query(F.data.regexp(DC_RE))
    async def ask_time(cb: CallbackQuery, state: FSMContext):
        k, oid = DC_RE.match(cb.data).groups()
        await _ask(cb, state, k, int(oid), OfferDue.custom, T.ASK_TIME)

    # ---- manager: client's answer
    @r.callback_query(F.data.regexp(OK_RE))
    async def ask_ok(cb: CallbackQuery):
        k, oid = OK_RE.match(cb.data).groups()
        await _set_kb(cb, K.confirm_kb(k, int(oid), _url(cb)))
        await cb.answer(T.CONFIRM_ASK)

    @r.callback_query(F.data.regexp(BK_RE))
    async def back_present(cb: CallbackQuery, state: FSMContext):
        k, oid = BK_RE.match(cb.data).groups()
        await _set_kb(cb, K.present_kb(k, int(oid), _url(cb)))
        await cb.answer()

    @r.callback_query(F.data.regexp(OKY_RE))
    async def confirmed(cb: CallbackQuery, state: FSMContext):
        k, tid = OKY_RE.match(cb.data).groups()
        oid = int(tid)
        try:
            res = await api.call(
                "POST",
                api.path(k, oid, "answer"),
                actor=cb.from_user.id,
                json={"answer": "approved"},
            )
        except api.BackendError as e:
            await _alert(cb, e)
            return
        await _drop_typed(state, k, oid)
        await cb.answer(T.SAVED_OK)
        m = cb.message
        if isinstance(m, Message):
            try:
                await m.edit_text(
                    _final((res or {}).get("task"), k, oid, "approved"), reply_markup=None
                )
            except TelegramAPIError:
                log.info("edit failed", exc_info=True)

    @r.callback_query(F.data.regexp(CH_RE))
    async def ask_comment(cb: CallbackQuery, state: FSMContext):
        k, oid = CH_RE.match(cb.data).groups()
        await _ask(cb, state, k, int(oid), OfferAnswer.comment, T.ASK_COMMENT[k])

    @r.callback_query(F.data.regexp(NO_RE))
    async def ask_reason(cb: CallbackQuery, state: FSMContext):
        k, oid = NO_RE.match(cb.data).groups()
        await _ask(cb, state, k, int(oid), OfferAnswer.reason, T.ASK_REASON[k])

    @r.callback_query(F.data == "of:q")
    async def cancel_typed(cb: CallbackQuery, state: FSMContext):
        cur = await state.get_state()
        if cur and cur.startswith("Offer"):
            await state.clear()
        await cb.answer(T.CANCELLED)
        await _set_kb(cb, None)

    # ---- typed answers
    typed = StateFilter(OfferDue.custom, OfferAnswer.comment, OfferAnswer.reason)

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
        cur = await state.get_state()
        uid = message.from_user.id
        k, oid = d.get("k"), int(d.get("oid"))
        if cur == OfferDue.custom.state:
            action, body, field, ask = "due", {"text": text}, "due", T.ASK_TIME
        elif cur == OfferAnswer.comment.state:
            action, field = "answer", "comment"
            body, ask = {"answer": CHANGES[k], "comment": text}, T.ASK_COMMENT[k]
        else:
            action, field = "answer", "comment"
            body, ask = {"answer": "declined", "comment": text}, T.ASK_REASON[k]
        try:
            res = await api.call("POST", api.path(k, oid, action), actor=uid, json=body)
        except api.BackendError as e:
            log.info("typed offer answer failed for %s: %s", uid, e)
            if isinstance(e, api.ServiceRefusal) and e.field == field:
                await message.answer(api.err_text(e) + "\n\n" + ask, reply_markup=K.cancel_kb())
                return
            await state.clear()
            await message.answer(api.err_text(e))
            return
        await state.clear()
        task = dict((res or {}).get("task") or {})
        task.setdefault("id", oid)
        task.setdefault("kind", api.KIND_NAME[k])
        if d.get("url") and not task.get("url"):
            task["url"] = d["url"]
        if action == "due":
            new_text, kb = T.work_card(task, d.get("kind") or "new"), _work_kb(task)
        else:
            new_text, kb = _final(task, k, oid, body["answer"]), None
        try:
            await message.bot.edit_message_text(
                chat_id=d.get("chat_id"),
                message_id=d.get("message_id"),
                text=new_text,
                reply_markup=kb,
            )
        except TelegramAPIError:
            log.info("edit of the offer card failed", exc_info=True)
        await message.answer(T.SAVED_OK)

    return r
