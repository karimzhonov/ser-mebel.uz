import asyncio
from types import SimpleNamespace

import pytest

from bot.common.middlewares import DedupMiddleware, UserLockMiddleware


async def test_dedup_drops_second_and_reprocesses_after_error():
    calls = []

    async def ok(event, data):
        calls.append(1)
        return "r"

    async def boom(event, data):
        raise RuntimeError

    mw = DedupMiddleware()
    ev = SimpleNamespace(update_id=7)
    assert await mw(ok, ev, {}) == "r"
    assert await mw(ok, ev, {}) is None
    assert len(calls) == 1
    ev2 = SimpleNamespace(update_id=8)
    with pytest.raises(RuntimeError):
        await mw(boom, ev2, {})
    assert await mw(ok, ev2, {}) == "r"


async def test_user_lock_serializes():
    order = []

    async def h(event, data):
        order.append("in")
        await asyncio.sleep(0.05)
        order.append("out")

    mw = UserLockMiddleware()
    data = {"event_from_user": SimpleNamespace(id=5)}
    await asyncio.gather(mw(h, None, dict(data)), mw(h, None, dict(data)))
    assert order == ["in", "out", "in", "out"]
