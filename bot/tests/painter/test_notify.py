"""painter.* events: cards, per-assignee store keys, rev guards, edits only for listed chats."""

import json

import bot.painter  # noqa: F401  (registers painter.*)
from bot.common.rds import get_redis
from bot.notify.registry import dispatch, events

from .conftest import URL, buttons, cbs, done_task, envelope, fake_bot, task

A = {"id": 5, "name": "Molyar usta"}
B = {"id": 6, "name": "Molyar ikki"}


def test_events_registered():
    for e in ("task", "unassigned", "ready", "due_ask", "due_set", "remind", "done"):
        assert f"painter.{e}" in events()


async def test_task_card_and_store_key_per_assignee():
    bot = fake_bot(701)
    await dispatch(envelope("painter.task", painter=task(rev=1), to=[111]), bot)
    args, kw = bot.send_message.call_args.args, bot.send_message.call_args.kwargs
    text = args[1]
    assert "Yangi Molyar ishi" in text and "Buyurtma №406" in text
    assert "Karim Aliyev" in text and "+998901234567" in text
    assert "Chilonzor 7 &amp; 12" in text and '<a href="https://yandex.com/maps' in text
    assert "3.5 m²" in text and "🎨 Tur: Emal" in text and "Muddat: 20.11.2026" in text
    assert "Summa" not in text
    assert buttons(kw["reply_markup"]) == [
        ("✅ Bajardim", "pn:dn:21", None),
        ("🌐 Saytda ochish", None, URL),
    ]
    raw = await get_redis().lrange("pnt:msg:t21u5", 0, -1)
    assert [json.loads(x)["chat_id"] for x in raw] == [111]


async def test_due_line_marks():
    bot = fake_bot()
    await dispatch(
        envelope("painter.task", painter=task(due_auto=True, overdue=True, days_late=2), to=[1]),
        bot,
    )
    text = bot.send_message.call_args.args[1]
    assert "(avto)" in text and "⚠️ 2 kun kechikdi" in text
    await dispatch(envelope("painter.task", 2, painter=task(due_date=None), to=[1]), bot)
    assert "Muddat hali belgilanmagan" in bot.send_message.call_args.args[1]


async def test_unassigned_edits_only_old_chat_and_keeps_new_card():
    bot = fake_bot(800)
    await dispatch(envelope("painter.task", painter=task(rev=1), to=[111]), bot)
    await dispatch(envelope("painter.task", 2, painter=task(rev=1, painter=B), to=[222]), bot)
    bot.edit_message_text.reset_mock()
    await dispatch(
        envelope("painter.unassigned", 3, painter=task(rev=2, painter=B), prev=A, to=[111]), bot
    )
    edits = bot.edit_message_text.call_args_list
    assert len(edits) == 1 and edits[0].kwargs["chat_id"] == 111
    assert "♻️ Bu ish boshqa molyarga o'tkazildi" in edits[0].args[0]
    assert cbs(edits[0].kwargs["reply_markup"]) == []
    assert buttons(edits[0].kwargs["reply_markup"]) == [("🌐 Saytda ochish", None, URL)]
    assert len(await get_redis().lrange("pnt:msg:t21u6", 0, -1)) == 1


async def test_late_unassigned_after_back_to_a_is_ignored():
    bot = fake_bot(800)
    # A -> B -> A: task A (rev 1), then task A again (rev 3), late unassigned A (rev 2)
    await dispatch(envelope("painter.task", painter=task(rev=1), to=[111]), bot)
    await dispatch(envelope("painter.task", 2, painter=task(rev=3), to=[111]), bot)
    bot.edit_message_text.reset_mock()
    await dispatch(
        envelope("painter.unassigned", 3, painter=task(rev=2, painter=B), prev=A, to=[111]), bot
    )
    bot.edit_message_text.assert_not_called()


async def test_unassigned_without_stored_card_is_noop():
    bot = fake_bot()
    await dispatch(
        envelope("painter.unassigned", painter=task(rev=2, painter=B), prev=A, to=[111]), bot
    )
    bot.edit_message_text.assert_not_called()
    bot.send_message.assert_not_called()


async def test_ready_message_to_managers():
    bot = fake_bot()
    await dispatch(envelope("painter.ready", painter=task(), to=[7, 8]), bot)
    calls = bot.send_message.call_args_list
    assert [c.args[0] for c in calls] == [7, 8]
    assert calls[0].args[1].startswith("🎨 Rover tayyor — №406")
    assert "Molyar usta" in calls[0].args[1]
    assert ("🌐 Saytda ochish", None, URL) in buttons(calls[0].kwargs["reply_markup"])
    bot.send_message.reset_mock()
    await dispatch(envelope("painter.ready", 2, painter=task(painter=None, type=None), to=[7]), bot)
    assert "molyar turini tanlang" in bot.send_message.call_args.args[1]


async def test_due_ask_head_card():
    bot = fake_bot(702)
    await dispatch(
        envelope("painter.due_ask", painter=task(due_date=None), presets=[5, 10, 14], to=[222]),
        bot,
    )
    text = bot.send_message.call_args.args[1]
    assert "Molyar uchun muddat qo'ying" in text and "👷 Molyar: Molyar usta" in text
    assert "Muddat hali belgilanmagan" in text
    kb = bot.send_message.call_args.kwargs["reply_markup"]
    assert cbs(kb) == ["pn:dd:5:21", "pn:dd:10:21", "pn:dd:14:21"]
    assert [b[0] for b in buttons(kb)][:3] == ["+5 kun", "+10 kun", "+14 kun"]
    raw = await get_redis().lrange("pnt:msg:h21", 0, -1)
    assert [json.loads(x)["message_id"] for x in raw] == [702]


async def _stored(bot):
    await dispatch(envelope("painter.task", painter=task(rev=1), to=[111, 112]), bot)
    await dispatch(envelope("painter.due_ask", 2, painter=task(rev=1), to=[222, 223]), bot)
    bot.send_message.reset_mock()


async def test_due_set_edits_only_listed_chats_and_notifies():
    bot = fake_bot(800)
    await _stored(bot)
    await dispatch(
        envelope(
            "painter.due_set",
            4,
            painter=task(rev=2, due_date="2026-11-25"),
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
    assert "25.11.2026" in texts[111] and "muddat qo'ying" in texts[222]
    sent = bot.send_message.call_args_list
    assert [c.args[0] for c in sent] == [111]
    assert sent[0].args[1] == "🗓 Molyar №406 muddati: 25.11.2026 (Rahbar &lt;x&gt; qo'ydi)"


async def test_due_set_auto_text_and_stale_rev():
    bot = fake_bot(800)
    await _stored(bot)
    await dispatch(
        envelope("painter.due_set", 4, painter=task(rev=5), how="auto", to=[111], heads=[222]), bot
    )
    assert bot.send_message.call_args.args[1].endswith("20.11.2026 (avtomatik)")
    bot.edit_message_text.reset_mock()
    bot.send_message.reset_mock()
    await dispatch(
        envelope("painter.due_set", 5, painter=task(rev=4), how="set", to=[111], heads=[222]), bot
    )
    bot.edit_message_text.assert_not_called()
    bot.send_message.assert_not_called()


async def test_remind_texts_not_stored():
    bot = fake_bot()
    t = task()
    await dispatch(
        envelope("painter.remind", painter=t, what="soon", days_late=0, to=[1], heads=[]), bot
    )
    c = bot.send_message.call_args
    assert c.args[1] == "⏰ Ertaga Molyar muddati tugaydi — №406"
    assert cbs(c.kwargs["reply_markup"]) == ["pn:dn:21"]
    bot.send_message.reset_mock()
    await dispatch(
        envelope("painter.remind", 2, painter=t, what="overdue", days_late=2, to=[1], heads=[9]),
        bot,
    )
    calls = bot.send_message.call_args_list
    assert [c.args[0] for c in calls] == [1, 9]
    assert calls[0].args[1] == "⚠️ Molyar muddati o'tdi (2 kun) — №406"
    assert calls[1].args[1] == "🔴 Molyar kechikyapti (2 kun) — №406"
    assert cbs(calls[1].kwargs["reply_markup"]) == ["pn:dd:5:21", "pn:dd:10:21", "pn:dd:14:21"]
    assert not await get_redis().lrange("pnt:msg:t21u5", 0, -1)


async def test_done_message_and_edits_of_stored_cards():
    bot = fake_bot(900)
    await dispatch(envelope("painter.task", painter=task(rev=1), to=[111]), bot)
    await dispatch(envelope("painter.due_ask", 2, painter=task(rev=1), to=[222, 223]), bot)
    bot.send_message.reset_mock()
    await dispatch(
        envelope(
            "painter.done",
            3,
            painter=done_task(rev=4, note="Ish <b>"),
            by_name="Molyar usta",
            to=[222, 7],
            heads=[222],
            painters=[111],
        ),
        bot,
    )
    sent = bot.send_message.call_args_list
    assert [c.args[0] for c in sent] == [222, 7]
    assert "Molyar tayyor" in sent[0].args[1] and "№406" in sent[0].args[1]
    assert "Emal" in sent[0].args[1] and "3.5 m²" in sent[0].args[1]
    assert "Ish &lt;b&gt;" in sent[0].args[1]
    edits = bot.edit_message_text.call_args_list
    assert sorted(e.kwargs["chat_id"] for e in edits) == [111, 222]  # not 223, not 7
    for e in edits:
        assert cbs(e.kwargs["reply_markup"]) == []
    painter_edit = [e for e in edits if e.kwargs["chat_id"] == 111][0]
    assert "✅ Bajarildi — Molyar usta" in painter_edit.args[0]


async def test_done_stale_rev_does_not_edit():
    bot = fake_bot(900)
    await dispatch(envelope("painter.task", painter=task(rev=5), to=[111]), bot)
    bot.edit_message_text.reset_mock()
    await dispatch(
        envelope("painter.done", 2, painter=done_task(rev=4), to=[], heads=[], painters=[111]), bot
    )
    bot.edit_message_text.assert_not_called()
