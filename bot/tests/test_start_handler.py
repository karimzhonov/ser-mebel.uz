import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
os.environ.setdefault("BASE_SITE", "https://example.com")

import pytest

from bot import handle_any_message


def make_message(text: str, chat_id: int = 111, from_user_id: int = 222):
    message = MagicMock()
    message.text = text
    message.chat.id = chat_id
    message.from_user.id = from_user_id
    message.reply = AsyncMock()
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_start_with_valid_user_links_telegram_id():
    message = make_message("/start 42")
    user = MagicMock()
    user.save = AsyncMock()

    with patch("bot.User.get_or_none", new=AsyncMock(return_value=user)):
        await handle_any_message(message)

    assert user.telegram_id == 222
    user.save.assert_awaited_once()
    message.reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_with_unknown_user_replies_without_crashing():
    message = make_message("/start 999999")

    with patch("bot.User.get_or_none", new=AsyncMock(return_value=None)):
        await handle_any_message(message)

    message.reply.assert_awaited_once()
    args, kwargs = message.reply.call_args
    assert "топилмади" in kwargs.get("text", "")


@pytest.mark.asyncio
async def test_start_with_non_numeric_payload_replies_without_crashing():
    message = make_message("/start not-a-number")

    with patch("bot.User.get_or_none", new=AsyncMock(return_value=None)) as get_or_none:
        await handle_any_message(message)

    get_or_none.assert_not_awaited()
    message.reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_start_command_sends_default_answer():
    message = make_message("hello")

    await handle_any_message(message)

    message.answer.assert_awaited_once()
