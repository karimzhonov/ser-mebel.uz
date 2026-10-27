import os

os.environ.setdefault("BOT_TOKEN", "123456:TEST-BOT-TOKEN")
os.environ.setdefault("BASE_SITE", "https://example.com")

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402

from bot.common.rds import set_redis  # noqa: E402


@pytest.fixture(autouse=True)
def fake_redis():
    r = fakeredis.aioredis.FakeRedis()
    set_redis(r)
    return r
