"""Kit of the rover tests: the CRM kit (real build_dispatcher, fake Bot API session,
scripted backend). Shapes follow the RoverTask DTO; contract fixtures are loaded if present."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from crm.conftest import Backend, Env, FakeSession, buttons, cbs, env  # noqa: F401

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"
URL = "https://ser-mebel.uz/production/rover?open=12"

TASK = {
    "id": 12,
    "order": {"id": 88, "number": 406},
    "client": {"fio": "Karim Aliyev", "phone": "+998901234567"},
    "square": 3.5,
    "amount": "250000.00",
    "currency": "UZS",
    "state": "checking",
    "state_label": "Tekshiruvda",
    "submitted_at": "2026-11-10T15:20:00",
    "submitted_by": {"id": 5, "name": "Rover usta"},
    "checked_at": None,
    "checked_by": None,
    "url": URL,
    "address": "Chilonzor 7 & 12",
    "map_url": "https://yandex.com/maps/?pt=69.24,41.29",
    "due_date": "2026-11-15",
    "due_auto": False,
    "due_set_by": {"id": 14, "name": "Rahbar"},
    "overdue": False,
    "days_late": 0,
    "note": "",
    "rev": 3,
}


def task(**kw) -> dict:
    d = copy.deepcopy(TASK)
    d.update(kw)
    return d


def new_task(**kw) -> dict:
    return task(
        state="new",
        state_label="Ishda",
        submitted_at=None,
        submitted_by=None,
        **kw,
    )


def done_task(**kw) -> dict:
    return task(
        state="done",
        checked_at="2026-11-10T16:00:00",
        checked_by={"id": 9, "name": "Tekshiruvchi"},
        **kw,
    )


def envelope(event: str, n: int = 1, **data) -> dict:
    return {"id": f"00000000-0000-0000-0000-0000000097{n:02d}", "event": event, "data": data}


def fake_bot(mid=900):
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=mid))
    bot.edit_message_text = AsyncMock()
    return bot


def fixture(name: str):
    p = CONTRACT / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
