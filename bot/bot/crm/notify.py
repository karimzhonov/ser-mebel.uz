"""`crm.task_due` (backend -> bot): «⏰ Vazifa vaqti keldi» to each recipient in `to`,
with the panel link, «✅ Bajarildi» and two snoozes. `crm.task_closed` / `crm.task_moved`:
the task changed elsewhere (panel, lead closed), so the reminders sent earlier get a status
line and lose their keyboard. Wording lives here; the backend sends data only
(docs/BOT_CONTRACT.md)."""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError

from bot.notify.registry import Notifier, on

from . import keyboards as K
from . import reminders
from . import texts as T

log = logging.getLogger("bot.crm.notify")


@on("crm.task_due")
async def task_due(n: Notifier, d: dict) -> None:
    text = T.task_due(d)
    task_id = int(d["task"]["id"])
    # no map button on a call reminder: the operator phones, nobody drives there
    kb = K.task_kb(task_id, d.get("url") or "")
    for tg in d.get("to") or []:
        msg = await n.send(tg, text, kb)
        mid = getattr(msg, "message_id", None)
        if mid is not None:
            await reminders.remember(task_id, tg, mid, text)


async def _apply_status(n: Notifier, task_id: int, line: str) -> None:
    for item in await reminders.take(task_id):
        html = item.get("html") or ""
        try:
            await n.bot.edit_message_text(
                f"{html}\n\n{line}" if html else line,
                chat_id=item["chat_id"],
                message_id=item["message_id"],
                reply_markup=None,
                parse_mode="HTML",
            )
        except TelegramAPIError as e:  # not modified / not found / blocked: nothing to do
            log.info("task %s reminder edit skipped: %s", task_id, e)
        except (KeyError, TypeError):
            continue


@on("crm.task_closed")
async def task_closed(n: Notifier, d: dict) -> None:
    await _apply_status(n, int(d["task"]["id"]), T.task_closed_line(d))


@on("crm.task_moved")
async def task_moved(n: Notifier, d: dict) -> None:
    await _apply_status(n, int(d["task"]["id"]), T.task_moved_line(d))
