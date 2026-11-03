"""crm.task_due rendering and the done / snooze buttons."""

import glob
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.crm  # noqa: F401  (registers crm.task_due)
from bot.backend.client import Conflict, Forbidden
from bot.notify.registry import dispatch, events

from .conftest import buttons

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"

TASK_DUE = {
    "id": "00000000-0000-0000-0000-000000009001",
    "event": "crm.task_due",
    "data": {
        "task": {
            "id": 8,
            "text": "Mijozga qo'ng'iroq qilish",
            "due_at": "2026-11-04T10:00:00",
            "is_done": False,
            "assigned": {"id": 3, "name": "Aziz"},
        },
        "invoice": {
            "id": 41,
            "client": {"fio": "Karim <b>", "phone": "+998901234567"},
            "source": "telegram",
            "source_label": "Telegram",
            "solution": None,
            "solution_label": None,
            "assigned": {"id": 3, "name": "Aziz"},
            "last_note": "Divan kerak",
        },
        "to": [111, 222],
        "url": "https://ser-mebel.uz/call-center?open=41",
    },
}


def fake_bot():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=900))
    return bot


def test_event_registered():
    assert "crm.task_due" in events()


async def test_task_due_renders_four_buttons_for_each_recipient():
    bot = fake_bot()
    delivered = await dispatch(TASK_DUE, bot)
    assert [d["chat_id"] for d in delivered] == [111, 222] and all(d["ok"] for d in delivered)
    call = bot.send_message.call_args_list[0]
    text = call.args[1]
    assert "Vazifa vaqti keldi" in text and "Mijozga qo'ng'iroq qilish" in text
    assert "04.11 10:00" in text and "Telegram" in text and "Divan kerak" in text
    assert "&lt;b&gt;" in text and "<b>Karim" not in text  # user content is escaped
    assert buttons(call.kwargs["reply_markup"]) == [
        ("💻 Panelda ochish", None, "https://ser-mebel.uz/call-center?open=41"),
        ("✅ Bajarildi", "crm:done:8", None),
        ("⏰ +1 soat", "crm:sn:1h:8", None),
        ("🌅 Ertaga", "crm:sn:tm:8", None),
    ]


async def test_task_due_adds_yandex_map_button_when_invoice_has_a_point():
    import copy

    env = copy.deepcopy(TASK_DUE)
    env["data"]["invoice"]["map_url"] = "https://yandex.uz/maps/?ll=69.27,41.31&pt=69.27,41.31"
    bot = fake_bot()
    await dispatch(env, bot)
    assert buttons(bot.send_message.call_args_list[0].kwargs["reply_markup"]) == [
        ("💻 Panelda ochish", None, "https://ser-mebel.uz/call-center?open=41"),
        ("🗺 Yandex xaritada", None, "https://yandex.uz/maps/?ll=69.27,41.31&pt=69.27,41.31"),
        ("✅ Bajarildi", "crm:done:8", None),
        ("⏰ +1 soat", "crm:sn:1h:8", None),
        ("🌅 Ertaga", "crm:sn:tm:8", None),
    ]


async def test_blocked_recipient_is_reported():
    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.methods import SendMessage

    bot = fake_bot()
    bot.send_message = AsyncMock(
        side_effect=TelegramForbiddenError(
            SendMessage(chat_id=1, text="x"), "Forbidden: bot was blocked by the user"
        )
    )
    delivered = await dispatch({**TASK_DUE, "data": {**TASK_DUE["data"], "to": [111]}}, bot)
    assert delivered[0]["blocked"] is True


@pytest.mark.parametrize("path", sorted(glob.glob(str(CONTRACT / "event.crm.*.json"))))
async def test_contract_fixtures_render(path):
    env = json.loads(Path(path).read_text(encoding="utf-8"))
    delivered = await dispatch(env, fake_bot())
    assert delivered and all(d["ok"] for d in delivered)


# ------------------------------------------------------------------ buttons
async def test_done_keep_only_posts_keep_and_finishes(env):
    env.backend.routes[("GET", "crm/tasks/8/")] = {"outcomes": ["keep"], "url": "u"}
    env.backend.routes[("POST", "crm/tasks/8/done/")] = {
        "task": {"id": 8, "is_done": True},
        "by_name": "Aziz",
    }
    await env.cb("crm:done:8", text="⏰ Vazifa vaqti keldi")
    assert env.backend.to("crm/tasks/8/done/")[0][2] == {"outcome": "keep"}
    e = env.session.edits()[0]
    assert e.text.startswith("✅ Bajarildi — Aziz") and "Vazifa vaqti keldi" in e.text
    assert e.reply_markup is None


async def test_snooze_edits_message(env):
    env.backend.routes[("POST", "crm/tasks/8/snooze/")] = {
        "task": {"id": 8, "due_at": "2026-11-03T15:30:00"}
    }
    await env.cb("crm:sn:1h:8")
    assert env.backend.to("crm/tasks/8/snooze/")[0][2] == {"preset": "1h"}
    assert env.session.edits()[0].text.startswith("⏰ 03.11 15:30 ga ko'chirildi")
    env.backend.routes[("POST", "crm/tasks/9/snooze/")] = {
        "task": {"id": 9, "due_at": "2026-11-04T10:00:00"}
    }
    await env.cb("crm:sn:tm:9")
    assert env.backend.to("crm/tasks/9/snooze/")[0][2] == {"preset": "tomorrow"}


async def test_done_conflict_alerts_and_keeps_message(env):
    env.backend.routes[("GET", "crm/tasks/8/")] = Conflict("Vazifa allaqachon bajarilgan", 409)
    await env.cb("crm:done:8")
    a = env.session.answers()[-1]
    assert a.show_alert and "allaqachon bajarilgan" in a.text
    assert env.session.edits() == []


async def test_snooze_forbidden_alerts(env):
    env.backend.routes[("POST", "crm/tasks/8/snooze/")] = Forbidden("Bu vazifa sizniki emas", 403)
    await env.cb("crm:sn:1h:8")
    a = env.session.answers()[-1]
    assert a.show_alert and a.text == "Bu vazifa sizniki emas"
    assert env.session.edits() == []


async def test_task_buttons_work_for_user_without_lead_right(env):
    env.backend.who["crm"] = {"can_add_lead": False}
    env.backend.routes[("GET", "crm/tasks/8/")] = {"outcomes": ["keep"]}
    env.backend.routes[("POST", "crm/tasks/8/done/")] = {"task": {"id": 8}, "by_name": "Aziz"}
    await env.cb("crm:done:8")
    assert len(env.backend.to("crm/tasks/8/done/")) == 1
