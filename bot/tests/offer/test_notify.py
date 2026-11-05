"""offer.* events: cards + stored role, edits only for the chats in `to`, rev guard,
final hows drop the card, due_moved keeps the keyboard, watchers, order_ready."""

import json

import pytest

import bot.offer  # noqa: F401  (registers offer.*)
from bot.common.rds import get_redis
from bot.notify.registry import dispatch, events

from .conftest import buttons, envelope, fake_bot, price_task, task

DESIGN_URL = "https://ser-mebel.uz/designs/12"


def sent(bot):
    return bot.send_message.call_args_list


def edits(bot):
    return bot.edit_message_text.call_args_list


def at(c):
    """(chat_id, message_id) of an edit call."""
    return (c.kwargs["chat_id"], c.kwargs["message_id"])


async def stored(key="d12"):
    return [json.loads(x) for x in await get_redis().lrange(f"off:msg:{key}", 0, -1)]


def test_events_registered():
    for e in ("assigned", "reminder", "present", "changed", "order_ready"):
        assert f"offer.{e}" in events()


async def test_assigned_design_card_no_tayyor_button_and_stored():
    bot = fake_bot(901)
    await dispatch(envelope("offer.assigned", task=task(), how="new", comment=None, to=[111]), bot)
    call = sent(bot)[0]
    text = call.args[1]
    assert call.args[0] == 111
    assert "Sizga yangi dizayn" in text and "25.12 (Juma) 18:00" in text
    assert "Karim &lt;b&gt;Aliyev" in text and "Yunusobod 3 &amp; 5" in text
    assert "+998901234567" in text and "Zamerchi" in text and "lift yo'q" in text
    assert "Menejer" in text and "saytda «Tayyor»ni bosing" in text
    assert buttons(call.kwargs["reply_markup"]) == [
        ("🕒 Muddatni o'zgartirish", "of:dm:d:12", None),
        ("🌐 Saytda ochish", None, DESIGN_URL),
    ]
    assert await stored() == [{"chat_id": 111, "message_id": 901, "kind": "new", "role": "work"}]
    assert 0 < await get_redis().ttl("off:msg:d12") <= 30 * 24 * 3600


async def test_assigned_price_header_and_prefix_keys():
    bot = fake_bot(902)
    await dispatch(envelope("offer.assigned", task=price_task(), how="new", to=[111]), bot)
    assert "Sizga narx hisoblash" in sent(bot)[0].args[1]
    assert buttons(sent(bot)[0].kwargs["reply_markup"])[0][1] == "of:dm:p:15"
    assert len(await stored("p15")) == 1


@pytest.mark.parametrize(
    "how,header",
    [
        ("reassigned", "Dizayn sizga o'tkazildi"),
        ("started", "Dizayn tasdiqlandi — narxni hisoblang"),
    ],
)
async def test_assigned_headers(how, header):
    bot = fake_bot()
    await dispatch(envelope("offer.assigned", task=task(), how=how, to=[111]), bot)
    assert header in sent(bot)[0].args[1]


async def test_assigned_changes_shows_round_and_comment():
    bot = fake_bot()
    t = task(round=2, last_comment="Rang <qora> bo'lsin")
    await dispatch(
        envelope("offer.assigned", task=t, how="changes", comment="Rang <qora> bo'lsin", to=[111]),
        bot,
    )
    text = sent(bot)[0].args[1]
    assert "Mijoz o'zgartirish so'radi (2-raund)" in text
    assert "Rang &lt;qora&gt; bo'lsin" in text
    assert (await stored())[0]["kind"] == "changes"


async def test_assigned_without_due_says_no_deadline():
    bot = fake_bot()
    await dispatch(envelope("offer.assigned", task=task(due_at=None), how="new", to=[111]), bot)
    assert "Muddat yo'q" in sent(bot)[0].args[1]


@pytest.mark.parametrize(
    "kind,header",
    [("late", "Muddat o'tdi"), ("overdue", "Muddat o'tib ketdi")],
)
async def test_reminder_headers_and_kind_stored(kind, header):
    bot = fake_bot(910)
    await dispatch(envelope("offer.reminder", task=task(), kind=kind, to=[111, 222]), bot)
    assert [c.args[0] for c in sent(bot)] == [111, 222]
    assert header in sent(bot)[0].args[1]
    assert [(e["kind"], e["role"]) for e in await stored()] == [(kind, "work")] * 2


async def test_reminder_soon_today_vs_tomorrow(monkeypatch):
    from datetime import datetime

    from bot.common import fmt

    bot = fake_bot()
    monkeypatch.setattr(fmt, "now", lambda: datetime(2026, 12, 24, 9, 0))
    await dispatch(envelope("offer.reminder", task=task(), kind="soon", to=[111]), bot)
    assert "Ertaga muddat" in sent(bot)[0].args[1]
    monkeypatch.setattr(fmt, "now", lambda: datetime(2026, 12, 25, 9, 0))
    await dispatch(envelope("offer.reminder", task=task(), kind="soon", to=[111], n=2), bot)
    assert "Bugun muddat" in sent(bot)[1].args[1]


async def test_present_design_manager_card():
    bot = fake_bot(920)
    await dispatch(envelope("offer.present", task=task(stage="review"), how="ready", to=[222]), bot)
    call = sent(bot)[0]
    assert "Dizayn tayyor — mijozga ko'rsating" in call.args[1]
    assert buttons(call.kwargs["reply_markup"]) == [
        ("✅ Tasdiqladi", "of:ok:d:12", None),
        ("✏️ O'zgartirish kerak", "of:ch:d:12", None),
        ("❌ Rad etdi", "of:no:d:12", None),
        ("🌐 Saytda ochish", None, "https://ser-mebel.uz/presentations?open=d12"),
    ]
    assert (await stored())[0] == {
        "chat_id": 222,
        "message_id": 920,
        "kind": "ready",
        "role": "present",
    }


async def test_present_price_buttons_and_reminder_header():
    bot = fake_bot()
    await dispatch(
        envelope("offer.present", task=price_task(stage="review"), how="reminder", to=[222]), bot
    )
    call = sent(bot)[0]
    assert "Mijoz javobi kutilmoqda: narx" in call.args[1]
    assert [b[0] for b in buttons(call.kwargs["reply_markup"])][:3] == [
        "✅ Rozi",
        "🔁 Qayta hisoblash",
        "❌ Narxi qoniqtirmadi",
    ]


async def test_changed_old_rev_skipped():
    from bot.offer.notify import store

    await store.remember("d12", 111, 11, "new", "work")
    b = fake_bot()
    await dispatch(envelope("offer.changed", task=task(rev=5), how="due_moved", to=[111]), b)
    assert len(edits(b)) == 1
    b2 = fake_bot()
    await dispatch(envelope("offer.changed", task=task(rev=5), how="due_moved", to=[111], n=2), b2)
    await dispatch(envelope("offer.changed", task=task(rev=4), how="due_moved", to=[111], n=3), b2)
    assert edits(b2) == []


async def test_due_moved_keeps_keyboard_and_edits_only_to_chats_and_notifies_watchers():
    from bot.offer.notify import store

    await store.remember("d12", 111, 11, "new", "work")
    await store.remember("d12", 222, 21, "ready", "present")
    b = fake_bot()
    t = task(rev=4, due_at="2026-12-26T18:00:00")
    await dispatch(
        envelope(
            "offer.changed", task=t, how="due_moved", by_name="Ali <x>", to=[111], watchers=[333]
        ),
        b,
    )
    assert [at(c) for c in edits(b)] == [(111, 11)]
    e = edits(b)[0]
    assert "26.12" in e.args[0] and e.kwargs["reply_markup"] is not None
    assert buttons(e.kwargs["reply_markup"])[0][1] == "of:dm:d:12"
    assert len(await stored()) == 2  # nothing forgotten
    w = sent(b)[0]
    assert w.args[0] == 333
    assert "Muddat ko'chirildi" in w.args[1] and "Karim &lt;b&gt;Aliyev" in w.args[1]
    assert "26.12 18:00" in w.args[1] and "Ali &lt;x&gt;" in w.args[1]


@pytest.mark.parametrize(
    "how,answer,extra,line",
    [
        ("done", None, {}, "✅ Tayyor — menejerga yuborildi"),
        ("reassigned", None, {"to_name": "Yangi <z>"}, "↪️ Yangi &lt;z&gt; ga o'tkazildi"),
        ("cancelled", None, {}, "❌ Bekor qilindi"),
    ],
)
async def test_final_work_hows_edit_without_keyboard_and_forget(how, answer, extra, line):
    from bot.offer.notify import store

    await store.remember("d12", 111, 11, "new", "work")
    await store.remember("d12", 111, 12, "late", "work")
    await store.remember("d12", 222, 21, "ready", "present")
    b = fake_bot()
    await dispatch(envelope("offer.changed", task=task(rev=6), how=how, to=[111], **extra), b)
    assert sorted(at(c)[1] for c in edits(b)) == [11, 12]
    for c in edits(b):
        assert line in c.args[0] and c.kwargs["reply_markup"] is None
    # the other chat keeps its card
    assert [(e["chat_id"], e["message_id"]) for e in await stored()] == [(222, 21)]


@pytest.mark.parametrize(
    "kind_task,answer,line",
    [
        (task(rev=7, stage="approved"), "approved", "✅ Mijoz tasdiqladi"),
        (price_task(rev=7, stage="approved"), "approved", "✅ Mijoz rozi"),
        (task(rev=7, stage="work", round=2), "changes", "✏️ Qayta ishlashga qaytdi"),
        (price_task(rev=7, stage="work"), "recalc", "✏️ Qayta ishlashga qaytdi"),
        (
            task(rev=7, stage="declined", last_comment="Yoqmadi <3"),
            "declined",
            "❌ Rad etildi: Yoqmadi &lt;3",
        ),
    ],
)
async def test_answered_finishes_the_manager_card(kind_task, answer, line):
    from bot.offer.notify import store

    key = "p15" if kind_task["kind"] == "price" else "d12"
    await store.remember(key, 222, 21, "ready", "present")
    await store.remember(key, 111, 11, "new", "work")  # not in `to`
    b = fake_bot()
    await dispatch(
        envelope("offer.changed", task=kind_task, how="answered", answer=answer, to=[222]), b
    )
    assert [at(c) for c in edits(b)] == [(222, 21)]
    assert line in edits(b)[0].args[0] and edits(b)[0].kwargs["reply_markup"] is None
    assert [e["chat_id"] for e in await stored(key)] == [111]


async def test_answered_leaves_a_work_card_of_the_same_person_alone():
    from bot.offer.notify import store

    await store.remember("d12", 222, 20, "new", "work")
    await store.remember("d12", 222, 21, "ready", "present")
    b = fake_bot()
    await dispatch(
        envelope("offer.changed", task=task(rev=8), how="answered", answer="approved", to=[222]), b
    )
    assert [at(c)[1] for c in edits(b)] == [21]
    assert [e["message_id"] for e in await stored()] == [20]


async def test_order_ready_text_and_url():
    b = fake_bot()
    await dispatch(
        envelope(
            "offer.order_ready",
            task=price_task(stage="approved"),
            to=[111, 222],
            url="https://ser-mebel.uz/orders/new?metering=7",
        ),
        b,
    )
    assert [c.args[0] for c in sent(b)] == [111, 222]
    text = sent(b)[0].args[1]
    assert "Karim &lt;b&gt;Aliyev" in text and "narxga rozi — buyurtma rasmiylashtiring" in text
    assert buttons(sent(b)[0].kwargs["reply_markup"])[0][2] == (
        "https://ser-mebel.uz/orders/new?metering=7"
    )
    assert await stored("p15") == []
