"""A reminder follows its task: crm.task_due remembers the message, crm.task_closed /
crm.task_moved (task changed in the panel or by closing the lead) edit it."""

import copy
import glob
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import EditMessageText

import bot.crm  # noqa: F401
from bot.common.rds import get_redis
from bot.crm import texts as T
from bot.notify.registry import dispatch, events

from .test_notify_and_tasks import TASK_DUE

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"
KEY = "crm:msg:8"


def fake_bot(mid=900):
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=mid))
    bot.edit_message_text = AsyncMock()
    return bot


def closed(**kw):
    d = {
        "task": {"id": 8},
        "how": "done",
        "by_name": "Aziz <b>",
        "solution_label": "Kutmoqda",
        "next_due": "2026-11-05T10:00:00",
    }
    d.update(kw)
    return {"id": "00000000-0000-0000-0000-000000009101", "event": "crm.task_closed", "data": d}


def moved(**kw):
    d = {
        "task": {"id": 8, "due_at": "2026-11-05T10:00:00"},
        "how": "rescheduled",
        "by_name": "Aziz",
        "to_name": None,
    }
    d.update(kw)
    return {"id": "00000000-0000-0000-0000-000000009102", "event": "crm.task_moved", "data": d}


async def stored(task_id=8):
    return [json.loads(x) for x in await get_redis().lrange(f"crm:msg:{task_id}", 0, -1)]


def test_events_registered():
    assert {"crm.task_closed", "crm.task_moved"} <= set(events())


async def test_task_due_stores_each_reminder_with_ttl():
    bot = fake_bot(901)
    await dispatch(TASK_DUE, bot)
    items = await stored()
    assert [(i["chat_id"], i["message_id"]) for i in items] == [(111, 901), (222, 901)]
    assert items[0]["html"] == bot.send_message.call_args_list[0].args[1]
    ttl = await get_redis().ttl(KEY)
    assert 13 * 86400 < ttl <= 14 * 86400


async def test_failed_send_is_not_stored():
    bot = fake_bot()
    bot.send_message = AsyncMock(side_effect=TelegramForbiddenError(MagicMock(), "blocked"))
    await dispatch(TASK_DUE, bot)
    assert await stored() == []


async def test_closed_edits_stored_messages_and_deletes_key():
    await dispatch(TASK_DUE, fake_bot())
    bot = fake_bot()
    res = await dispatch(closed(), bot)
    assert res == []
    calls = bot.edit_message_text.call_args_list
    assert [(c.kwargs["chat_id"], c.kwargs["message_id"]) for c in calls] == [
        (111, 900),
        (222, 900),
    ]
    text = calls[0].args[0]
    assert text.startswith(T.task_due(TASK_DUE["data"]))
    assert text.endswith(
        "✅ Panelda bajarildi — Aziz &lt;b&gt;\n➡️ Kutmoqda\n⏰ Keyingi qo'ng'iroq: 05.11 10:00"
    )
    assert calls[0].kwargs["reply_markup"] is None and calls[0].kwargs["parse_mode"] == "HTML"
    assert await stored() == []


async def test_closed_without_next_or_solution():
    await dispatch(TASK_DUE, fake_bot())
    bot = fake_bot()
    await dispatch(closed(solution_label=None, next_due=None), bot)
    assert (
        bot.edit_message_text.call_args_list[0]
        .args[0]
        .endswith("\n\n✅ Panelda bajarildi — Aziz &lt;b&gt;")
    )


async def test_auto_closed_text():
    await dispatch(TASK_DUE, fake_bot())
    bot = fake_bot()
    await dispatch(closed(how="auto", by_name=None, next_due=None), bot)
    assert (
        bot.edit_message_text.call_args_list[0].args[0].endswith("\n\n🗂 Ariza yopildi — Kutmoqda")
    )


async def test_unknown_task_is_a_noop():
    bot = fake_bot()
    assert await dispatch(closed(task={"id": 777}), bot) == []
    bot.edit_message_text.assert_not_called()


@pytest.mark.parametrize("exc", ["not modified", "message to edit not found"])
async def test_telegram_errors_are_swallowed(exc):
    await dispatch(TASK_DUE, fake_bot())
    bot = fake_bot()
    bot.edit_message_text = AsyncMock(
        side_effect=[
            TelegramBadRequest(EditMessageText(text="x"), f"Bad Request: {exc}"),
            TelegramForbiddenError(MagicMock(), "Forbidden: bot was blocked by the user"),
        ]
    )
    await dispatch(closed(), bot)
    assert bot.edit_message_text.await_count == 2  # the second recipient is still tried
    assert await stored() == []


async def test_moved_rescheduled_and_reassigned_texts():
    await dispatch(TASK_DUE, fake_bot())
    bot = fake_bot()
    await dispatch(moved(), bot)
    assert (
        bot.edit_message_text.call_args_list[0]
        .args[0]
        .endswith("\n\n⏰ Ko'chirildi: 05.11 10:00 — Aziz")
    )
    assert bot.edit_message_text.call_args_list[0].kwargs["reply_markup"] is None
    assert await stored() == []

    await dispatch(TASK_DUE, fake_bot())
    bot = fake_bot()
    await dispatch(moved(how="reassigned", to_name="Vali & Co", by_name=None), bot)
    assert (
        bot.edit_message_text.call_args_list[0]
        .args[0]
        .endswith("\n\n↪️ Vali &amp; Co ga o'tkazildi")
    )


@pytest.mark.parametrize(
    "path",
    [p for p in sorted(glob.glob(str(CONTRACT / "event.crm.task_*.json"))) if "task_due" not in p],
)
async def test_sync_fixtures_render(path):
    env = copy.deepcopy(json.loads(Path(path).read_text(encoding="utf-8")))
    tid = env["data"]["task"]["id"]
    await get_redis().rpush(
        f"crm:msg:{tid}", json.dumps({"chat_id": 5, "message_id": 6, "html": "<b>x</b>"})
    )
    bot = fake_bot()
    await dispatch(env, bot)
    c = bot.edit_message_text.call_args_list[0]
    assert c.args[0].startswith("<b>x</b>\n\n") and c.kwargs["chat_id"] == 5
    assert await stored(tid) == []


# ------------------------------------------------------------ the bot's own buttons
async def seed():
    await get_redis().rpush(KEY, json.dumps({"chat_id": 1, "message_id": 2, "html": "h"}))


async def test_bot_done_forgets_the_mapping(env):
    await seed()
    env.backend.routes[("GET", "crm/tasks/8/")] = {"outcomes": ["keep"], "url": "u"}
    env.backend.routes[("POST", "crm/tasks/8/done/")] = {
        "task": {"id": 8, "is_done": True},
        "by_name": "Aziz",
    }
    await env.cb("crm:done:8", text="⏰ Vazifa vaqti keldi")
    assert await stored() == []


async def test_bot_snooze_forgets_the_mapping(env):
    await seed()
    env.backend.routes[("POST", "crm/tasks/8/snooze/")] = {
        "task": {"id": 8, "due_at": "2026-11-03T15:30:00"}
    }
    await env.cb("crm:sn:1h:8")
    assert await stored() == []


async def test_failed_snooze_keeps_the_mapping(env):
    from bot.backend.client import Forbidden

    await seed()
    env.backend.routes[("POST", "crm/tasks/8/snooze/")] = Forbidden("no", 403)
    await env.cb("crm:sn:1h:8")
    assert len(await stored()) == 1
