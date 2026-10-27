"""backend -> bot delivery: core.bot_notify (emit / send_event_sync / fetch_file) and the
Celery task core.tasks.notify_bot."""

import json

import pytest
import requests

from core import bot_notify, bot_signing
from core.bot_notify import BotUnavailable, make_envelope
from core.tasks import notify_bot

TOKEN = "123456:TEST-BOT-TOKEN"


class Resp:
    def __init__(self, status=200, body=None, content=b"", ctype="application/json"):
        self.status_code = status
        self._body = body if body is not None else {}
        self.content = content
        self.headers = {"Content-Type": ctype}

    def json(self):
        if self._body is None:
            raise ValueError
        return self._body


@pytest.fixture
def server(settings):
    settings.TELEGRAM_BOT_TOKEN = TOKEN
    settings.TELEGRAM_BOT_SERVER = "http://bot:80"


def test_envelope_is_json_safe_and_has_an_id():
    from datetime import date
    from decimal import Decimal

    env = make_envelope("finance.x", {"amount": Decimal("1.50"), "day": date(2026, 10, 27)})
    assert env["event"] == "finance.x" and len(env["id"]) == 36
    assert env["data"] == {"amount": "1.50", "day": "2026-10-27"}
    assert make_envelope("a", {})["id"] != make_envelope("a", {})["id"]


def test_retries_connection_errors_and_5xx_with_the_same_envelope_id(server, monkeypatch):
    seen = []

    def fake_post(url, data=None, headers=None, timeout=None):
        seen.append((url, json.loads(data), headers, data))
        if len(seen) == 1:
            raise requests.ConnectionError("down")
        if len(seen) == 2:
            return Resp(502)
        return Resp(200, {"ok": True, "delivered": []})

    monkeypatch.setattr("core.bot_notify.requests.post", fake_post)
    env = make_envelope("finance.operation_created", {"balance": "1.00"})
    result = notify_bot.apply(args=[env])
    assert result.get() is True
    assert len(seen) == 3
    assert {s[1]["id"] for s in seen} == {env["id"]}  # the bot dedups on this
    url, _, headers, raw = seen[-1]
    assert url == "http://bot:80/notify"
    assert bot_signing.verify(
        headers["X-Bot-Signature"],
        headers["X-Bot-Timestamp"],
        "POST",
        "/notify",
        headers["X-Bot-Actor"],
        raw,
        token=TOKEN,
        nonce=headers["X-Bot-Nonce"],
    )


def test_a_4xx_is_never_retried(server, monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(
        "core.bot_notify.requests.post",
        lambda *a, **k: calls.append(1) or Resp(400, {"detail": "unknown event"}),
    )
    env = make_envelope("nope", {})
    assert notify_bot.apply(args=[env]).get() is False
    assert len(calls) == 1 and "unknown event" in caplog.text


def test_gives_up_after_the_retry_limit(server, monkeypatch):
    calls = []

    def always_down(*a, **k):
        calls.append(1)
        raise requests.ConnectionError("down")

    monkeypatch.setattr("core.bot_notify.requests.post", always_down)
    result = notify_bot.apply(args=[make_envelope("x", {})])
    assert result.failed() and len(calls) == notify_bot.max_retries + 1


def test_without_a_bot_server_nothing_is_sent(settings, monkeypatch):
    settings.TELEGRAM_BOT_SERVER = None
    monkeypatch.setattr("core.bot_notify.requests.post", lambda *a, **k: pytest.fail("sent"))
    assert notify_bot.apply(args=[make_envelope("x", {})]).get() is False


@pytest.mark.django_db
def test_hr_delivery_results_update_can_dm(server, monkeypatch, group):
    from hr import services as S
    from hr.models import Employee

    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    delivered = [
        {"chat_id": 500, "ok": False, "blocked": True, "error_code": 403},
        {"chat_id": -100777, "ok": True, "blocked": False},
    ]
    monkeypatch.setattr(
        "core.bot_notify.requests.post",
        lambda *a, **k: Resp(200, {"ok": True, "delivered": delivered}),
    )
    notify_bot.apply(args=[make_envelope("hr.day_report", {})])
    assert Employee.objects.get(telegram_id=500).can_dm is False
    monkeypatch.setattr(
        "core.bot_notify.requests.post",
        lambda *a, **k: Resp(200, {"ok": True, "delivered": [{"chat_id": 500, "ok": True}]}),
    )
    notify_bot.apply(args=[make_envelope("finance.x", {})])  # not an hr event: untouched
    assert Employee.objects.get(telegram_id=500).can_dm is False
    notify_bot.apply(args=[make_envelope("hr.ask_eta", {})])
    assert Employee.objects.get(telegram_id=500).can_dm is True


def test_send_event_sync_returns_the_answer_or_raises(server, monkeypatch):
    monkeypatch.setattr(
        "core.bot_notify.requests.post",
        lambda *a, **k: Resp(200, {"ok": True, "delivered": [{"chat_id": 1, "ok": True}]}),
    )
    assert bot_notify.send_event_sync("hr.ask_eta", {"employee": {}})["delivered"][0]["ok"] is True
    monkeypatch.setattr("core.bot_notify.requests.post", lambda *a, **k: Resp(503))
    with pytest.raises(BotUnavailable):
        bot_notify.send_event_sync("hr.ask_eta", {})

    def boom(*a, **k):
        raise requests.Timeout("slow")

    monkeypatch.setattr("core.bot_notify.requests.post", boom)
    with pytest.raises(BotUnavailable):
        bot_notify.send_event_sync("hr.ask_eta", {})
    monkeypatch.setattr(
        "core.bot_notify.requests.post", lambda *a, **k: Resp(400, {"detail": "bad"})
    )
    assert bot_notify.send_event_sync("hr.ask_eta", {})["ok"] is False


@pytest.mark.django_db
def test_emit_survives_a_broken_broker(monkeypatch, django_capture_on_commit_callbacks, caplog):
    def broken(env):
        raise OSError("redis is down")

    monkeypatch.setattr("core.tasks.notify_bot.delay", broken)
    with django_capture_on_commit_callbacks(execute=True):
        bot_notify.emit("finance.x", {})
    assert "could not queue" in caplog.text


@pytest.mark.django_db
def test_emit_waits_for_the_commit_and_queues_one_envelope(
    monkeypatch, django_capture_on_commit_callbacks
):
    sent = []
    monkeypatch.setattr("core.tasks.notify_bot.delay", lambda env: sent.append(env))
    with django_capture_on_commit_callbacks(execute=False) as cbs:
        eid = bot_notify.emit("finance.x", {"a": 1})
        assert sent == []
    assert len(cbs) == 1
    cbs[0]()
    assert sent == [{"id": eid, "event": "finance.x", "data": {"a": 1}}]


def test_fetch_file(server, monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers)
        return Resp(200, content=b"\xff\xd8 jpeg", ctype="image/jpeg")

    monkeypatch.setattr("core.bot_notify.requests.get", fake_get)
    assert bot_notify.fetch_file("AgAC-xyz_1") == (b"\xff\xd8 jpeg", "image/jpeg")
    assert seen["url"] == "http://bot:80/files/AgAC-xyz_1"
    assert bot_signing.verify(
        seen["headers"]["X-Bot-Signature"],
        seen["headers"]["X-Bot-Timestamp"],
        "GET",
        "/files/AgAC-xyz_1",
        "",
        b"",
        token=TOKEN,
        nonce=seen["headers"]["X-Bot-Nonce"],
    )
    monkeypatch.setattr("core.bot_notify.requests.get", lambda *a, **k: Resp(404))
    assert bot_notify.fetch_file("x") is None
    assert bot_notify.fetch_file("") is None

    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("core.bot_notify.requests.get", boom)
    assert bot_notify.fetch_file("x") is None
