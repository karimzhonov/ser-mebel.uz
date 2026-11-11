"""Kit of the painter tests: the CRM kit (real build_dispatcher, fake Bot API session,
scripted backend). Shapes follow the PainterTask DTO; contract fixtures are loaded if present."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from crm.conftest import Backend, Env, FakeSession, buttons, cbs, env  # noqa: F401

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"
URL = "https://ser-mebel.uz/production/painter?open=21"

TASK = {
    "id": 21,
    "order": {"id": 88, "number": 406},
    "client": {"fio": "Karim Aliyev", "phone": "+998901234567"},
    "address": "Chilonzor 7 & 12",
    "map_url": "https://yandex.com/maps/?pt=69.24,41.29",
    "square": 3.5,
    "type": {"id": 3, "name": "Emal"},
    "painter": {"id": 5, "name": "Molyar usta"},
    "outsource": False,
    "state": "new",
    "state_label": "Ishda",
    "started_at": "2026-11-10T09:00:00",
    "done_at": None,
    "done_by": None,
    "due_date": "2026-11-20",
    "due_auto": False,
    "due_set_by": {"id": 14, "name": "Rahbar"},
    "overdue": False,
    "days_late": 0,
    "note": "",
    "rev": 3,
    "url": URL,
}


def task(**kw) -> dict:
    d = copy.deepcopy(TASK)
    d.update(kw)
    return d


def done_task(**kw) -> dict:
    base = {
        "state": "done",
        "state_label": "Bajarildi",
        "done_at": "2026-11-12T10:00:00",
        "done_by": {"id": 5, "name": "Molyar usta"},
        "note": "4 ta eshik",
    }
    return task(**{**base, **kw})


def envelope(event: str, n: int = 1, **data) -> dict:
    return {"id": f"00000000-0000-0000-0000-0000000096{n:02d}", "event": event, "data": data}


def fake_bot(mid=900):
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=mid))
    bot.edit_message_text = AsyncMock()
    return bot


def fixture(name: str):
    p = CONTRACT / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
