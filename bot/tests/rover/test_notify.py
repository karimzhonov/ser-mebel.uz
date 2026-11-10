"""rover.* events: card per recipient, edits only for stored cards in `to`."""

import json

import bot.rover  # noqa: F401  (registers rover.*)
from bot.common.rds import get_redis
from bot.notify.registry import dispatch, events

from .conftest import URL, buttons, done_task, envelope, fake_bot, task


def test_events_registered():
    assert "rover.check" in events() and "rover.checked" in events()


async def test_check_sends_one_card_per_recipient_and_remembers():
    bot = fake_bot(901)
    await dispatch(envelope("rover.check", rover=task(), to=[111, 222]), bot)
    calls = bot.send_message.call_args_list
    assert [c.args[0] for c in calls] == [111, 222]
    text = calls[0].args[1]
    assert "Rover ishini tekshiring" in text and "Buyurtma №406" in text
    assert "Karim Aliyev" in text and "+998901234567" in text
    assert "3.5 m²" in text and "250 000 so'm" in text
    assert "Rover usta" in text and "10.11 15:20" in text
    assert buttons(calls[0].kwargs["reply_markup"]) == [
        ("✅ Bajarildi", "rv:ok:12", None),
        ("🌐 Saytda ochish", None, URL),
    ]
    raw = await get_redis().lrange("rov:msg:12", 0, -1)
    assert sorted(json.loads(x)["chat_id"] for x in raw) == [111, 222]
    assert json.loads(raw[0])["kind"] == "check"


async def test_empty_client_fields_skipped_and_html_escaped():
    bot = fake_bot()
    t = task(client={"fio": "<b>Ali</b> & Co", "phone": ""}, submitted_by=None)
    await dispatch(envelope("rover.check", rover=t, to=[111]), bot)
    text = bot.send_message.call_args.args[1]
    assert "&lt;b&gt;Ali&lt;/b&gt; &amp; Co" in text
    assert "📞" not in text


async def test_checked_edits_stored_cards_in_to_only():
    bot = fake_bot(901)
    await dispatch(envelope("rover.check", rover=task(), to=[111, 222]), bot)
    bot.edit_message_text.reset_mock()
    await dispatch(
        envelope("rover.checked", 2, rover=done_task(), by_name="Tekshiruvchi", to=[111]), bot
    )
    edits = bot.edit_message_text.call_args_list
    assert len(edits) == 1
    kw = edits[0].kwargs
    assert kw["chat_id"] == 111 and kw["message_id"] == 901
    assert "✅ Tasdiqlandi — Tekshiruvchi" in edits[0].args[0]
    assert buttons(kw["reply_markup"]) == [("🌐 Saytda ochish", None, URL)]
    # the other chat keeps its card
    assert len(await get_redis().lrange("rov:msg:12", 0, -1)) == 1


async def test_checked_without_stored_card_is_noop():
    bot = fake_bot()
    await dispatch(envelope("rover.checked", rover=done_task(), by_name="X", to=[111]), bot)
    bot.edit_message_text.assert_not_called()
    bot.send_message.assert_not_called()
