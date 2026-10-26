import itertools
from datetime import datetime

import pytest

from accounting.tests.conftest import FakeTelegram, api, make_staff, site_order  # noqa: F401
from hr import services as S

GROUP = -100777


@pytest.fixture
def tg(monkeypatch, settings):
    settings.TELEGRAM_BOT_TOKEN = "123:TEST"
    fake = FakeTelegram()
    monkeypatch.setattr("accounting.telegram.api.call", fake)
    monkeypatch.setattr(
        "accounting.telegram.router._executor.submit", lambda fn, *a, **k: fn(*a, **k)
    )
    monkeypatch.setattr("accounting.telegram.router.close_old_connections", lambda: None)
    return fake


class Clock:
    """Fixed Tashkent time for the bot (S.now)."""

    def __init__(self, monkeypatch):
        self.t = datetime(2026, 10, 26, 8, 0)  # Monday
        monkeypatch.setattr("hr.services.now", lambda: self.t)

    def set(self, h, m=0, day=None):
        self.t = self.t.replace(hour=h, minute=m) if day is None else datetime(2026, 10, day, h, m)
        return self.t


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch)


@pytest.fixture
def boss(db):
    from oauth.models import TelegramMember

    return TelegramMember.objects.create(telegram_id=100, name="Rahbar", role="admin")


_upd = itertools.count(1)


def ts(dt: datetime) -> int:
    return int(dt.replace(tzinfo=S.TZ).timestamp())


def send_update(up: dict):
    from accounting.telegram.router import handle_update

    up["update_id"] = next(_upd)
    return handle_update(up)


def group_msg(uid, at: datetime, video=True, text=None, name="Jasur", chat=GROUP):
    m = {
        "message_id": next(_upd),
        "date": ts(at),
        "chat": {"id": chat, "type": "supergroup", "title": "Zavod"},
        "from": {"id": uid, "is_bot": False, "first_name": name},
    }
    if video:
        m["video_note"] = {"file_id": "VN"}
    if text:
        m["text"] = text
    return send_update({"message": m})


def private(uid, text, name="Jasur"):
    return send_update(
        {
            "message": {
                "message_id": next(_upd),
                "date": 0,
                "chat": {"id": uid, "type": "private"},
                "from": {"id": uid, "is_bot": False, "first_name": name},
                "text": text,
            }
        }
    )


def press(uid, data):
    return send_update(
        {
            "callback_query": {
                "id": "q",
                "from": {"id": uid, "is_bot": False, "first_name": "X"},
                "data": data,
                "message": {"message_id": 5, "chat": {"id": uid, "type": "private"}},
            }
        }
    )


@pytest.fixture
def group(db, tg, boss):
    from hr.models import WorkGroup

    return WorkGroup.objects.create(chat_id=GROUP, title="Zavod")


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    """hr settings are cached for a few seconds per process — never across tests."""
    S.clear_settings_cache()
    yield
    S.clear_settings_cache()
