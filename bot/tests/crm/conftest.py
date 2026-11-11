"""Kit of the CRM bot tests: the REAL build_dispatcher() (router order, Redis FSM, actor
middleware) over a fake Bot API session and a scripted backend."""

from __future__ import annotations

import itertools

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
)
from aiogram.types import Chat, Message, Update, User

TOKEN = "123456:TEST-BOT-TOKEN"
UID = 555
_ids = itertools.count(100)


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

    def of(self, cls):
        return [c for c in self.calls if isinstance(c, cls)]

    def sent(self):
        return self.of(SendMessage)

    def texts(self):
        return [c.text for c in self.sent()]

    def last(self) -> SendMessage:
        return self.sent()[-1]

    def edits(self):
        return self.of(EditMessageText)

    def answers(self):
        return self.of(AnswerCallbackQuery)

    def cleared(self):
        return self.of(EditMessageReplyMarkup)


def buttons(markup):
    """(text, callback_data, url) of an inline keyboard."""
    if markup is None:
        return []
    return [(b.text, b.callback_data, b.url) for row in markup.inline_keyboard for b in row]


def cbs(markup):
    return [c for _, c, _ in buttons(markup) if c]


class Backend:
    """Scripted backend: routes[(METHOD, path)] = value | Exception | callable(json, params)."""

    def __init__(self):
        self.routes = {}
        self.calls = []
        self.who = {
            "finance_member": None,
            "hr": {"employee": None, "is_admin": False},
            "crm": {"can_add_lead": True},
        }

    async def request(
        self, method, path, *, actor=None, json=None, params=None, files=None, raw=False
    ):
        self.calls.append((method, path, json, params))
        if path == "whoami/":
            return self.who
        if path == "hr/private-text/":
            return {"handled": False, "outcome": None, "data": {}}
        v = self.routes.get((method, path), AssertionError(f"unexpected call {method} {path}"))
        if isinstance(v, Exception):
            raise v
        return v(json, params) if callable(v) else v

    def to(self, path):
        return [c for c in self.calls if c[1] == path]


class Env:
    def __init__(self, dp, bot, session, backend):
        self.dp, self.bot, self.session, self.backend = dp, bot, session, backend

    async def feed(self, **kw):
        return await self.dp.feed_update(
            self.bot, Update.model_validate({"update_id": next(_ids), **kw})
        )

    def _msg(self, uid=UID, **extra):
        return {
            "message_id": next(_ids),
            "date": 1700000000,
            "chat": {"id": uid, "type": "private"},
            "from": {"id": uid, "is_bot": False, "first_name": "Aziz", "username": "aziz"},
            **extra,
        }

    async def text(self, text, uid=UID):
        return await self.feed(message=self._msg(uid, text=text))

    async def forward(
        self, text="Salom, divan kerak", name="Karim Aliyev", username="karim", uid=UID
    ):
        origin = {
            "type": "user",
            "date": 1699990000,
            "sender_user": {"id": 99, "is_bot": False, "first_name": name, "username": username},
        }
        if username is None:
            origin = {"type": "hidden_user", "date": 1699990000, "sender_user_name": name}
        extra = {"forward_origin": origin}
        if text is not None:
            extra["text"] = text
        else:
            extra["photo"] = [{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}]
        return await self.feed(message=self._msg(uid, **extra))

    async def contact(self, phone="998901234567", first="Dilshod", last="Rustamov", uid=UID):
        c = {"phone_number": phone, "first_name": first}
        if last:
            c["last_name"] = last
        return await self.feed(message=self._msg(uid, contact=c))

    async def cb(self, data, uid=UID, text="old", markup=None):
        return await self.feed(
            callback_query={
                "id": str(next(_ids)),
                "chat_instance": "x",
                "from": {"id": uid, "is_bot": False, "first_name": "Aziz"},
                "data": data,
                "message": {
                    "message_id": 9,
                    "date": 1700000000,
                    "chat": {"id": uid, "type": "private"},
                    "text": text,
                    **({"reply_markup": markup} if markup else {}),
                },
            }
        )

    async def state(self, uid=UID):
        from aiogram.fsm.storage.base import StorageKey

        key = StorageKey(bot_id=self.bot.id, chat_id=uid, user_id=uid)
        return await self.dp.storage.get_state(key)

    async def set_state(self, state, uid=UID, **data):
        from aiogram.fsm.storage.base import StorageKey

        key = StorageKey(bot_id=self.bot.id, chat_id=uid, user_id=uid)
        await self.dp.storage.set_state(key, state)
        await self.dp.storage.set_data(key, data)


@pytest.fixture
def env(monkeypatch):
    import bot as botpkg
    from bot.backend.client import backend as real
    from bot.common import link, start
    from bot.crm import router as crm
    from bot.finance import router as fin
    from bot.hr import group_router, private_router
    from bot.metering import router as metering
    from bot.offer import router as offer
    from bot.painter import router as painter
    from bot.rover import router as rover
    from bot.warehouse import ex_keeper_router as wh_ex
    from bot.warehouse import fallback_router as wh_fallback
    from bot.warehouse import router as wh

    for r in (
        group_router,
        link.router,
        start.router,
        metering,
        offer,
        rover,
        painter,
        wh,
        wh_ex,
        crm,
        private_router,
        wh_fallback,
        fin,
    ):
        r._parent_router = None
    be = Backend()
    monkeypatch.setattr(real, "request", be.request)
    dp = botpkg.build_dispatcher()
    session = FakeSession()
    return Env(dp, Bot(TOKEN, session=session), session, be)
