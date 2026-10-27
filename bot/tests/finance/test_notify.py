import glob
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

import bot.finance  # noqa: F401  (registers the finance.* renderers)
from bot.notify.registry import dispatch, events

from .conftest import fx

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"


def fake_bot(fail=()):
    bot = MagicMock()

    async def send_message(chat_id, text, **kw):
        if chat_id in fail:
            raise TelegramForbiddenError(
                SendMessage(chat_id=chat_id, text=text), "Forbidden: bot was blocked by the user"
            )
        return SimpleNamespace(message_id=900)

    bot.send_message = AsyncMock(side_effect=send_message)
    bot.send_photo = AsyncMock(return_value=SimpleNamespace(message_id=1))
    bot.edit_message_text = AsyncMock()
    return bot


async def test_operation_created_channel_and_owner(be):
    env = fx("event.finance.operation_created")
    delivered = await dispatch(env, fake_bot())
    assert delivered and all(d["ok"] for d in delivered)
    d = env["data"]
    if d["notify_owner"]:
        assert d["owner_tg"] in {x["chat_id"] for x in delivered}


async def test_blocked_reported(be):
    env = fx("event.finance.daily_reminder")
    tg = env["data"]["member"]["telegram_id"]
    delivered = await dispatch(env, fake_bot(fail={tg}))
    assert delivered == [
        {"chat_id": tg, "ok": False, "message_id": None, "error_code": 403, "blocked": True}
    ]


async def test_request_created_posts_admin_messages(be):
    env = fx("event.finance.request_created")
    n = env["data"]["request"]["number"]
    be.routes[("POST", f"finance/requests/{n}/admin-messages/")] = None
    await dispatch(env, fake_bot())
    _, path, body, _ = be.calls[-1]
    assert path == f"finance/requests/{n}/admin-messages/"
    assert body["messages"] and all(len(p) == 2 for p in body["messages"])


async def test_every_finance_fixture_renders(be):
    for f in glob.glob(str(CONTRACT / "event.finance.*.json")):
        env = json.load(open(f, encoding="utf-8"))
        assert env["event"] in events(), env["event"]
        if env["event"] in ("finance.ready_card", "finance.month_excel"):
            continue  # need the backend (card.png / excel)
        n = env["data"].get("request", {}).get("number")
        if n:
            be.routes[("POST", f"finance/requests/{n}/admin-messages/")] = None
        await dispatch(env, fake_bot())
