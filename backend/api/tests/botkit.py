"""Test kit for the internal bot channel (/api/v1/bot/...) and the events it emits.

- `bot_client`: signs requests exactly like the bot service does (core.bot_signing).
- `bot_events`: collects every event envelope queued with core.bot_notify.emit; the
  on_commit hop is executed at once and nothing reaches Celery or the network.
- `FIXTURES`: loads docs/bot_contract/*.json, shared with the bot's test suite.

Import the fixtures into a conftest.py:  from api.tests.botkit import *  # noqa
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from djmoney.money import Money
from rest_framework.test import APIClient

from core.bot_signing import HEADER_ACTOR, HEADER_NONCE, HEADER_SIG, HEADER_TS, sign

TEST_TOKEN = "123456:TEST-BOT-TOKEN"
CONTRACT_DIR = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"


def load_fixture(name: str):
    """docs/bot_contract/<name> (the repo-level docs/ folder is not inside the backend
    image: tests that need it are skipped there; mount it at /docs to run them)."""
    path = CONTRACT_DIR / name
    if not path.exists():
        pytest.skip("docs/bot_contract is not available (mount ./docs at /docs)")
    return json.loads(path.read_text(encoding="utf-8"))


class Events(list):
    """Envelopes in the order they were emitted."""

    def names(self) -> list[str]:
        return [e["event"] for e in self]

    def of(self, event: str) -> list[dict]:
        return [e["data"] for e in self if e["event"] == event]

    def one(self, event: str) -> dict:
        found = self.of(event)
        assert len(found) == 1, f"{event}: expected 1, got {len(found)} ({self.names()})"
        return found[0]


class BotClient:
    """The bot service as seen by the backend."""

    def __init__(self):
        self.http = APIClient()
        self.token = TEST_TOKEN
        self.base = "/api/v1/bot/"

    def headers(self, method, path, actor, body: bytes, ts=None, nonce=None):
        if ts is None:
            # every request needs a fresh signature (replays are refused): walk back in time
            self._n = getattr(self, "_n", 0) % 250 + 1
            ts = int(time.time()) - self._n
        nonce = uuid.uuid4().hex if nonce is None else nonce
        return {
            "HTTP_" + HEADER_NONCE.upper().replace("-", "_"): nonce,
            "HTTP_" + HEADER_TS.upper().replace("-", "_"): str(ts),
            "HTTP_" + HEADER_ACTOR.upper().replace("-", "_"): "" if actor is None else str(actor),
            "HTTP_"
            + HEADER_SIG.upper().replace("-", "_"): sign(
                ts, method, path, actor, body, token=self.token, nonce=nonce
            ),
        }

    def call(self, method, path, actor=None, json_body=None, files=None, form=None, **tamper):
        """path is relative to /api/v1/bot/ (may carry a query string)."""
        full = self.base + path
        if files is not None:
            body = encode_multipart(BOUNDARY, {**(form or {}), **files})
            content_type = MULTIPART_CONTENT
        elif json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode()
            content_type = "application/json"
        else:
            body, content_type = b"", "application/json"
        ts = None
        if "ts_offset" in tamper:
            ts = int(time.time()) + tamper.pop("ts_offset")
        h = self.headers(method, full, tamper.pop("sign_actor", actor), body, ts)
        if "actor_header" in tamper:
            h["HTTP_X_BOT_ACTOR"] = str(tamper.pop("actor_header"))
        if tamper.pop("tamper_body", None):
            body = body + b" "
        return self.http.generic(
            method,
            full,
            data=body,
            content_type=content_type,
            **h,
        )

    def get(self, path, actor=None, **kw):
        return self.call("GET", path, actor, **kw)

    def post(self, path, actor=None, data=None, **kw):
        return self.call("POST", path, actor, json_body={} if data is None else data, **kw)

    def put(self, path, actor=None, data=None, **kw):
        return self.call("PUT", path, actor, json_body={} if data is None else data, **kw)

    def patch(self, path, actor=None, data=None, **kw):
        return self.call("PATCH", path, actor, json_body={} if data is None else data, **kw)

    def delete(self, path, actor=None, **kw):
        return self.call("DELETE", path, actor, **kw)


class FakeRedis:
    """Just enough of redis-py for the replay cache."""

    def __init__(self):
        self.keys = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


@pytest.fixture(autouse=True)
def fake_replay_cache(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("api.authentication._redis", lambda: fake)
    return fake


@pytest.fixture
def bot_client(settings):
    settings.TELEGRAM_BOT_TOKEN = TEST_TOKEN
    return BotClient()


@pytest.fixture
def bot_events(monkeypatch, settings):
    """Every emit() lands in the returned list; no Celery, no HTTP."""
    settings.TELEGRAM_BOT_TOKEN = TEST_TOKEN
    events = Events()
    monkeypatch.setattr("core.bot_notify.transaction.on_commit", lambda fn, *a, **k: fn())
    monkeypatch.setattr("core.tasks.notify_bot.delay", lambda env: events.append(env))
    return events


@pytest.fixture
def contract():
    return load_fixture


@pytest.fixture
def members(db):
    """100 boss (admin), 200 Ali (staff), 300 Vali (staff, bonus receiver)."""
    from oauth.models import TelegramMember

    boss = TelegramMember.objects.create(telegram_id=100, name="Rahbar", role="admin")
    ali = TelegramMember.objects.create(telegram_id=200, name="Ali", role="staff")
    vali = TelegramMember.objects.create(
        telegram_id=300, name="Vali", role="staff", is_bonus_receiver=True
    )
    return boss, ali, vali


@pytest.fixture
def site_order(db, db_client, default_factory):
    """Order 406, 1000 USD, 400 USD paid, in production."""
    from order.models import Order

    return Order.objects.create(
        order_number=406,
        client=db_client,
        reception_date=date.today(),
        end_date=date.today() + timedelta(days=20),
        address="Chilonzor",
        factory=default_factory,
        price=Money(1000, "USD"),
        lost_money=Money(400, "USD"),
        status="working",
    )
