"""Test kit of the davomat (HR) bot: a fake Bot API session, a fake BackendClient and a
small Dispatcher with only the HR routers (plus a stand-in for the finance router), so the
real filters, FSM destiny and SkipHandler behaviour are exercised end to end."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import GetChatMember, GetMe, SendMessage
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberMember,
    Message,
    Update,
    User,
)

import bot.hr as hr
from bot.backend.client import backend
from bot.common.actor import Actor

FIXTURES = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ fake Bot API
class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list = []
        self.fail: dict[int, Exception] = {}  # chat_id -> error raised by sendMessage
        self.members: dict[tuple[int, int], str] = {}  # (chat, user) -> status
        self.me_reads_all = False
        self._mid = 1000

    async def close(self):  # pragma: no cover
        pass

    async def stream_content(self, *a, **kw):  # pragma: no cover
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            if method.chat_id in self.fail:
                raise self.fail[method.chat_id]
            self._mid += 1
            return Message(
                message_id=self._mid,
                date=datetime.now(),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        if isinstance(method, GetMe):
            return User(
                id=42,
                is_bot=True,
                first_name="bot",
                username="sermebel_bot",
                can_read_all_group_messages=self.me_reads_all,
            )
        if isinstance(method, GetChatMember):
            st = self.members.get((method.chat_id, method.user_id), "left")
            user = User(id=method.user_id, is_bot=False, first_name="x")
            if st == "administrator":
                from aiogram.types import ChatMemberAdministrator

                return ChatMemberAdministrator(
                    status="administrator",
                    user=user,
                    can_be_edited=False,
                    is_anonymous=False,
                    can_manage_chat=True,
                    can_delete_messages=True,
                    can_manage_video_chats=True,
                    can_restrict_members=True,
                    can_promote_members=False,
                    can_change_info=True,
                    can_invite_users=True,
                    can_post_stories=False,
                    can_edit_stories=False,
                    can_delete_stories=False,
                )
            if st == "left":
                from aiogram.types import ChatMemberLeft

                return ChatMemberLeft(status="left", user=user)
            return ChatMemberMember(status="member", user=user)
        return True

    # ---- helpers for assertions
    def of(self, cls, chat_id=None) -> list:
        return [
            c
            for c in self.calls
            if isinstance(c, cls) and (chat_id is None or getattr(c, "chat_id", None) == chat_id)
        ]

    def sent(self, chat_id=None) -> list[SendMessage]:
        return self.of(SendMessage, chat_id)

    def texts(self, chat_id=None) -> list[str]:
        return [c.text for c in self.sent(chat_id)]


def buttons(markup) -> list[tuple[str, str | None, str | None]]:
    """(text, callback_data, url) of every button of an inline keyboard."""
    if markup is None:
        return []
    return [(b.text, b.callback_data, b.url) for row in markup.inline_keyboard for b in row]


# ------------------------------------------------------------------ fake backend
@dataclass
class Call:
    method: str
    path: str
    actor: Any
    json: Any
    params: Any


@dataclass
class FakeBackend:
    routes: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def on(self, method: str, path: str, response=None):
        """response: a value, an Exception to raise, or a callable(call) -> value."""
        self.routes[(method, path)] = response

    async def request(self, method, path, *, actor=None, json=None, params=None, files=None, raw=False):
        call = Call(method, path, actor, json, params)
        self.calls.append(call)
        if (method, path) not in self.routes:
            if path == "hr/dm-status/":
                return None
            raise AssertionError(f"unexpected backend call {method} {path} {json}")
        r = self.routes[(method, path)]
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(call)
        return r

    def to(self, path: str, method: str | None = None) -> list[Call]:
        return [c for c in self.calls if c.path == path and (method is None or c.method == method)]

    def paths(self) -> list[str]:
        return [c.path for c in self.calls]


@pytest.fixture
def fake_backend(monkeypatch):
    fb = FakeBackend()
    monkeypatch.setattr(backend, "request", fb.request)
    return fb


@pytest.fixture
def session():
    return FakeSession()


@pytest.fixture
def tgbot(session, monkeypatch):
    b = Bot("42:TEST", session=session)
    monkeypatch.setattr(hr.api, "get_bot", lambda: b)
    return b


# ------------------------------------------------------------------ dispatcher
class Finance:
    """Stand-in for the finance router: records what the HR routers let through."""

    def __init__(self):
        self.messages: list[str] = []
        self.callbacks: list[str] = []


_finance = Finance()
_state: dict[str, Any] = {"actor": None}


def _detach(router: Router) -> None:
    parent = router.parent_router
    if parent is not None:
        parent.sub_routers.remove(router)
        router._parent_router = None  # noqa: SLF001


def _build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    async def actor_mw(handler, event, data):
        data["actor"] = _state["actor"]
        return await handler(event, data)

    dp.message.outer_middleware(actor_mw)
    dp.callback_query.outer_middleware(actor_mw)
    fin = Router(name="finance_stub")

    @fin.message(F.text)
    async def _msg(message: Message):
        _finance.messages.append(message.text)

    @fin.callback_query()
    async def _cb(cb: CallbackQuery):
        _finance.callbacks.append(cb.data)
        await cb.answer()

    for r in (hr.group_router, hr.private_router):
        _detach(r)
    dp.include_router(hr.group_router)
    dp.include_router(hr.private_router)
    dp.include_router(fin)
    return dp


@pytest.fixture(scope="session")
def _dp():
    return _build_dispatcher()


@pytest.fixture
def dp(_dp):
    _dp.fsm.storage.storage.clear()
    _finance.messages.clear()
    _finance.callbacks.clear()
    _state["actor"] = None
    return _dp


@pytest.fixture
def finance():
    return _finance


def make_actor(
    tg=777001, employee: dict | None = None, admin: bool = False, member: dict | None = None
) -> Actor:
    return Actor(
        user=User(id=tg, is_bot=False, first_name="T"),
        member=member,
        hr={"employee": employee, "is_admin": admin},
    )


@pytest.fixture
def set_actor():
    def _set(actor):
        _state["actor"] = actor

    return _set


def _user(uid: int, name: str = "Dilmurod") -> dict:
    return {"id": uid, "is_bot": False, "first_name": name, "username": "u%d" % uid}


class Feeder:
    def __init__(self, dp, bot):
        self.dp, self.bot, self._uid = dp, bot, 1

    async def _feed(self, **kw):
        self._uid += 1
        return await self.dp.feed_update(self.bot, Update.model_validate({"update_id": self._uid, **kw}))

    async def private(self, text: str, uid: int = 777001):
        return await self._feed(
            message={
                "message_id": self._uid,
                "date": 1790496000,
                "chat": {"id": uid, "type": "private"},
                "from": _user(uid),
                "text": text,
            }
        )

    async def group(self, chat_id: int = -1001234567890, uid: int = 777001, **extra):
        m = {
            "message_id": 55,
            "date": 1790496000,
            "chat": {"id": chat_id, "type": "supergroup", "title": "Chilonzor filiali"},
            "from": _user(uid),
            **extra,
        }
        return await self._feed(message=m)

    async def callback(self, data: str, uid: int = 777001):
        return await self._feed(
            callback_query={
                "id": "cb1",
                "from": _user(uid),
                "chat_instance": "ci",
                "data": data,
                "message": {
                    "message_id": 9,
                    "date": 1790496000,
                    "chat": {"id": uid, "type": "private"},
                    "text": "old",
                },
            }
        )

    async def chat_member(self, kind: str = "chat_member", status: str = "left", uid: int = 777001):
        return await self._feed(
            **{
                kind: {
                    "chat": {"id": -1001234567890, "type": "supergroup", "title": "Chilonzor filiali"},
                    "from": _user(1),
                    "date": 1790496000,
                    "old_chat_member": {"status": "member", "user": _user(uid)},
                    "new_chat_member": {"status": status, "user": _user(uid)},
                }
            }
        )


@pytest.fixture
def feed(dp, tgbot):
    return Feeder(dp, tgbot)


EMPLOYEE = fixture("dto.employee.1")
