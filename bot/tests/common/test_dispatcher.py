"""Real Updates through the real build_dispatcher(): router order, the outer actor
middleware (filters must see `actor`), HR vs finance, silence for strangers."""

import json
from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User

FIX = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"
TOKEN = "123456:TEST-BOT-TOKEN"


def fx(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):  # pragma: no cover
        pass

    async def stream_content(self, *a, **kw):  # pragma: no cover
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=700 + len(self.calls),
                date=0,
                chat=Chat(id=method.chat_id, type="private"),
                from_user=User(id=1, is_bot=True, first_name="bot"),
                text=method.text,
            )
        return True

    def sent(self):
        return [c.text for c in self.calls if isinstance(c, SendMessage)]


@pytest.fixture
def env(monkeypatch):
    import bot as botpkg
    from bot.backend.client import backend
    from bot.common import link, start
    from bot.finance import router as fin
    from bot.hr import group_router, private_router

    for r in (group_router, link.router, start.router, private_router, fin):
        r._parent_router = None  # routers are module singletons: allow a fresh Dispatcher
    dp = botpkg.build_dispatcher()
    session = FakeSession()
    bot = Bot(TOKEN, session=session)
    state = {"who": {"finance_member": None, "hr": {"employee": None, "is_admin": False}}}
    calls = []

    async def request(method, path, *, actor=None, json=None, params=None, files=None, raw=False):
        calls.append((method, path, json))
        if path == "whoami/":
            return state["who"]
        if path == "hr/private-text/":
            return {"handled": False, "outcome": None, "data": {}}
        return {}

    monkeypatch.setattr(backend, "request", request)
    return dp, bot, session, state, calls


_uid = [10]


def msg_update(text, uid=555):
    _uid[0] += 1
    return Update.model_validate(
        {
            "update_id": _uid[0],
            "message": {
                "message_id": 1,
                "date": 1700000000,
                "chat": {"id": uid, "type": "private"},
                "from": {"id": uid, "is_bot": False, "first_name": "A"},
                "text": text,
            },
        }
    )


def cb_update(data, uid=555):
    _uid[0] += 1
    return Update.model_validate(
        {
            "update_id": _uid[0],
            "callback_query": {
                "id": "1",
                "chat_instance": "x",
                "from": {"id": uid, "is_bot": False, "first_name": "A"},
                "data": data,
                "message": {
                    "message_id": 9,
                    "date": 1700000000,
                    "chat": {"id": uid, "type": "private"},
                    "text": "old",
                },
            },
        }
    )


async def test_member_text_reaches_finance(env):
    dp, bot, session, state, calls = env
    state["who"]["finance_member"] = fx("dto.member.1")
    await dp.feed_update(bot, msg_update("/bekor"))
    assert session.sent() == ["Bekor qilindi."]


async def test_member_button_callback_works(env):
    dp, bot, session, state, calls = env
    state["who"]["finance_member"] = fx("dto.member.1")
    await dp.feed_update(bot, cb_update("noexp"))
    from aiogram.methods import EditMessageText

    edits = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert edits and "Qabul qilindi" in edits[0].text


async def test_hr_employee_plain_text_goes_to_hr_private_text(env):
    dp, bot, session, state, calls = env
    state["who"]["hr"]["employee"] = fx("dto.employee.1")
    await dp.feed_update(bot, msg_update("kech qolaman"))
    assert any(p == "hr/private-text/" for _, p, _ in calls)
    assert session.sent() == []  # handled=false and not a finance member: silence


async def test_stranger_text_gets_silence(env):
    dp, bot, session, state, calls = env
    await dp.feed_update(bot, msg_update("salom"))
    assert session.sent() == []
    assert [p for _, p, _ in calls] == ["whoami/"]


async def test_stranger_start_gets_join_screen(env):
    dp, bot, session, state, calls = env
    await dp.feed_update(bot, msg_update("/start"))
    assert len(session.sent()) == 1 and "Ro'yxatdan" in str(session.calls[0].reply_markup)


async def test_blocked_start_is_silent(env):
    dp, bot, session, state, calls = env
    state["who"]["finance_member"] = {**fx("dto.member.1"), "role": "blocked", "is_active_member": False}
    await dp.feed_update(bot, msg_update("/start"))
    assert session.sent() == []


async def test_link_start_goes_to_link(env):
    dp, bot, session, state, calls = env
    await dp.feed_update(bot, msg_update("/start u5_abcdef0123"))
    assert ("POST", "link/", {"token": "u5_abcdef0123", "telegram_id": 555}) in calls
    assert len(session.sent()) == 1


async def test_whoami_cached_and_dropped_after_write(env, fake_redis):
    dp, bot, session, state, calls = env
    await dp.feed_update(bot, msg_update("salom"))
    await dp.feed_update(bot, msg_update("salom"))
    assert [p for _, p, _ in calls].count("whoami/") == 1
    from bot.backend.client import _forget_whoami

    await _forget_whoami(555)
    await dp.feed_update(bot, msg_update("salom"))
    assert [p for _, p, _ in calls].count("whoami/") == 2
