"""Buttons under the `crm.task_due` reminder: «✅ Bajarildi» (asks the next stage first) and
the two snoozes. They work for the person the backend links to this Telegram account; the
backend says 403 (not your task / not linked) or 409 (already done) and we show it as an alert.

Completion is stateless (every step is a button carrying the task id; the url / map rows
are copied from the message itself) except a typed time: FSM `TaskDone:custom`, 10 min TTL.
Which stages are offered, and every rule, is decided by the backend (GET crm/tasks/{id}/)."""

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

from bot.hr.texts import FINANCE_MENU_BUTTONS

from .. import api
from .. import keyboards as K
from .. import texts as T
from ..states import TaskDone
from .lead import CMD_CANCEL

log = logging.getLogger("bot.crm.tasks")

PRESETS = {"1h": "1h", "tm": "tomorrow"}
DONE_TTL = 600  # seconds a typed-time prompt stays valid
DO_RE = re.compile(r"^crm:do:(rp|gi|gl|pp|dn|dc):(\d+)$")
DT_RE = re.compile(r"^crm:dt:(rp|gi|gl):(1h|td|tm|cu|no):(\d+)$")
DY_RE = re.compile(r"^crm:dy:(pp|dn|dc):(\d+)$")
DX_RE = re.compile(r"^crm:dx:(\d+)$")
FIELD_ERRORS = ("outcome", "next_task")


async def _finish(cb: CallbackQuery, line: str) -> None:
    """Edit the reminder: status line on top of the original text, keyboard removed."""
    m = cb.message
    if not isinstance(m, Message):
        return
    body = m.html_text or ""
    try:
        await m.edit_text(f"{line}\n\n{body}" if body else line, reply_markup=None)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            log.info("edit failed: %s", e)
    except TelegramAPIError:
        log.info("edit failed", exc_info=True)


def _links(cb: CallbackQuery) -> tuple[str, str]:
    """(panel url, map url) of the message's own keyboard, so intermediate screens keep them."""
    url = map_url = ""
    m = cb.message
    if isinstance(m, Message) and m.reply_markup:
        for row in m.reply_markup.inline_keyboard:
            for btn in row:
                if btn.url and btn.text == T.OPEN_PANEL:
                    url = btn.url
                elif btn.url and btn.text == T.MAP_BTN:
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


async def _drop_custom(state: FSMContext, task_id: int) -> None:
    """Forget a pending typed-time prompt, but only when it belongs to this task."""
    cur = await state.get_state()
    if cur and cur.startswith("TaskDone:"):
        if (await state.get_data()).get("task") == task_id:
            await state.clear()


def build() -> Router:
    r = Router(name="crm_tasks")

    async def complete(
        cb: CallbackQuery, state: FSMContext, task_id: int, body: dict, *, retry: bool = True
    ):
        """POST done and finish the message. A 400 on outcome / next_task alerts and
        re-opens the picker (`retry`); 409 / 403 alert and keep the message."""
        try:
            res = await api.call(
                "POST", f"crm/tasks/{task_id}/done/", actor=cb.from_user.id, json=body
            )
        except api.BackendError as e:
            await _alert(cb, e)
            if retry and isinstance(e, api.ServiceRefusal) and e.field in FIELD_ERRORS:
                await picker(cb, state, task_id, answer=False)
            return
        await _drop_custom(state, task_id)
        await cb.answer()
        res = dict(res or {})
        res.setdefault("by_name", cb.from_user.full_name)
        await _finish(cb, T.task_done_line(res))

    async def picker(
        cb: CallbackQuery, state: FSMContext, task_id: int, *, answer: bool = True
    ) -> None:
        """Show the stages the backend allows (or finish at once when only `keep` is)."""
        try:
            res = await api.call("GET", f"crm/tasks/{task_id}/", actor=cb.from_user.id)
        except api.BackendError as e:
            await _alert(cb, e)
            return
        res = res or {}
        outcomes = list(res.get("outcomes") or [])
        if outcomes == ["keep"] or not outcomes:
            await complete(cb, state, task_id, {"outcome": "keep"}, retry=False)
            return
        url, map_url = _links(cb)
        url = url or res.get("url") or ""
        await _set_kb(cb, K.outcome_kb(task_id, outcomes, url, map_url))
        if answer:
            await cb.answer(T.PICK_STAGE)

    @r.callback_query(F.data.regexp(r"^crm:done:\d+$"))
    async def done(cb: CallbackQuery, state: FSMContext):
        task_id = int(cb.data.split(":")[2])
        await _drop_custom(state, task_id)
        await picker(cb, state, task_id)

    @r.callback_query(F.data.regexp(DO_RE))
    async def do_stage(cb: CallbackQuery):
        code, tid = DO_RE.match(cb.data).groups()
        task_id = int(tid)
        url, map_url = _links(cb)
        if code in ("pp", "dn", "dc"):
            await _set_kb(cb, K.close_kb(code, task_id, url, map_url))
            await cb.answer(T.CLOSE_WARN, show_alert=True)
            return
        optional = code != "rp"
        await _set_kb(cb, K.due_kb(code, task_id, optional, url, map_url))
        await cb.answer(T.ASK_DUE_OPT if optional else T.ASK_DUE)

    @r.callback_query(F.data.regexp(DY_RE))
    async def close_yes(cb: CallbackQuery, state: FSMContext):
        code, tid = DY_RE.match(cb.data).groups()
        await complete(cb, state, int(tid), {"outcome": K.CODE_OUTCOME[code]})

    async def ask_custom(cb: CallbackQuery, state: FSMContext, task_id: int, outcome: str):
        cur = await state.get_state()
        if cur is not None and not cur.startswith("TaskDone:"):
            await cb.answer(T.TASK_BUSY, show_alert=True)
            return
        m = cb.message
        if not isinstance(m, Message):
            await cb.answer(T.STALE)
            return
        url, map_url = _links(cb)
        await state.set_state(TaskDone.custom)
        await state.set_data(
            {
                "task": task_id,
                "outcome": outcome,
                "chat_id": m.chat.id,
                "message_id": m.message_id,
                "html": m.html_text or "",
                "url": url,
                "map_url": map_url,
                "ts": time.time(),
            }
        )
        await cb.answer()
        await m.answer(T.ASK_DUE_CUSTOM, reply_markup=K.due_cancel_kb())

    @r.callback_query(F.data.regexp(DT_RE))
    async def pick_time(cb: CallbackQuery, state: FSMContext):
        code, when, tid = DT_RE.match(cb.data).groups()
        task_id = int(tid)
        outcome = K.CODE_OUTCOME[code]
        if when == "cu":
            await ask_custom(cb, state, task_id, outcome)
            return
        if when == "no":
            if code == "rp":  # the time is mandatory here: an old / forged button
                await cb.answer(T.STALE)
                return
            await complete(cb, state, task_id, {"outcome": outcome})
            return
        body = {"outcome": outcome, "next_task": {"preset": K.PRESET_CODES[when]}}
        await complete(cb, state, task_id, body)

    @r.callback_query(F.data.regexp(DX_RE))
    async def restore(cb: CallbackQuery, state: FSMContext):
        task_id = int(DX_RE.match(cb.data).group(1))
        await _drop_custom(state, task_id)
        url, map_url = _links(cb)
        await _set_kb(cb, K.task_kb(task_id, url, map_url))
        await cb.answer()

    @r.callback_query(F.data == "crm:dq")
    async def cancel_custom(cb: CallbackQuery, state: FSMContext):
        cur = await state.get_state()
        if cur and cur.startswith("TaskDone:"):
            await state.clear()
        await cb.answer(T.CANCELLED)
        await _set_kb(cb, None)

    # ---- typed time
    @r.message(F.text.regexp(CMD_CANCEL), StateFilter(TaskDone.custom))
    async def custom_cancel(message: Message, state: FSMContext):
        await state.clear()
        await message.answer(T.CANCELLED)

    @r.message(F.text & ~F.text.startswith("/") & ~F.forward_origin, StateFilter(TaskDone.custom))
    async def custom_time(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if text in FINANCE_MENU_BUTTONS or text == T.NEW_BTN:
            await state.clear()
            raise SkipHandler
        d = await state.get_data()
        ts = d.get("ts")
        if not isinstance(ts, (int, float)) or time.time() - ts > DONE_TTL:
            await state.clear()
            await message.answer(T.STALE)
            return
        uid = message.from_user.id
        again = "\n\n" + T.ASK_DUE_CUSTOM
        try:
            parsed = await api.call("POST", "crm/due/parse/", actor=uid, json={"text": text})
        except api.ServiceRefusal as e:
            await message.answer(api.err_text(e) + again, reply_markup=K.due_cancel_kb())
            return
        except api.BackendError as e:
            await message.answer(api.err_text(e))
            return
        body = {
            "outcome": d.get("outcome"),
            "next_task": {"due_at": str((parsed or {}).get("due_at"))},
        }
        try:
            res = await api.call(
                "POST", f"crm/tasks/{int(d.get('task'))}/done/", actor=uid, json=body
            )
        except api.BackendError as e:
            log.info("typed-time done failed for %s: %s", uid, e)
            if isinstance(e, api.ServiceRefusal) and e.field == "next_task":
                await message.answer(api.err_text(e) + again, reply_markup=K.due_cancel_kb())
                return
            await state.clear()
            await message.answer(api.err_text(e))
            return
        await state.clear()
        res = dict(res or {})
        res.setdefault("by_name", message.from_user.full_name)
        line = T.task_done_line(res)
        html = d.get("html") or ""
        try:
            await message.bot.edit_message_text(
                chat_id=d.get("chat_id"),
                message_id=d.get("message_id"),
                text=f"{line}\n\n{html}" if html else line,
                reply_markup=None,
            )
        except TelegramAPIError:
            log.info("edit of the reminder failed", exc_info=True)
        await message.answer(T.SAVED_OK)

    @r.callback_query(F.data.regexp(r"^crm:sn:(1h|tm):\d+$"))
    async def snooze(cb: CallbackQuery):
        _, _, kind, tid = cb.data.split(":")
        try:
            res = await api.call(
                "POST",
                f"crm/tasks/{int(tid)}/snooze/",
                actor=cb.from_user.id,
                json={"preset": PRESETS[kind]},
            )
        except api.BackendError as e:
            await _alert(cb, e)
            return
        await cb.answer()
        due = ((res or {}).get("task") or {}).get("due_at")
        await _finish(cb, f"⏰ {T.dt_short(due)} ga ko'chirildi")

    return r
