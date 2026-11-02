"""Buttons under the `crm.task_due` reminder: «✅ Bajarildi» and the two snoozes.
They work for the person the backend links to this Telegram account; the backend says
403 (not your task / not linked) or 409 (already done) and we show it as an alert."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from bot.common.fmt import esc

from .. import api
from .. import texts as T

log = logging.getLogger("bot.crm.tasks")

PRESETS = {"1h": "1h", "tm": "tomorrow"}


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


async def _alert(cb: CallbackQuery, e: api.BackendError) -> None:
    text = api.err_text(e).removeprefix("❗ ")
    await cb.answer(text[:200], show_alert=True)


def build() -> Router:
    r = Router(name="crm_tasks")

    @r.callback_query(F.data.regexp(r"^crm:done:\d+$"))
    async def done(cb: CallbackQuery):
        task_id = int(cb.data.split(":")[2])
        try:
            res = await api.call(
                "POST", f"crm/tasks/{task_id}/done/", actor=cb.from_user.id, json={}
            )
        except api.BackendError as e:
            await _alert(cb, e)
            return
        await cb.answer()
        name = (res or {}).get("by_name") or cb.from_user.full_name
        await _finish(cb, f"✅ Bajarildi — {esc(name)}")

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
