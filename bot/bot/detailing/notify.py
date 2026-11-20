"""Detailing events (backend -> bot).

- `detailing.task`: the task card to every detailer in `to` (new message each time —
  "new" when the order is sent to detailing, "moved" when its deadline changes).
"""

from __future__ import annotations

from bot.notify.registry import Notifier, on

from . import keyboards as K
from . import texts as T


def _tgs(value) -> list[int]:
    if isinstance(value, (int, str)) and str(value).lstrip("-").isdigit():
        return [int(value)]
    return [int(x) for x in (value or [])]


@on("detailing.task")
async def task(n: Notifier, d: dict) -> None:
    t = d["detailing"]
    text = T.task_card(t, d.get("how"))
    kb = K.task_kb(t.get("url") or "", t.get("folder_url"), bool(t.get("done")))
    for tg in _tgs(d.get("to")):
        await n.send(tg, text, kb)
