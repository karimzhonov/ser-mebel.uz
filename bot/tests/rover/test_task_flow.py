"""Worker flow («✅ Bajardim»), head presets, new events (real dispatcher, scripted backend)."""

import json
import time

from aiogram.methods import EditMessageReplyMarkup, EditMessageText

import bot.rover  # noqa: F401
from bot.backend.client import BackendDown, Conflict, Forbidden, ServiceRefusal
from bot.common.rds import get_redis
from bot.crm.texts import NEW_BTN
from bot.notify.registry import dispatch, events
from bot.rover.api import DOWN_TEXT

from .conftest import URL, buttons, cbs, done_task, envelope, fake_bot, new_task, task

SUBMIT = "rovers/12/submit/"
DUE = "rovers/12/due/"
TCARD = "🛠 Yangi Rover ishi\n\nBuyurtma №406"


def card_kb():
    return {
        "inline_keyboard": [
            [{"text": "✅ Bajardim", "callback_data": "rv:dn:12"}],
            [{"text": "🌐 Saytda ochish", "url": URL}],
        ]
    }


async def start(env):
    await env.cb("rv:dn:12", text=TCARD, markup=card_kb())


async def to_confirm(env, amount="250 000", note="Eshiklar tayyor, 4 ta"):
    await start(env)
    await env.text(amount)
    await env.text(note)


def alert(env):
    a = env.session.answers()[-1]
    return a.text if a.show_alert else None


# ---- events


def test_events_registered():
    for e in ("task", "due_ask", "due_set", "remind"):
        assert f"rover.{e}" in events()


async def test_task_card_and_store():
    bot = fake_bot(701)
    await dispatch(envelope("rover.task", rover=new_task(), to=[111]), bot)
    args, kw = bot.send_message.call_args.args, bot.send_message.call_args.kwargs
    text = args[1]
    assert "Yangi Rover ishi" in text and "Karim Aliyev" in text and "+998901234567" in text
    assert "Chilonzor 7 &amp; 12" in text and '<a href="https://yandex.com/maps' in text
    assert "3.5 m²" in text and "Muddat: 15.11.2026" in text
    assert "Summa" not in text
    assert buttons(kw["reply_markup"]) == [
        ("✅ Bajardim", "rv:dn:12", None),
        ("🌐 Saytda ochish", None, URL),
    ]
    raw = await get_redis().lrange("rov:msg:t12", 0, -1)
    assert [json.loads(x)["chat_id"] for x in raw] == [111]
    assert not await get_redis().lrange("rov:msg:12", 0, -1)


async def test_task_card_marks_and_no_due():
    bot = fake_bot()
    t = new_task(due_auto=True, overdue=True, days_late=2)
    await dispatch(envelope("rover.task", rover=t, to=[1]), bot)
    text = bot.send_message.call_args.args[1]
    assert "(avto)" in text and "⚠️ 2 kun kechikdi" in text
    await dispatch(envelope("rover.task", 2, rover=new_task(due_date=None), to=[1]), bot)
    assert "Muddat hali belgilanmagan" in bot.send_message.call_args.args[1]


async def test_task_card_no_button_when_not_new():
    bot = fake_bot()
    await dispatch(envelope("rover.task", rover=task(note="Ish <b>"), to=[1]), bot)
    text = bot.send_message.call_args.args[1]
    assert "⏳ Tekshiruvda" in text and "250 000 so'm" in text and "Ish &lt;b&gt;" in text
    assert cbs(bot.send_message.call_args.kwargs["reply_markup"]) == []


async def test_due_ask_head_card():
    bot = fake_bot(702)
    await dispatch(
        envelope("rover.due_ask", rover=new_task(due_date=None), presets=[3, 5, 7], to=[222]), bot
    )
    text = bot.send_message.call_args.args[1]
    assert "Rover uchun muddat qo'ying" in text and "Muddat hali belgilanmagan" in text
    kb = bot.send_message.call_args.kwargs["reply_markup"]
    assert cbs(kb) == ["rv:dd:3:12", "rv:dd:5:12", "rv:dd:7:12"]
    assert [b[0] for b in buttons(kb)][:3] == ["+3 kun", "+5 kun", "+7 kun"]
    raw = await get_redis().lrange("rov:msg:h12", 0, -1)
    assert [json.loads(x)["message_id"] for x in raw] == [702]


async def _stored(bot):
    await dispatch(envelope("rover.task", rover=new_task(rev=1), to=[111, 112]), bot)
    await dispatch(envelope("rover.due_ask", 2, rover=new_task(rev=1), to=[222, 223]), bot)
    await dispatch(envelope("rover.check", 3, rover=task(rev=1), to=[333]), bot)
    bot.send_message.reset_mock()


async def test_due_set_edits_only_to_and_heads_and_notifies():
    bot = fake_bot(800)
    await _stored(bot)
    await dispatch(
        envelope(
            "rover.due_set",
            4,
            rover=new_task(rev=2, due_date="2026-11-20"),
            how="set",
            by_name="Rahbar <x>",
            to=[111],
            heads=[222],
        ),
        bot,
    )
    edits = bot.edit_message_text.call_args_list
    assert sorted(e.kwargs["chat_id"] for e in edits) == [111, 222]
    texts = {e.kwargs["chat_id"]: e.args[0] for e in edits}
    assert "Yangi Rover ishi" in texts[111] and "20.11.2026" in texts[111]
    assert "muddat qo'ying" in texts[222]
    sent = bot.send_message.call_args_list
    assert [c.args[0] for c in sent] == [111]
    assert sent[0].args[1] == "🗓 Rover №406 muddati: 20.11.2026 (Rahbar &lt;x&gt; qo'ydi)"


async def test_due_set_auto_text():
    bot = fake_bot(800)
    await _stored(bot)
    await dispatch(
        envelope(
            "rover.due_set", 4, rover=new_task(rev=2), how="auto", by_name=None, to=[111], heads=[]
        ),
        bot,
    )
    assert bot.send_message.call_args.args[1].endswith("15.11.2026 (avtomatik)")


async def test_due_set_older_rev_ignored():
    bot = fake_bot(800)
    await _stored(bot)
    await dispatch(
        envelope("rover.due_set", 4, rover=new_task(rev=5), how="set", to=[111], heads=[222]), bot
    )
    bot.edit_message_text.reset_mock()
    bot.send_message.reset_mock()
    await dispatch(
        envelope("rover.due_set", 5, rover=new_task(rev=4), how="set", to=[111], heads=[222]), bot
    )
    bot.edit_message_text.assert_not_called()
    bot.send_message.assert_not_called()


async def test_remind_texts():
    bot = fake_bot()
    t = new_task()
    await dispatch(
        envelope("rover.remind", rover=t, what="soon", days_late=0, to=[1], heads=[]), bot
    )
    c = bot.send_message.call_args
    assert c.args[1] == "⏰ Ertaga Rover muddati tugaydi — №406"
    assert cbs(c.kwargs["reply_markup"]) == ["rv:dn:12"]
    assert ("🌐 Saytda ochish", None, URL) in buttons(c.kwargs["reply_markup"])
    bot.send_message.reset_mock()
    await dispatch(
        envelope("rover.remind", 2, rover=t, what="overdue", days_late=2, to=[1], heads=[9]), bot
    )
    calls = bot.send_message.call_args_list
    assert [c.args[0] for c in calls] == [1, 9]
    assert calls[0].args[1] == "⚠️ Rover muddati o'tdi (2 kun) — №406"
    assert cbs(calls[0].kwargs["reply_markup"]) == ["rv:dn:12"]
    assert calls[1].args[1] == "🔴 Rover kechikyapti (2 kun) — №406"
    assert cbs(calls[1].kwargs["reply_markup"]) == ["rv:dd:3:12", "rv:dd:5:12", "rv:dd:7:12"]
    assert not await get_redis().lrange("rov:msg:t12", 0, -1)


async def test_check_and_checked_edit_workers_cards_separately():
    bot = fake_bot(900)
    # chat 111 is both the worker and a checker
    await dispatch(envelope("rover.task", rover=new_task(rev=1), to=[111]), bot)
    bot.edit_message_text.reset_mock()
    await dispatch(envelope("rover.check", 2, rover=task(rev=2), to=[111, 222], workers=[111]), bot)
    edits = bot.edit_message_text.call_args_list
    assert len(edits) == 1 and "⏳ Tekshiruvda" in edits[0].args[0]
    assert cbs(edits[0].kwargs["reply_markup"]) == []
    assert len(await get_redis().lrange("rov:msg:12", 0, -1)) == 2
    assert len(await get_redis().lrange("rov:msg:t12", 0, -1)) == 1
    bot.edit_message_text.reset_mock()
    await dispatch(
        envelope(
            "rover.checked", 3, rover=done_task(rev=3), by_name="T", to=[111, 222], workers=[111]
        ),
        bot,
    )
    edits = bot.edit_message_text.call_args_list
    assert len(edits) == 3
    worker = [e for e in edits if "Yangi Rover ishi" in e.args[0]]
    checker = [e for e in edits if "Rover ishini tekshiring" in e.args[0]]
    assert len(worker) == 1 and len(checker) == 2
    assert "✅ Tasdiqlandi — Tekshiruvchi" in worker[0].args[0]
    # the worker card survived the checker's take()
    assert len(await get_redis().lrange("rov:msg:t12", 0, -1)) == 1
    assert not await get_redis().lrange("rov:msg:12", 0, -1)


async def test_checker_card_shows_note():
    bot = fake_bot()
    await dispatch(envelope("rover.check", rover=task(note="4 ta eshik"), to=[1]), bot)
    assert "📝 Izoh: 4 ta eshik" in bot.send_message.call_args.args[1]


# ---- worker FSM


async def test_full_path_submits_and_edits_card(env):
    env.backend.routes[("POST", SUBMIT)] = {"rover": task(note="Eshiklar tayyor, 4 ta", rev=4)}
    await start(env)
    assert await env.state() == "RoverDone:amount"
    assert "summasini yozing" in env.session.last().text
    await env.text("250 000")
    assert await env.state() == "RoverDone:note"
    assert "nechta eshik" in env.session.last().text
    await env.text("Eshiklar tayyor, 4 ta")
    assert await env.state() == "RoverDone:confirm"
    last = env.session.last()
    assert "250 000 so'm" in last.text and "Eshiklar tayyor, 4 ta" in last.text
    assert cbs(last.reply_markup) == ["rv:sy:12", "rv:se:12", "rv:q"]
    await env.cb("rv:sy:12", text="Tekshiring")
    assert env.backend.to(SUBMIT)[0][2] == {"amount": "250000", "note": "Eshiklar tayyor, 4 ta"}
    e = env.session.of(EditMessageText)
    card = [x for x in e if "Yangi Rover ishi" in x.text][-1]
    assert card.message_id == 9 and "⏳ Tekshiruvda" in card.text
    assert buttons(card.reply_markup) == [("🌐 Saytda ochish", None, URL)]
    assert any(x.text == "✅ Tekshiruvga yuborildi" for x in e)
    assert await env.state() is None


async def test_bad_amount_and_short_note_reask(env):
    await start(env)
    await env.text("ko'p")
    assert "Summa noto'g'ri" in env.session.last().text
    assert await env.state() == "RoverDone:amount"
    await env.text("250.5")
    assert await env.state() == "RoverDone:amount"
    await env.text("100 000")
    await env.text("ok")
    assert "juda qisqa" in env.session.last().text
    assert await env.state() == "RoverDone:note"


async def test_restart_goes_back_to_amount(env):
    await to_confirm(env)
    await env.cb("rv:se:12", text="Tekshiring")
    assert await env.state() == "RoverDone:amount"
    assert "summasini yozing" in env.session.last().text


async def test_400_field_note_reasks(env):
    env.backend.routes[("POST", SUBMIT)] = ServiceRefusal(
        "Izoh juda qisqa", status=400, field="note"
    )
    await to_confirm(env)
    await env.cb("rv:sy:12", text="Tekshiring")
    assert await env.state() == "RoverDone:note"
    assert (
        "Izoh juda qisqa" in env.session.last().text and "nechta eshik" in env.session.last().text
    )


async def test_400_field_amount_reasks(env):
    env.backend.routes[("POST", SUBMIT)] = ServiceRefusal("Summa xato", status=400, field="amount")
    await to_confirm(env)
    await env.cb("rv:sy:12", text="Tekshiring")
    assert await env.state() == "RoverDone:amount"


async def test_409_alerts_clears_and_strips(env):
    env.backend.routes[("POST", SUBMIT)] = Conflict("Allaqachon topshirilgan", status=409)
    await to_confirm(env)
    await env.cb("rv:sy:12", text="Tekshiring")
    assert alert(env) == "Allaqachon topshirilgan"
    assert await env.state() is None
    kb = [c for c in env.session.of(EditMessageReplyMarkup) if c.message_id == 9]
    assert kb and cbs(kb[-1].reply_markup) == []


async def test_403_and_down_clear(env):
    env.backend.routes[("POST", SUBMIT)] = Forbidden("Ruxsat yo'q", status=403)
    await to_confirm(env)
    await env.cb("rv:sy:12", text="Tekshiring")
    assert alert(env) == "Ruxsat yo'q" and await env.state() is None
    env.backend.routes[("POST", SUBMIT)] = BackendDown("down")
    await to_confirm(env)
    await env.cb("rv:sy:12", text="Tekshiring")
    assert alert(env) == DOWN_TEXT and await env.state() is None


async def test_ttl_expired_is_stale(env):
    await env.set_state(
        "RoverDone:amount", rid=12, chat_id=555, message_id=9, ts=time.time() - 4000
    )
    await env.text("250 000")
    assert env.session.last().text == "Bu tugma eskirgan."
    assert await env.state() is None


async def test_busy_with_other_feature_state(env):
    await env.set_state("Lead:name")
    await start(env)
    assert alert(env) == "Avval boshqa amalni tugating"
    assert await env.state() == "Lead:name"


async def test_other_rover_state_restarts(env):
    await env.set_state("RoverDone:note", rid=99, chat_id=555, message_id=3, ts=time.time())
    await start(env)
    assert await env.state() == "RoverDone:amount"
    assert (await env.dp.storage.get_data(_key(env)))["rid"] == 12


def _key(env):
    from aiogram.fsm.storage.base import StorageKey

    return StorageKey(bot_id=env.bot.id, chat_id=555, user_id=555)


async def test_cancel_button_and_command(env):
    await start(env)
    await env.cb("rv:q", text="x")
    assert await env.state() is None
    await start(env)
    await env.text("/bekor")
    assert await env.state() is None and env.session.last().text == "Bekor qilindi."


async def test_menu_button_clears_and_skips(env):
    await start(env)
    await env.text(NEW_BTN)
    assert await env.state() != "RoverDone:amount"
    assert not env.backend.to(SUBMIT)


async def test_submit_without_state_is_stale(env):
    await env.cb("rv:sy:12", text="Tekshiring")
    assert alert(env) == "Bu tugma eskirgan."
    assert not env.backend.to(SUBMIT)


# ---- head presets


def head_kb():
    return {
        "inline_keyboard": [
            [{"text": "+5 kun", "callback_data": "rv:dd:5:12"}],
            [{"text": "🌐 Saytda ochish", "url": URL}],
        ]
    }


async def test_due_preset_posts_days_and_edits(env):
    env.backend.routes[("POST", DUE)] = {"rover": new_task(due_date="2026-11-20", rev=4)}
    await env.cb("rv:dd:5:12", text="🗓 Rover uchun muddat qo'ying", markup=head_kb())
    assert env.backend.to(DUE)[0][2] == {"days": 5}
    e = env.session.of(EditMessageText)[-1]
    assert "Rover uchun muddat qo'ying" in e.text and "20.11.2026" in e.text
    assert cbs(e.reply_markup) == ["rv:dd:3:12", "rv:dd:5:12", "rv:dd:7:12"]


async def test_due_preset_409_strips_buttons(env):
    env.backend.routes[("POST", DUE)] = Conflict("Rover allaqachon bajarilgan", status=409)
    await env.cb("rv:dd:5:12", text="x", markup=head_kb())
    assert alert(env) == "Rover allaqachon bajarilgan"
    kb = env.session.of(EditMessageReplyMarkup)[-1].reply_markup
    assert cbs(kb) == [] and ("🌐 Saytda ochish", None, URL) in buttons(kb)


async def test_due_preset_other_error_alerts_only(env):
    env.backend.routes[("POST", DUE)] = Forbidden("Ruxsat yo'q", status=403)
    await env.cb("rv:dd:7:12", text="x", markup=head_kb())
    assert alert(env) == "Ruxsat yo'q"
    assert not env.session.of(EditMessageReplyMarkup)


async def test_late_check_does_not_overwrite_done_card():
    bot = fake_bot(900)
    await dispatch(envelope("rover.task", rover=new_task(rev=1), to=[111]), bot)
    await dispatch(
        envelope("rover.checked", 3, rover=done_task(rev=3), by_name="T", to=[222], workers=[111]),
        bot,
    )
    bot.edit_message_text.reset_mock()
    await dispatch(envelope("rover.check", 4, rover=task(rev=2), to=[222], workers=[111]), bot)
    assert bot.edit_message_text.call_count == 0
