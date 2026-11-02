"""`crm.task_due` (backend -> bot): «⏰ Vazifa vaqti keldi» to each recipient in `to`,
with the panel link, «✅ Bajarildi» and two snoozes. Wording lives here; the backend sends
data only (docs/BOT_CONTRACT.md)."""

from __future__ import annotations

from bot.notify.registry import Notifier, on

from . import keyboards as K
from . import texts as T


@on("crm.task_due")
async def task_due(n: Notifier, d: dict) -> None:
    text = T.task_due(d)
    kb = K.task_kb(int(d["task"]["id"]), d.get("url") or "")
    for tg in d.get("to") or []:
        await n.send(tg, text, kb)
