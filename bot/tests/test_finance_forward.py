"""The finance router: what is forwarded to the backend and what still reaches the
site handler. Runs the real aiogram Dispatcher; only the HTTP call and the replies
are mocked."""

import hashlib
import hmac
import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
os.environ.setdefault("BASE_SITE", "https://example.com")

import pytest  # noqa: E402
from aiogram.types import Update  # noqa: E402

import bot.finance as finance  # noqa: E402
from bot import bot as tg_bot  # noqa: E402
from bot import dp  # noqa: E402


def msg_update(text=None, chat_type="private", uid=222, photo=False):
    m = {
        "message_id": 1,
        "date": 0,
        "chat": {"id": uid, "type": chat_type},
        "from": {"id": uid, "is_bot": False, "first_name": "A"},
    }
    if text is not None:
        m["text"] = text
    if photo:
        m["photo"] = [{"file_id": "F", "file_unique_id": "U", "width": 1, "height": 1}]
    return Update.model_validate({"update_id": 1, "message": m}, context={"bot": tg_bot})


def cb_update(data="save"):
    return Update.model_validate(
        {
            "update_id": 2,
            "callback_query": {
                "id": "q",
                "chat_instance": "c",
                "data": data,
                "from": {"id": 222, "is_bot": False, "first_name": "A"},
                "message": {
                    "message_id": 5,
                    "date": 0,
                    "chat": {"id": 222, "type": "private"},
                    "text": "x",
                },
            },
        },
        context={"bot": tg_bot},
    )


@pytest.fixture
def answers():
    with (
        patch("aiogram.types.Message.answer", new=AsyncMock()) as answer,
        patch("aiogram.types.Message.reply", new=AsyncMock()) as reply,
    ):
        yield answer, reply


async def test_finance_message_handled_by_backend_skips_site_reply(answers):
    with patch.object(finance, "forward", new=AsyncMock(return_value=True)) as fwd:
        await dp.feed_update(tg_bot, msg_update("➖ Chiqim"))
    fwd.assert_awaited_once()
    assert not answers[0].await_count and not answers[1].await_count


async def test_not_handled_falls_back_to_site_greeting(answers):
    with patch.object(finance, "forward", new=AsyncMock(return_value=False)):
        await dp.feed_update(tg_bot, msg_update("salom"))
    answers[0].assert_awaited_once()


async def test_site_linking_start_is_never_forwarded(answers):
    with (
        patch.object(finance, "forward", new=AsyncMock(return_value=True)) as fwd,
        patch("bot.User.get_or_none", new=AsyncMock(return_value=None)),
    ):
        await dp.feed_update(tg_bot, msg_update("/start 42"))
    fwd.assert_not_awaited()
    answers[1].assert_awaited_once()  # «Профиль топилмади»


async def test_photo_without_text_does_not_crash_site_handler(answers):
    with patch.object(finance, "forward", new=AsyncMock(return_value=False)):
        await dp.feed_update(tg_bot, msg_update(photo=True))
    answers[0].assert_awaited_once()


async def test_group_messages_are_not_forwarded(answers):
    with patch.object(finance, "forward", new=AsyncMock(return_value=True)) as fwd:
        await dp.feed_update(tg_bot, msg_update("x", chat_type="group", uid=-5))
    fwd.assert_not_awaited()


async def test_callbacks_are_forwarded():
    with patch.object(finance, "forward", new=AsyncMock(return_value=True)) as fwd:
        await dp.feed_update(tg_bot, cb_update())
    fwd.assert_awaited_once()


def test_webhook_receives_button_presses():
    assert {"message", "callback_query"} <= set(dp.resolve_used_update_types())


def test_signature_matches_backend_formula():
    body = b'{"update_id": 1}'
    expected = hmac.new(os.environ["BOT_TOKEN"].encode(), body, hashlib.sha256).hexdigest()
    assert finance.sign(body) == expected


async def test_forward_posts_signed_update_to_backend():
    captured = {}

    class Resp:
        status = 200

        async def json(self):
            return {"handled": True}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Session:
        def __init__(self, *a, **k):
            pass

        def post(self, url, data, headers):
            captured.update(url=url, data=data, headers=headers)
            return Resp()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    with patch.object(finance.aiohttp, "ClientSession", Session):
        assert await finance.forward(msg_update("hi")) is True
    assert captured["url"].endswith("/api/v1/finance/telegram/update/")
    assert captured["headers"]["X-Bot-Signature"] == finance.sign(captured["data"])
    import json

    sent = json.loads(captured["data"])
    assert sent["message"]["from"]["id"] == 222 and "from_user" not in sent["message"]


async def test_backend_down_falls_back():
    class Boom:
        def __init__(self, *a, **k):
            raise finance.aiohttp.ClientError("down")

    with patch.object(finance.aiohttp, "ClientSession", Boom):
        assert await finance.forward(msg_update("hi")) is False
