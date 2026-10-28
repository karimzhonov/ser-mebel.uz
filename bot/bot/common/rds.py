"""The shared Redis client (FSM storage, update dedup, per-user locks).

Tests replace it with `set_redis(fakeredis_client)`.
"""

from __future__ import annotations

from redis.asyncio import Redis

from config import REDIS_URL

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(REDIS_URL, decode_responses=False)
    return _redis


def set_redis(client) -> None:
    global _redis
    _redis = client
