import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.common.actor import Actor
from bot.finance import api as fapi
from bot.finance.ctx import Ctx

FIX = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"


def fx(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


class FakeBackend:
    """Routes (METHOD, path) -> value / exception / callable(json, params); records calls."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    async def request(
        self, method, path, *, actor=None, json=None, params=None, files=None, raw=False
    ):
        self.calls.append((method, path, json, params))
        key = (method, path)
        if key not in self.routes:
            raise AssertionError(f"unexpected backend call {method} {path}")
        v = self.routes[key]
        if isinstance(v, Exception):
            raise v
        return v(json, params) if callable(v) else v


@pytest.fixture
def be(monkeypatch):
    f = FakeBackend()
    from bot.backend.client import backend

    monkeypatch.setattr(backend, "request", f.request)
    return f


@pytest.fixture
def cats():
    base = fx("dto.category.1")
    return [base, {**base, "code": "oylik", "name": "Oylik", "no_order": True}]


@pytest.fixture
def make_ctx(be):
    def make(member=None, admin=False):
        m = {**fx("dto.member.1"), "is_admin": admin, **(member or {})}
        user = SimpleNamespace(id=m["telegram_id"], username="u", first_name="F", last_name=None)
        actor = Actor(user=user, member=m)
        bot = MagicMock()
        sent = SimpleNamespace(message_id=500)
        bot.send_message = AsyncMock(return_value=sent)
        bot.send_photo = AsyncMock(return_value=sent)
        bot.edit_message_text = AsyncMock()
        bot.delete_message = AsyncMock(return_value=True)
        state = FSMContext(MemoryStorage(), StorageKey(1, 1, 1))
        return Ctx(bot, actor, state, 1)

    return make


def texts(ctx):
    return [
        c.args[1] if len(c.args) > 1 else c.kwargs.get("text")
        for c in ctx.bot.send_message.call_args_list
    ]


@pytest.fixture(autouse=True)
def _nocache(monkeypatch):
    async def passthrough(key, loader, ttl=60):
        return await loader()

    monkeypatch.setattr(fapi, "_cached", passthrough)
