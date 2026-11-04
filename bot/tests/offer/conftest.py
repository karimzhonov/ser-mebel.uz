"""Kit of the design / price bot tests: reuses the CRM kit (real build_dispatcher, fake Bot
API session, scripted backend). Shapes follow the approved design (OfferTask, offer.*
events); the contract fixtures are checked in test_contract.py when present."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from crm.conftest import Backend, Env, FakeSession, buttons, cbs, env  # noqa: F401

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"

TASK = {
    "kind": "design",
    "id": 12,
    "rev": 3,
    "metering_id": 7,
    "round": 1,
    "stage": "work",
    "stage_label": "Ishda",
    "client": {"fio": "Karim <b>Aliyev", "phone": "+998901234567"},
    "address": "Yunusobod 3 & 5",
    "map_url": "https://yandex.uz/maps/?ll=69.27,41.31",
    "due_at": "2026-12-25T18:00:00",
    "done_at": None,
    "assignee": {"id": 3, "name": "Dizayner"},
    "manager": {"id": 4, "name": "Menejer"},
    "measurer": {"id": 5, "name": "Zamerchi"},
    "note": "3-qavat, lift yo'q",
    "last_comment": "",
    "next_step": "design_price",
    "url": "https://ser-mebel.uz/designs/12",
    "present_url": "https://ser-mebel.uz/presentations?open=d12",
}


def task(**kw) -> dict:
    d = copy.deepcopy(TASK)
    d.update(kw)
    return d


def price_task(**kw) -> dict:
    return task(
        kind="price",
        id=15,
        url="https://ser-mebel.uz/prices/15",
        present_url="https://ser-mebel.uz/presentations?open=p15",
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
