"""Kit of the zamer bot tests: reuses the CRM kit (real build_dispatcher, fake Bot API
session, scripted backend). Shapes follow docs/BOT_CONTRACT.md (MeteringBrief, metering.*
events); the contract fixtures are checked in test_contract.py when present."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from crm.conftest import Backend, Env, FakeSession, buttons, cbs, env  # noqa: F401

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"
MAP = "https://yandex.uz/maps/?ll=69.27,41.31&pt=69.27,41.31"

BRIEF = {
    "id": 7,
    "rev": 3,
    "client": {"fio": "Karim <b>Aliyev", "phone": "+998901234567"},
    "status": "created",
    "status_label": "Yaratilgan",
    "date_time": "2026-12-25T14:30:00",
    "address": "Yunusobod 3 & 5",
    "map_url": MAP,
    "has_point": True,
    "desc": "3-qavat",
    "measurer": {"id": 3, "name": "Zamerchi"},
    "operator": {"id": 4, "name": "Operator"},
    "next_step": "",
    "cancel_reason": "",
    "url": "https://ser-mebel.uz/meterings/7",
}


def brief(**kw) -> dict:
    d = copy.deepcopy(BRIEF)
    d.update(kw)
    return d


def envelope(event: str, n: int = 1, **data) -> dict:
    return {"id": f"00000000-0000-0000-0000-0000000095{n:02d}", "event": event, "data": data}


def fake_bot(mid=900):
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=mid))
    bot.edit_message_text = AsyncMock()
    return bot


def fixture(name: str):
    p = CONTRACT / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
