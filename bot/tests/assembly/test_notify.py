"""assembly.* events: cards, per-assignee store keys, rev guards, edits only for listed chats."""

import json

import bot.assembly  # noqa: F401  (registers assembly.*)
from bot.common.rds import get_redis
from bot.notify.registry import dispatch, events

from .conftest import URL, buttons, cbs, done_task, envelope, fake_bot, task

A = {"id": 5, "name": "Yig'uvchi usta"}
B = {"id": 6, "name": "Yig'uvchi ikki"}
ASSEMBLERS = [A, B, {"id": 9, "name": "U" * 60}]


def test_events_registered():
    for e in ("ready", "task", "unassigned", "due_ask", "due_set", "remind", "done"):
        assert f"assembly.{e}" in events()


async def test_task_card_and_store_key_per_assignee():
    bot = fake_bot(701)
    await dispatch(envelope("assembly.task", assembly=task(rev=1), to=[111]), bot)
    args, kw = bot.send_message.call_args.args, bot.send_message.call_args.kwargs
    text = args[1]
    assert "Yangi Yig'ish/O'rnatish ishi" in text and "Buyurtma №406" in text
    assert "Karim Aliyev" in text and "+998901234567" in text
    assert "Chilonzor 7 &amp; 12" in text and '<a href="https://yandex.com/maps' in text
    assert "3.5 m²" in text and "Muddat: 20.11.2026" in text
    assert buttons(kw["reply_markup"]) == [
        ("✅ O'rnatildi", "as:fn:21", None),
        ("🌐 Saytda ochish", None, URL),
    ]
    raw = await get_redis().lrange("asm:msg:t21u5", 0, -1)
    assert [json.loads(x)["chat_id"] for x in raw] == [111]


async def test_assembled_state_line_keeps_button():
    bot = fake_bot()
    await dispatch(
        envelope(
            "assembly.task", assembly=task(state="assembled", overdue=True, days_late=2), to=[1]
        ),
        bot,
    )
    text = bot.send_message.call_args.args[1]
    assert "Holat: Yig'ildi — o'rnatish qoldi" in text and "⚠️ 2 kun kechikdi" in text
    assert cbs(bot.send_message.call_args.kwargs["reply_markup"]) == ["as:fn:21"]
    await dispatch(envelope("assembly.task", 2, assembly=task(due_date=None), to=[1]), bot)
    assert "Muddat hali belgilanmagan" in bot.send_message.call_args.args[1]


async def test_unassigned_edits_only_old_chat_and_keeps_new_card():
    bot = fake_bot(800)
    await dispatch(envelope("assembly.task", assembly=task(rev=1), to=[111]), bot)
    await dispatch(envelope("assembly.task", 2, assembly=task(rev=1, assembler=B), to=[222]), bot)
    bot.edit_message_text.reset_mock()
    await dispatch(
        envelope("assembly.unassigned", 3, assembly=task(rev=2, assembler=B), prev=A, to=[111]),
        bot,
    )
    edits = bot.edit_message_text.call_args_list
    assert len(edits) == 1 and edits[0].kwargs["chat_id"] == 111
    assert "♻️ Bu ish boshqa yig'uvchiga o'tkazildi" in edits[0].args[0]
    assert cbs(edits[0].kwargs["reply_markup"]) == []
    assert buttons(edits[0].kwargs["reply_markup"]) == [("🌐 Saytda ochish", None, URL)]
    assert len(await get_redis().lrange("asm:msg:t21u6", 0, -1)) == 1


async def test_late_unassigned_after_back_to_a_is_ignored():
    bot = fake_bot(800)
    await dispatch(envelope("assembly.task", assembly=task(rev=1), to=[111]), bot)
    await dispatch(envelope("assembly.task", 2, assembly=task(rev=3), to=[111]), bot)
    bot.edit_message_text.reset_mock()
    await dispatch(
        envelope("assembly.unassigned", 3, assembly=task(rev=2, assembler=B), prev=A, to=[111]),
        bot,
    )
    bot.edit_message_text.assert_not_called()


async def test_unassigned_without_stored_card_is_noop():
    bot = fake_bot()
    await dispatch(
        envelope("assembly.unassigned", assembly=task(rev=2, assembler=B), prev=A, to=[111]), bot
    )
    bot.edit_message_text.assert_not_called()
    bot.send_message.assert_not_called()


async def test_ready_team_card_to_heads():
    bot = fake_bot(705)
    await dispatch(
        envelope("assembly.ready", assembly=task(assembler=None), assemblers=ASSEMBLERS, to=[7, 8]),
        bot,
    )
    calls = bot.send_message.call_args_list
    assert [c.args[0] for c in calls] == [7, 8]
    text = calls[0].args[1]
    assert "Yig'ishga tushdi — №406: jamoani tanlang" in text and "Karim Aliyev" in text
    assert "3.5 m²" in text
    assert buttons(calls[0].kwargs["reply_markup"]) == [
        ("Yig'uvchi usta", "as:us:5:21", None),
        ("Yig'uvchi ikki", "as:us:6:21", None),
        ("U" * 40, "as:us:9:21", None),
        ("🌐 Saytda ochish", None, URL),
    ]
    raw = await get_redis().lrange("asm:msg:r21", 0, -1)
    assert [json.loads(x)["chat_id"] for x in raw] == [7, 8]


async def test_ready_shows_current_assembler():
    bot = fake_bot()
    await dispatch(envelope("assembly.ready", assembly=task(), assemblers=[A], to=[7]), bot)
    assert "👷 Yig'uvchi: Yig'uvchi usta" in bot.send_message.call_args.args[1]


async def test_ready_without_assemblers_is_link_only():
    bot = fake_bot(706)
    await dispatch(envelope("assembly.ready", assembly=task(), assemblers=[], to=[7]), bot)
    c = bot.send_message.call_args
    assert "Yig'uvchilar yo'q — saytda tanlang" in c.args[1]
    assert cbs(c.kwargs["reply_markup"]) == []
    assert buttons(c.kwargs["reply_markup"]) == [("🌐 Saytda ochish", None, URL)]


async def test_ready_stale_rev_is_ignored():
    bot = fake_bot()
    await dispatch(envelope("assembly.ready", assembly=task(rev=5), assemblers=[A], to=[7]), bot)
    bot.send_message.reset_mock()
    await dispatch(envelope("assembly.ready", 2, assembly=task(rev=4), assemblers=[A], to=[7]), bot)
    bot.send_message.assert_not_called()


async def test_due_ask_closes_team_cards_and_stores_head_card():
    bot = fake_bot(710)
    await dispatch(envelope("assembly.ready", assembly=task(rev=2), assemblers=[A], to=[7, 8]), bot)
    bot.edit_message_text.reset_mock()
    bot.send_message.reset_mock()
    await dispatch(
        envelope(
            "assembly.due_ask",
            2,
            assembly=task(rev=3, due_date=None),
            presets=[5, 10, 14],
            to=[222],
        ),
        bot,
    )
    edits = bot.edit_message_text.call_args_list
    assert sorted(e.kwargs["chat_id"] for e in edits) == [7, 8]
    assert "✅ Jamoa: Yig'uvchi usta" in edits[0].args[0]
    assert buttons(edits[0].kwargs["reply_markup"]) == [("🌐 Saytda ochish", None, URL)]
    assert await get_redis().lrange("asm:msg:r21", 0, -1) == []
    text = bot.send_message.call_args.args[1]
    assert "Yig'ish uchun muddat qo'ying" in text and "👷 Yig'uvchi: Yig'uvchi usta" in text
    assert "Muddat hali belgilanmagan" in text
    kb = bot.send_message.call_args.kwargs["reply_markup"]
    assert cbs(kb) == ["as:dd:5:21", "as:dd:10:21", "as:dd:14:21"]
    raw = await get_redis().lrange("asm:msg:h21", 0, -1)
    assert [json.loads(x)["message_id"] for x in raw] == [710]


async def test_task_event_closes_stored_team_cards():
    bot = fake_bot(720)
    await dispatch(envelope("assembly.ready", assembly=task(rev=2), assemblers=[A], to=[7, 8]), bot)
    bot.edit_message_text.reset_mock()
    await dispatch(envelope("assembly.task", 2, assembly=task(rev=3), to=[111]), bot)
    edits = bot.edit_message_text.call_args_list
    assert sorted(e.kwargs["chat_id"] for e in edits) == [7, 8]
    assert "✅ Jamoa: Yig'uvchi usta" in edits[0].args[0]
    assert await get_redis().lrange("asm:msg:r21", 0, -1) == []


async def test_late_ready_after_task_sends_no_pick_card():
    bot = fake_bot(740)
    await dispatch(envelope("assembly.task", 1, assembly=task(rev=3), to=[111]), bot)
    bot.send_message.reset_mock()
    await dispatch(envelope("assembly.ready", 2, assembly=task(rev=2), assemblers=[A], to=[7]), bot)
    assert bot.send_message.call_count == 0


async def _stored(bot):
    await dispatch(envelope("assembly.task", assembly=task(rev=1), to=[111, 112]), bot)
    await dispatch(envelope("assembly.due_ask", 2, assembly=task(rev=1), to=[222, 223]), bot)
    bot.send_message.reset_mock()


async def test_due_set_edits_only_listed_chats_and_notifies():
    bot = fake_bot(800)
    await _stored(bot)
    await dispatch(
        envelope(
            "assembly.due_set",
            4,
            assembly=task(rev=2, due_date="2026-11-25"),
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
    assert sent[0].args[1] == "🗓 Yig'ish №406 muddati: 25.11.2026 (Rahbar &lt;x&gt; qo'ydi)"


async def test_due_set_auto_text_and_stale_rev():
    bot = fake_bot(800)
    await _stored(bot)
    await dispatch(
        envelope("assembly.due_set", 4, assembly=task(rev=5), how="auto", to=[111], heads=[222]),
        bot,
    )
    assert bot.send_message.call_args.args[1].endswith("20.11.2026 (avtomatik)")
    bot.edit_message_text.reset_mock()
    bot.send_message.reset_mock()
    await dispatch(
        envelope("assembly.due_set", 5, assembly=task(rev=4), how="set", to=[111], heads=[222]),
        bot,
    )
    bot.edit_message_text.assert_not_called()
    bot.send_message.assert_not_called()


async def test_remind_texts_not_stored():
    bot = fake_bot()
    t = task()
    await dispatch(
        envelope("assembly.remind", assembly=t, what="soon", days_late=0, to=[1], heads=[]), bot
    )
    c = bot.send_message.call_args
    assert c.args[1] == "⏰ Ertaga Yig'ish muddati tugaydi — №406"
    assert cbs(c.kwargs["reply_markup"]) == ["as:fn:21"]
    bot.send_message.reset_mock()
    await dispatch(
        envelope("assembly.remind", 2, assembly=t, what="overdue", days_late=2, to=[1], heads=[9]),
        bot,
    )
    calls = bot.send_message.call_args_list
    assert [c.args[0] for c in calls] == [1, 9]
    assert calls[0].args[1] == "⚠️ Yig'ish muddati o'tdi (2 kun) — №406"
    assert calls[1].args[1] == "🔴 Yig'ish kechikyapti (2 kun) — №406"
    assert cbs(calls[1].kwargs["reply_markup"]) == ["as:dd:5:21", "as:dd:10:21", "as:dd:14:21"]
    assert not await get_redis().lrange("asm:msg:t21u5", 0, -1)


async def test_done_message_and_edits_of_stored_cards():
    bot = fake_bot(900)
    await dispatch(envelope("assembly.task", assembly=task(rev=1), to=[111]), bot)
    await dispatch(envelope("assembly.due_ask", 2, assembly=task(rev=1), to=[222, 223]), bot)
    bot.send_message.reset_mock()
    await dispatch(
        envelope(
            "assembly.done",
            3,
            assembly=done_task(rev=4, note="Ish <b>"),
            by_name="Yig'uvchi usta",
            to=[222, 7],
            heads=[222],
            assemblers=[111],
        ),
        bot,
    )
    sent = bot.send_message.call_args_list
    assert [c.args[0] for c in sent] == [222, 7]
    assert "O'rnatildi" in sent[0].args[1] and "№406" in sent[0].args[1]
    assert "3.5 m²" in sent[0].args[1] and "Ish &lt;b&gt;" in sent[0].args[1]
    assert sent[0].args[1].count("Yig'uvchi usta") == 1  # the assembler closed it: name once
    edits = bot.edit_message_text.call_args_list
    assert sorted(e.kwargs["chat_id"] for e in edits) == [111, 222]  # not 223, not 7
    for e in edits:
        assert cbs(e.kwargs["reply_markup"]) == []
    mine = [e for e in edits if e.kwargs["chat_id"] == 111][0]
    assert "✅ O'rnatildi — Yig'uvchi usta" in mine.args[0]


async def test_done_stale_rev_does_not_edit():
    bot = fake_bot(900)
    await dispatch(envelope("assembly.task", assembly=task(rev=5), to=[111]), bot)
    bot.edit_message_text.reset_mock()
    await dispatch(
        envelope("assembly.done", 2, assembly=done_task(rev=4), to=[], heads=[], assemblers=[111]),
        bot,
    )
    bot.edit_message_text.assert_not_called()


async def test_done_by_manager_names_who_closed_it_and_closes_pick_cards():
    bot = fake_bot(910)
    await dispatch(
        envelope(
            "assembly.ready", assembly=task(rev=1, assembler=None), assemblers=ASSEMBLERS, to=[7]
        ),
        bot,
    )
    bot.send_message.reset_mock()
    await dispatch(
        envelope(
            "assembly.done",
            2,
            assembly=done_task(rev=2, assembler=None),
            by_name="Menejer",
            to=[222],
            heads=[],
            assemblers=[],
        ),
        bot,
    )
    assert "✅ Belgiladi: Menejer" in bot.send_message.call_args.args[1]
    edits = bot.edit_message_text.call_args_list
    assert [e.kwargs["chat_id"] for e in edits] == [7]
    assert cbs(edits[0].kwargs["reply_markup"]) == []
    assert await get_redis().lrange("asm:msg:r21", 0, -1) == []
