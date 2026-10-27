"""HR (davomat) test kit: a fixed clock, a boss, a watched group. Imported by
hr/tests/conftest.py and api/tests/conftest.py."""

from datetime import datetime

import pytest

from hr import services as S

GROUP = -100777


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


def ts(dt: datetime) -> int:
    return int(dt.replace(tzinfo=S.TZ).timestamp())


@pytest.fixture
def group(db, boss):
    from hr.models import WorkGroup

    return WorkGroup.objects.create(chat_id=GROUP, title="Zavod")


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    """hr settings are cached for a few seconds per process - never across tests."""
    S.clear_settings_cache()
    yield
    S.clear_settings_cache()
