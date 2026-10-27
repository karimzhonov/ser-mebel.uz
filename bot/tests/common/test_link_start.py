from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.backend.client import BackendDown, NotFound
from bot.common import link
from bot.common.actor import Actor


def msg(text):
    m = SimpleNamespace(text=text, chat=SimpleNamespace(id=1), from_user=SimpleNamespace(id=222))
    m.reply = AsyncMock()
    return m


def test_regex():
    assert link.LINK_RE.match("/start u5_abcdef0123")
    assert link.LINK_RE.match("/start 123")
    assert not link.LINK_RE.match("/start davomat")
    assert not link.LINK_RE.match("/start")


async def test_link_ok():
    m = msg("/start u5_abcdef0123")
    with patch.object(link.backend, "request", AsyncMock(return_value={"linked": True})) as rq:
        await link.link_account(m)
    rq.assert_awaited_once_with(
        "POST", "link/", json={"token": "u5_abcdef0123", "telegram_id": 222}
    )
    assert "уланди" in m.reply.call_args.args[0]


async def test_link_not_found_and_down():
    m = msg("/start 999")
    with patch.object(link.backend, "request", AsyncMock(side_effect=NotFound("x"))):
        await link.link_account(m)
    assert "топилмади" in m.reply.call_args.args[0]
    m = msg("/start 999")
    with patch.object(link.backend, "request", AsyncMock(side_effect=BackendDown("x"))):
        await link.link_account(m)
    assert "vaqtincha" in m.reply.call_args.args[0]


def actor(member=None, employee=None):
    return Actor(
        user=SimpleNamespace(id=1),
        member=member,
        hr={"employee": employee, "is_admin": False},
    )


async def run_start(a):
    from bot.common import start

    fin, hr_ = AsyncMock(return_value=True), AsyncMock(return_value=True)
    with patch.object(start, "finance_start", fin), patch.object(start, "employee_start", hr_):
        await start.start_plain(msg("/start"), None, a, None)
    return fin.await_count, hr_.await_count


async def test_start_precedence():
    member = {"role": "staff", "is_active_member": True}
    assert await run_start(actor(member=member, employee={"x": 1})) == (1, 0)
    assert await run_start(actor(employee={"x": 1})) == (0, 1)
    assert await run_start(actor()) == (1, 0)  # stranger: join screen
    assert await run_start(actor(member={"role": "blocked"})) == (0, 0)  # silence
    assert await run_start(actor(member={"role": "pending"})) == (1, 0)
