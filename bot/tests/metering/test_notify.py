"""metering.* events: cards, edits only for the chats in `to`, rev guard, digest."""

import json

import pytest
from aiogram.methods import EditMessageText  # noqa: F401

import bot.metering  # noqa: F401  (registers metering.*)
from bot.common.rds import get_redis
from bot.metering import messages
from bot.notify.registry import dispatch, events

from .conftest import MAP, brief, buttons, envelope, fake_bot


def sent(bot):
    return bot.send_message.call_args_list


def edits(bot):
    return bot.edit_message_text.call_args_list


def test_events_registered():
    for e in ("assigned", "reminder", "digest", "changed"):
        assert f"metering.{e}" in events()


async def test_assigned_sends_card_with_keyboard_and_stores_it():
    bot = fake_bot(901)
    await dispatch(envelope("metering.assigned", metering=brief(), how="new", to=[111]), bot)
    call = sent(bot)[0]
    text = call.args[1]
    assert call.args[0] == 111
    assert "Sizga yangi zamer" in text and "25.12 (Juma) 14:30" in text
    assert "Karim &lt;b&gt;Aliyev" in text and "Yunusobod 3 &amp; 5" in text  # escaped
    assert "+998901234567" in text and "3-qavat" in text and "Operator" in text
    assert buttons(call.kwargs["reply_markup"]) == [
        ("✅ O'lchov oldim", "mt:ms:7", None),
        ("🕒 Vaqtni o'zgartirish", "mt:rs:7", None),
        ("❌ Bekor bo'ldi", "mt:cn:7", None),
        ("📍 Xarita", None, MAP),
        ("🌐 Saytda ochish", None, "https://ser-mebel.uz/meterings/7"),
    ]
    raw = await get_redis().lrange("met:msg:7", 0, -1)
    assert [json.loads(x) for x in raw] == [{"chat_id": 111, "message_id": 901, "kind": "assigned"}]
    assert 0 < await get_redis().ttl("met:msg:7") <= 30 * 24 * 3600


async def test_no_map_button_without_map_url():
    bot = fake_bot()
    m = brief(map_url="", has_point=False)
    await dispatch(envelope("metering.assigned", metering=m, how="new", to=[111]), bot)
    kb = buttons(sent(bot)[0].kwargs["reply_markup"])
    assert all(t != "📍 Xarita" for t, _, _ in kb) and kb[-1][0] == "🌐 Saytda ochish"


async def test_reassigned_header():
    bot = fake_bot()
    await dispatch(envelope("metering.assigned", metering=brief(), how="reassigned", to=[111]), bot)
    assert "Zamer sizga o'tkazildi" in sent(bot)[0].args[1]


@pytest.mark.parametrize(
    "kind,header",
    [("soon", "1 soatdan keyin zamer"), ("late", "Zamer vaqti o'tdi — natijani belgilang")],
)
async def test_reminder_headers_and_kind_stored(kind, header):
    bot = fake_bot(910)
    await dispatch(envelope("metering.reminder", metering=brief(), kind=kind, to=[111, 222]), bot)
    assert [c.args[0] for c in sent(bot)] == [111, 222]
    assert header in sent(bot)[0].args[1]
    raw = [json.loads(x) for x in await get_redis().lrange("met:msg:7", 0, -1)]
    assert [e["kind"] for e in raw] == [kind, kind]


async def _seed():
    await messages.remember(7, 111, 11, "assigned")
    await messages.remember(7, 111, 12, "late")
    await messages.remember(7, 222, 21, "assigned")


def changed(how, rev=4, n=2, **kw):
    m = kw.pop("metering", None) or brief(rev=rev)
    return envelope(
        "metering.changed",
        n,
        metering=m,
        how=how,
        by_name="Zamerchi",
        to_name=kw.pop("to_name", None),
        to=kw.pop("to", [111]),
        watchers=kw.pop("watchers", []),
    )


async def test_measured_edits_only_chats_in_to_and_keeps_entries():
    await _seed()
    bot = fake_bot()
    await dispatch(changed("measured", metering=brief(rev=4, status="metering_done")), bot)
    got = {(c.kwargs["chat_id"], c.kwargs["message_id"]) for c in edits(bot)}
    assert got == {(111, 11), (111, 12)}  # chat 222 untouched
    c = edits(bot)[0]
    assert "Fayllarni saytga yuklang" in c.args[0]
    assert buttons(c.kwargs["reply_markup"]) == [
        ("📤 Saytda yuklash", None, "https://ser-mebel.uz/meterings/7")
    ]
    assert len(await get_redis().lrange("met:msg:7", 0, -1)) == 3


async def test_old_or_repeated_rev_is_ignored():
    await _seed()
    bot = fake_bot()
    await dispatch(changed("measured", rev=5, n=2), bot)
    n_edits = len(edits(bot))
    assert n_edits == 2
    await dispatch(changed("rescheduled", rev=4, n=3), bot)  # older
    await dispatch(changed("rescheduled", rev=5, n=4), bot)  # same
    assert len(edits(bot)) == n_edits
    await dispatch(changed("rescheduled", rev=6, n=5), bot)
    assert len(edits(bot)) == n_edits + 2


async def test_rescheduled_rerenders_open_card_and_notifies_watchers():
    await _seed()
    bot = fake_bot()
    m = brief(rev=4, status="other_day", date_time="2026-12-26T09:00:00")
    await dispatch(changed("rescheduled", metering=m, watchers=[333]), bot)
    c = edits(bot)[0]
    assert "Zamer vaqti o'zgardi" in c.args[0] and "26.12 (Shanba) 09:00" in c.args[0]
    assert ("✅ O'lchov oldim", "mt:ms:7", None) in buttons(c.kwargs["reply_markup"])
    w = sent(bot)
    assert [x.args[0] for x in w] == [333]
    assert w[0].args[1] == "🕒 Zamer ko'chirildi: Karim &lt;b&gt;Aliyev → 26.12 09:00 (Zamerchi)"
    assert buttons(w[0].kwargs["reply_markup"])[0][2] == "https://ser-mebel.uz/meterings/7"


async def test_done_edits_without_keyboard_and_drops_only_those_chats():
    await _seed()
    bot = fake_bot()
    m = brief(rev=4, status="done", next_step="design_price")
    await dispatch(changed("done", metering=m), bot)
    c = edits(bot)[0]
    assert "Bajarildi — fayllar yuklandi, dizayn + narx tayinlandi" in c.args[0]
    assert c.kwargs["reply_markup"] is None
    left = [json.loads(x) for x in await get_redis().lrange("met:msg:7", 0, -1)]
    assert [e["chat_id"] for e in left] == [222]


async def test_cancelled_shows_reason_and_drops():
    await _seed()
    bot = fake_bot()
    m = brief(rev=4, status="dont_need", cancel_reason="Mijoz <rad> etdi")
    await dispatch(changed("cancelled", metering=m, to=[111, 222]), bot)
    assert "❌ Bekor bo'ldi: Mijoz &lt;rad&gt; etdi" in edits(bot)[0].args[0]
    assert await get_redis().llen("met:msg:7") == 0


async def test_reassigned_edits_only_the_old_measurers_chat():
    await _seed()
    bot = fake_bot()
    # `to` = the OLD measurer (chat 111); the brief already carries the new one
    await dispatch(changed("reassigned", to=[111], to_name="Yangi <i>"), bot)
    assert {c.kwargs["chat_id"] for c in edits(bot)} == {111}
    c = edits(bot)[0]
    assert "↪️ Yangi &lt;i&gt; ga o'tkazildi" in c.args[0] and c.kwargs["reply_markup"] is None
    left = [json.loads(x) for x in await get_redis().lrange("met:msg:7", 0, -1)]
    assert [e["chat_id"] for e in left] == [222]


async def test_changed_without_stored_cards_is_quiet():
    bot = fake_bot()
    await dispatch(changed("measured"), bot)
    assert not edits(bot) and not sent(bot)


def digest_items(n, **kw):
    return [
        brief(id=100 + i, date_time=f"2026-12-26T{9 + i % 10:02d}:00:00", **kw) for i in range(n)
    ]


async def test_digest_lists_tomorrow_with_map_link_and_agenda_button():
    bot = fake_bot()
    items = [brief(), brief(id=8, map_url="", address="Chilonzor", date_time="2026-12-26T16:00:00")]
    url = "https://ser-mebel.uz/meterings?tab=tomorrow"
    await dispatch(
        envelope("metering.digest", date="2026-12-26", items=items, to=[111], url=url), bot
    )
    assert len(sent(bot)) == 1
    text = sent(bot)[0].args[1]
    assert "Ertangi zamerlar (2)" in text
    assert (
        f'14:30 — Karim &lt;b&gt;Aliyev, +998901234567, <a href="{MAP.replace("&", "&amp;")}">Yunusobod 3 &amp; 5</a>'
        in text
    )
    assert "16:00 — " in text and "Chilonzor" in text and 'href="">' not in text
    assert buttons(sent(bot)[0].kwargs["reply_markup"]) == [("🗓 Zamerlar ro'yxati", None, url)]
    assert await get_redis().llen("met:msg:7") == 0  # not stored


async def test_digest_is_chunked_under_the_telegram_limit():
    bot = fake_bot()
    items = digest_items(60, address="A" * 120, desc="")
    url = "https://ser-mebel.uz/meterings?tab=tomorrow"
    await dispatch(
        envelope("metering.digest", date="2026-12-26", items=items, to=[111], url=url), bot
    )
    calls = sent(bot)
    assert len(calls) > 1 and all(len(c.args[1]) < 4096 for c in calls)
    assert sum(c.args[1].count(" — ") for c in calls) == 60
    # the agenda button only under the last chunk
    assert [bool(c.kwargs["reply_markup"]) for c in calls] == [False] * (len(calls) - 1) + [True]


async def test_empty_digest_sends_nothing():
    bot = fake_bot()
    await dispatch(envelope("metering.digest", date="x", items=[], to=[111], url=""), bot)
    assert not sent(bot)


async def test_messages_take_is_atomic_per_chat():
    await _seed()
    got = await messages.take(7, [111])
    assert {e["message_id"] for e in got} == {11, 12}
    assert [e["message_id"] for e in await messages.entries_for(7, [222])] == [21]
    assert await messages.take(7, [111]) == []


async def test_accept_rev_out_of_order():
    assert await messages.accept_rev(7, 3) is True
    assert await messages.accept_rev(7, 2) is False
    assert await messages.accept_rev(7, 3) is False
    assert await messages.accept_rev(7, 4) is True


async def test_accept_rev_concurrent_same_rev_only_one_wins():
    import asyncio

    res = await asyncio.gather(*(messages.accept_rev(8, 5) for _ in range(6)))
    assert res.count(True) == 1


def test_kind_of_keeps_reassigned_and_moved_headers():
    from bot.metering import texts as T

    for kind in ("assigned", "reassigned", "soon", "late", "moved"):
        plain = T.HEADERS[kind].replace("<b>", "").replace("</b>", "")
        assert T.kind_of(plain + "\n\n👤 x") == kind
        assert T.card({"status": "created", "client": {}}, kind).startswith(T.HEADERS[kind])
