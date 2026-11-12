"""Split jobs (one job, several teams = parts): events, cards, FSM and legacy compatibility."""

import json

import pytest
from aiogram.methods import EditMessageReplyMarkup, EditMessageText

import bot.painter  # noqa: F401  (registers painter.*)
from bot.backend.client import Conflict, Forbidden, ServiceRefusal
from bot.common.rds import get_redis
from bot.notify.registry import dispatch, events

from .conftest import (
    PART_URL,
    SPLIT_URL,
    buttons,
    cbs,
    done_part,
    done_task,
    envelope,
    fake_bot,
    fixture,
    part,
    ref,
    split_job,
    task,
)

A = {"id": 5, "name": "Molyar usta"}
B = {"id": 6, "name": "Molyar ikki"}
PART_DONE = "painter-parts/31/done/"
PART_DUE = "painter-parts/31/due/"
NOTE = "Eshiklar bo'yaldi, 4 ta"
TYPES = [{"id": 3, "name": "Autsors", "user": A}, {"id": 4, "name": "O'zimiz", "user": None}]


def alert(env):
    a = env.session.answers()[-1]
    return a.text if a.show_alert else None


def test_new_events_registered():
    for e in ("part_task", "part_unassigned", "part_due_ask", "part_due_set", "part_remind"):
        assert f"painter.{e}" in events()
    for e in ("part_done", "assigned", "remainder", "task", "unassigned", "due_ask", "remind"):
        assert f"painter.{e}" in events()


# ---- ready card


async def test_ready_card_has_split_link():
    bot = fake_bot(700)
    await dispatch(
        envelope(
            "painter.ready", painter=split_job(assigned_square=0, parts=[]), types=TYPES, to=[7]
        ),
        bot,
    )
    kb = bot.send_message.call_args.kwargs["reply_markup"]
    assert buttons(kb) == [
        ("Autsors · Molyar usta", "pn:ty:3:21", None),
        ("O'zimiz", "pn:ty:4:21", None),
        ("✂️ Bo'lib berish (saytda)", None, SPLIT_URL),
        ("🌐 Saytda ochish", None, PART_URL),
    ]


async def test_ready_without_split_url_still_renders():
    bot = fake_bot(701)
    await dispatch(envelope("painter.ready", painter=task(), types=TYPES, to=[7]), bot)
    assert all(
        b[2] != SPLIT_URL for b in buttons(bot.send_message.call_args.kwargs["reply_markup"])
    )


# ---- part_task


async def test_part_task_card_and_store_key():
    bot = fake_bot(710)
    await dispatch(envelope("painter.part_task", part=part(), reason="assigned", to=[111]), bot)
    args, kw = bot.send_message.call_args.args, bot.send_message.call_args.kwargs
    text = args[1]
    assert "Sizning qismingiz: 10 m² (jami 15 m²)" in text and "Autsors" in text
    assert "+998901234567" in text and "Chilonzor" not in text and "yandex" not in text
    assert buttons(kw["reply_markup"]) == [
        ("✅ Bajardim", "pn:pd:31", None),
        ("🌐 Saytda ochish", None, PART_URL),
    ]
    raw = await get_redis().lrange("pnt:msg:p31u5", 0, -1)
    assert [json.loads(x)["chat_id"] for x in raw] == [111]


async def test_part_task_outsource_hides_phone():
    bot = fake_bot()
    await dispatch(
        envelope("painter.part_task", part=part(outsource=True), reason="assigned", to=[1]), bot
    )
    text = bot.send_message.call_args.args[1]
    assert "+998901234567" not in text and "Karim Aliyev" in text


async def test_part_resized_edits_card_sends_notice_and_is_rev_guarded():
    bot = fake_bot(720)
    await dispatch(
        envelope("painter.part_task", part=part(rev=1), reason="assigned", to=[111]), bot
    )
    bot.send_message.reset_mock()
    await dispatch(
        envelope("painter.part_task", 2, part=part(rev=3, square=8.5), reason="resized", to=[111]),
        bot,
    )
    edit = bot.edit_message_text.call_args
    assert "8.5 m² (jami 15 m²)" in edit.args[0] and edit.kwargs["chat_id"] == 111
    assert [c.args[1] for c in bot.send_message.call_args_list] == [
        "📐 Maydon o'zgardi: 8.5 m² — №406"
    ]
    bot.edit_message_text.reset_mock()
    bot.send_message.reset_mock()
    await dispatch(
        envelope("painter.part_task", 3, part=part(rev=2, square=9), reason="resized", to=[111]),
        bot,
    )
    bot.edit_message_text.assert_not_called()
    bot.send_message.assert_not_called()


async def test_part_resized_without_stored_card_sends_fresh_one():
    bot = fake_bot(730)
    await dispatch(envelope("painter.part_task", part=part(rev=2), reason="resized", to=[111]), bot)
    texts = [c.args[1] for c in bot.send_message.call_args_list]
    assert texts[0].startswith("📐 Maydon o'zgardi") and "Sizning qismingiz" in texts[1]
    assert len(await get_redis().lrange("pnt:msg:p31u5", 0, -1)) == 1


# ---- part_unassigned


async def test_part_unassigned_edits_only_prev_card_and_a_b_a_is_safe():
    bot = fake_bot(740)
    await dispatch(
        envelope("painter.part_task", part=part(rev=1), reason="assigned", to=[111]), bot
    )
    await dispatch(
        envelope("painter.part_task", 2, part=part(rev=2, painter=B), reason="assigned", to=[222]),
        bot,
    )
    bot.edit_message_text.reset_mock()
    await dispatch(
        envelope("painter.part_unassigned", 3, part=part(rev=2, painter=B), prev=A, to=[111]), bot
    )
    edits = bot.edit_message_text.call_args_list
    assert len(edits) == 1 and edits[0].kwargs["chat_id"] == 111
    assert "boshqa molyarga o'tkazildi" in edits[0].args[0]
    assert cbs(edits[0].kwargs["reply_markup"]) == []
    assert len(await get_redis().lrange("pnt:msg:p31u6", 0, -1)) == 1
    # back to A (rev 4), then the late unassigned of rev 3 is ignored
    await dispatch(
        envelope("painter.part_task", 4, part=part(rev=4), reason="assigned", to=[111]), bot
    )
    bot.edit_message_text.reset_mock()
    await dispatch(
        envelope("painter.part_unassigned", 5, part=part(rev=3, painter=B), prev=A, to=[111]), bot
    )
    bot.edit_message_text.assert_not_called()


# ---- due ask / set / remind


async def test_part_due_ask_set_and_remind():
    bot = fake_bot(750)
    await dispatch(
        envelope("painter.part_task", part=part(rev=1), reason="assigned", to=[111]), bot
    )
    await dispatch(
        envelope(
            "painter.part_due_ask",
            2,
            part=part(rev=1, due_date=None),
            presets=[5, 10, 14],
            to=[222],
        ),
        bot,
    )
    kw = bot.send_message.call_args.kwargs
    assert cbs(kw["reply_markup"]) == ["pn:pdd:5:31", "pn:pdd:10:31", "pn:pdd:14:31"]
    assert "Qism: 10 m²" in bot.send_message.call_args.args[1]
    assert len(await get_redis().lrange("pnt:msg:q31", 0, -1)) == 1
    bot.send_message.reset_mock()
    await dispatch(
        envelope(
            "painter.part_due_set",
            3,
            part=part(rev=2, due_date="2026-11-25"),
            how="auto",
            to=[111],
            heads=[222],
        ),
        bot,
    )
    edits = bot.edit_message_text.call_args_list
    assert sorted(e.kwargs["chat_id"] for e in edits) == [111, 222]
    assert bot.send_message.call_args.args[1].endswith("25.11.2026 (avtomatik)")
    bot.send_message.reset_mock()
    await dispatch(
        envelope(
            "painter.part_remind", 4, part=part(), what="overdue", days_late=2, to=[1], heads=[9]
        ),
        bot,
    )
    calls = bot.send_message.call_args_list
    assert [c.args[0] for c in calls] == [1, 9]
    assert cbs(calls[0].kwargs["reply_markup"]) == ["pn:pd:31"]
    assert cbs(calls[1].kwargs["reply_markup"]) == ["pn:pdd:5:31", "pn:pdd:10:31", "pn:pdd:14:31"]
    assert not await get_redis().lrange("pnt:msg:p31u5", 1, -1)


# ---- part_done / done


async def _cards(bot):
    await dispatch(
        envelope("painter.part_task", 1, part=part(rev=1), reason="assigned", to=[111]), bot
    )
    await dispatch(envelope("painter.part_due_ask", 2, part=part(rev=1), to=[222]), bot)
    await get_redis().rpush(
        "pnt:msg:t21u5", json.dumps({"chat_id": 111, "message_id": 5, "kind": "task"})
    )
    await get_redis().rpush(
        "pnt:msg:h21", json.dumps({"chat_id": 222, "message_id": 6, "kind": "head"})
    )
    bot.send_message.reset_mock()
    bot.edit_message_text.reset_mock()


async def test_part_done_not_last_sends_message_and_edits():
    bot = fake_bot(760)
    await _cards(bot)
    await dispatch(
        envelope(
            "painter.part_done",
            3,
            part=done_part(rev=3),
            by_name="Molyar usta",
            job_done=False,
            to=[222, 7],
            heads=[222],
            painters=[111],
        ),
        bot,
    )
    sent = bot.send_message.call_args_list
    assert [c.args[0] for c in sent] == [222, 7]
    assert "Molyar qismi tayyor — №406: Autsors 10 m²" in sent[0].args[1]
    edits = bot.edit_message_text.call_args_list
    assert sorted(e.kwargs["chat_id"] for e in edits) == [111, 222]
    assert all(cbs(e.kwargs["reply_markup"]) == [] for e in edits)


async def test_part_done_job_done_no_message_then_done_lists_all_teams():
    bot = fake_bot(770)
    await _cards(bot)
    await dispatch(
        envelope(
            "painter.part_done",
            3,
            part=done_part(rev=3),
            job_done=True,
            to=[222, 7],
            heads=[222],
            painters=[111],
        ),
        bot,
    )
    bot.send_message.assert_not_called()
    assert len(bot.edit_message_text.call_args_list) == 2
    bot.edit_message_text.reset_mock()
    job = split_job(
        rev=8,
        state="done",
        note="A: bo'yaldi",
        parts=[
            ref(31, "Autsors", 10.0, A, state="done"),
            ref(32, "Proizvodstva", 5.0, B, state="done"),
        ],
    )
    await dispatch(
        envelope(
            "painter.done",
            4,
            painter=job,
            by_name="Molyar usta",
            to=[222, 7],
            heads=[222],
            painters=[111, 112],
        ),
        bot,
    )
    sent = bot.send_message.call_args_list
    assert [c.args[0] for c in sent] == [222, 7]
    text = sent[0].args[1]
    assert "Molyar tayyor" in text and "Autsors — 10 m² (Molyar usta)" in text
    assert "Proizvodstva — 5 m² (Molyar ikki)" in text
    # legacy cards (pre-deploy) of the job are edited too
    assert 111 in [e.kwargs["chat_id"] for e in bot.edit_message_text.call_args_list]


# ---- assigned / remainder


async def test_assigned_edits_all_ready_cards_and_ignores_older_rev():
    bot = fake_bot(780)
    await dispatch(envelope("painter.ready", painter=task(rev=2), types=TYPES, to=[7, 8]), bot)
    bot.edit_message_text.reset_mock()
    await dispatch(envelope("painter.assigned", 2, painter=split_job(rev=6), to=[7, 8]), bot)
    edits = bot.edit_message_text.call_args_list
    assert sorted(e.kwargs["chat_id"] for e in edits) == [7, 8]
    assert "✅ Jamoalar: Autsors — 10 m², Proizvodstva — 5 m²" in edits[0].args[0]
    assert cbs(edits[0].kwargs["reply_markup"]) == []
    assert await get_redis().lrange("pnt:msg:r21", 0, -1) == []
    bot.edit_message_text.reset_mock()
    await dispatch(envelope("painter.assigned", 3, painter=split_job(rev=5), to=[7, 8]), bot)
    bot.edit_message_text.assert_not_called()


async def test_assigned_with_remainder_keeps_cards_and_split_link():
    bot = fake_bot(790)
    await dispatch(envelope("painter.ready", painter=task(rev=2), types=TYPES, to=[7]), bot)
    bot.edit_message_text.reset_mock()
    job = split_job(rev=4, assigned_square=10.0, parts=[ref(31, "Autsors", 10.0, A)])
    await dispatch(envelope("painter.assigned", 2, painter=job, to=[7]), bot)
    e = bot.edit_message_text.call_args
    assert "Taqsimlanmagan: 5 m²" in e.args[0]
    assert ("✂️ Bo'lib berish (saytda)", None, SPLIT_URL) in buttons(e.kwargs["reply_markup"])
    assert len(await get_redis().lrange("pnt:msg:r21", 0, -1)) == 1


async def test_remainder_message_to_heads():
    bot = fake_bot()
    job = split_job(assigned_square=10.0)
    await dispatch(envelope("painter.remainder", painter=job, remainder=5.0, to=[222, 223]), bot)
    calls = bot.send_message.call_args_list
    assert [c.args[0] for c in calls] == [222, 223]
    assert "№406" in calls[0].args[1] and "5 m² hali hech kimga berilmagan" in calls[0].args[1]
    assert "jamoaga bering" in calls[0].args[1]
    assert ("✂️ Bo'lib berish (saytda)", None, SPLIT_URL) in buttons(
        calls[0].kwargs["reply_markup"]
    )


# ---- FSM: part done


def part_card_kb():
    return {
        "inline_keyboard": [
            [{"text": "✅ Bajardim", "callback_data": "pn:pd:31"}],
            [{"text": "🌐 Saytda ochish", "url": PART_URL}],
        ]
    }


async def part_start(env):
    await env.cb("pn:pd:31", text="🎨 Yangi Molyar ishi", markup=part_card_kb())


async def part_confirm(env):
    await part_start(env)
    await env.text(NOTE)


async def test_part_done_flow(env):
    env.backend.routes[("POST", PART_DONE)] = {"part": done_part()}
    await part_start(env)
    assert await env.state() == "PainterDone:note"
    await env.text(NOTE)
    last = env.session.last()
    assert cbs(last.reply_markup) == ["pn:psy:31", "pn:pse:31", "pn:q"]
    await env.cb("pn:psy:31", text="Tekshiring")
    assert env.backend.to(PART_DONE)[0][2] == {"note": NOTE}
    card = [x for x in env.session.of(EditMessageText) if "Yangi Molyar ishi" in x.text][-1]
    assert "Sizning qismingiz: 10 m²" in card.text and "✅ Bajarildi — Molyar usta" in card.text
    assert buttons(card.reply_markup) == [("🌐 Saytda ochish", None, PART_URL)]
    assert await env.state() is None


async def test_part_restart_and_cross_kind_is_stale(env):
    await part_confirm(env)
    await env.cb("pn:se:31", text="x")  # the job flavour must not touch a part flow
    assert alert(env) == "Bu tugma eskirgan."
    await part_confirm(env)
    await env.cb("pn:pse:31", text="x")
    assert await env.state() == "PainterDone:note"


async def test_part_submit_wrong_id_is_stale(env):
    await part_confirm(env)
    await env.cb("pn:psy:99", text="x")
    assert alert(env) == "Bu tugma eskirgan."
    assert not env.backend.to(PART_DONE)


async def test_part_400_note_reasks_and_other_400_alerts(env):
    env.backend.routes[("POST", PART_DONE)] = ServiceRefusal(
        "Izoh juda qisqa", status=400, field="note"
    )
    await part_confirm(env)
    await env.cb("pn:psy:31", text="x")
    assert await env.state() == "PainterDone:note" and "Izoh juda qisqa" in env.session.last().text
    env.backend.routes[("POST", PART_DONE)] = ServiceRefusal("Rover tugamagan", status=400)
    await env.text(NOTE)
    await env.cb("pn:psy:31", text="x")
    assert alert(env) == "Rover tugamagan" and await env.state() is None


async def test_part_409_link_only_and_403_no_keyboard(env):
    env.backend.routes[("POST", PART_DONE)] = Conflict("Bu qism allaqachon bajarilgan", status=409)
    await part_confirm(env)
    await env.cb("pn:psy:31", text="x")
    assert alert(env) == "Bu qism allaqachon bajarilgan" and await env.state() is None
    kb = [c for c in env.session.of(EditMessageReplyMarkup) if c.message_id == 9]
    assert ("🌐 Saytda ochish", None, PART_URL) in buttons(kb[-2].reply_markup)
    env.session.calls.clear()
    env.backend.routes[("POST", PART_DONE)] = Forbidden("Ruxsat yo'q", status=403)
    await part_confirm(env)
    await env.cb("pn:psy:31", text="x")
    assert alert(env) == "Ruxsat yo'q" and await env.state() is None
    kb = [c for c in env.session.of(EditMessageReplyMarkup) if c.message_id == 9]
    assert not buttons(kb[-1].reply_markup)


async def test_flow_opened_before_deploy_posts_job_path(env):
    import time

    env.backend.routes[("POST", "painters/21/done/")] = {"painter": done_task()}
    await env.set_state(
        "PainterDone:confirm", pid=21, chat_id=555, message_id=9, note=NOTE, ts=time.time(), url=""
    )
    await env.cb("pn:sy:21", text="x")
    assert env.backend.to("painters/21/done/")[0][2] == {"note": NOTE}
    assert not env.backend.to(PART_DONE)


# ---- part deadline preset


def head_part_kb():
    return {
        "inline_keyboard": [
            [{"text": "+10 kun", "callback_data": "pn:pdd:10:31"}],
            [{"text": "🌐 Saytda ochish", "url": PART_URL}],
        ]
    }


async def test_part_due_preset_posts_days_and_edits(env):
    env.backend.routes[("POST", PART_DUE)] = {"part": part(due_date="2026-11-25", rev=4)}
    await env.cb("pn:pdd:10:31", text="x", markup=head_part_kb())
    assert env.backend.to(PART_DUE)[0][2] == {"days": 10}
    e = env.session.of(EditMessageText)[-1]
    assert "25.11.2026" in e.text and "Qism: 10 m²" in e.text
    assert cbs(e.reply_markup) == ["pn:pdd:5:31", "pn:pdd:10:31", "pn:pdd:14:31"]


async def test_part_due_preset_409_strips_presets_403_alerts_only(env):
    env.backend.routes[("POST", PART_DUE)] = Conflict("Bu qism allaqachon bajarilgan", status=409)
    await env.cb("pn:pdd:10:31", text="x", markup=head_part_kb())
    assert alert(env) == "Bu qism allaqachon bajarilgan"
    kb = env.session.of(EditMessageReplyMarkup)[-1].reply_markup
    assert cbs(kb) == [] and ("🌐 Saytda ochish", None, PART_URL) in buttons(kb)
    env.session.calls.clear()
    env.backend.routes[("POST", PART_DUE)] = Forbidden("Ruxsat yo'q", status=403)
    await env.cb("pn:pdd:10:31", text="x", markup=head_part_kb())
    assert alert(env) == "Ruxsat yo'q" and not env.session.of(EditMessageReplyMarkup)


# ---- legacy callbacks keep their paths


async def test_legacy_callbacks_use_old_paths_and_show_split_conflict(env):
    msg = "Ish bo'lingan — o'z qismingizni tanlang (saytda)"
    for path, data in (
        ("painters/21/due/", "pn:dd:10:21"),
        ("painters/21/type/", "pn:ty:3:21"),
    ):
        env.backend.routes[("POST", path)] = Conflict(msg, status=409)
        await env.cb(data, text="x")
        assert env.backend.to(path)
        assert alert(env) == msg
        env.session.calls.clear()
    env.backend.routes[("POST", "painters/21/done/")] = Conflict(msg, status=409)
    await env.set_state(
        "PainterDone:confirm",
        pid=21,
        chat_id=5,
        message_id=9,
        note=NOTE,
        ts=__import__("time").time(),
    )
    await env.cb("pn:sy:21", text="x")
    assert alert(env) == msg


# ---- one-tap pick on a split-result card


async def test_team_pick_with_parts_response_lists_teams(env):
    env.backend.routes[("POST", "painters/21/type/")] = {"painter": split_job()}
    await env.cb("pn:ty:3:21", text="x")
    e = env.session.of(EditMessageText)[-1]
    assert "✅ Jamoalar: Autsors — 10 m², Proizvodstva — 5 m²" in e.text


# ---- contract fixtures (when django-dev wrote them)

NEW_EVENTS = [
    "part_task", "part_unassigned", "part_due_ask", "part_due_set",
    "part_remind", "part_done", "assigned", "remainder",
]  # fmt: skip


@pytest.mark.parametrize("event", NEW_EVENTS)
async def test_new_event_fixtures_render(event):
    fx = fixture(f"event.painter.{event}")
    if fx is None:
        pytest.skip("fixture not written yet")
    env_ = (
        fx
        if "event" in fx
        else {"id": "00000000-0000-0000-0000-000000009801", "event": f"painter.{event}", "data": fx}
    )
    await dispatch(env_, fake_bot())


def test_part_dto_fixture_renders():
    from bot.painter import texts as T

    dto = fixture("dto.painter_part_task.1")
    resp = fixture("misc.painter_part_done_response")
    if dto is None and resp is None:
        pytest.skip("fixtures not written yet")
    for p in (dto, (resp or {}).get("part")):
        if p:
            assert "Buyurtma" in T.part_task_card(p) and "Buyurtma" in T.part_head_card(p)


# ---- review fixes


async def test_team_pick_409_keeps_split_link(env):
    env.backend.routes[("POST", "painters/21/type/")] = Conflict("Ish bo'lingan", status=409)
    kb = {
        "inline_keyboard": [
            [{"text": "Autsors", "callback_data": "pn:ty:3:21"}],
            [{"text": "✂️ Bo'lib berish (saytda)", "url": SPLIT_URL}],
            [{"text": "🌐 Saytda ochish", "url": PART_URL}],
        ]
    }
    await env.cb("pn:ty:3:21", text="x", markup=kb)
    out = env.session.of(EditMessageReplyMarkup)[-1].reply_markup
    assert cbs(out) == []
    assert buttons(out) == [
        ("✂️ Bo'lib berish (saytda)", None, SPLIT_URL),
        ("🌐 Saytda ochish", None, PART_URL),
    ]


async def test_team_pick_409_rebuilds_split_link_from_site_url(env):
    env.backend.routes[("POST", "painters/21/type/")] = Conflict("Ish bo'lingan", status=409)
    kb = {
        "inline_keyboard": [
            [{"text": "Autsors", "callback_data": "pn:ty:3:21"}],
            [{"text": "🌐 Saytda ochish", "url": PART_URL}],
        ]
    }
    await env.cb("pn:ty:3:21", text="x", markup=kb)
    out = env.session.of(EditMessageReplyMarkup)[-1].reply_markup
    assert ("✂️ Bo'lib berish (saytda)", None, SPLIT_URL) in buttons(out)


async def test_part_task_assigned_late_older_envelope_sends_nothing():
    bot = fake_bot(800)
    await dispatch(
        envelope("painter.part_task", 1, part=part(rev=3), reason="assigned", to=[111]), bot
    )
    assert bot.send_message.call_count == 1  # the first card is always sent
    await dispatch(
        envelope("painter.part_task", 2, part=part(rev=2), reason="assigned", to=[111]), bot
    )
    await dispatch(
        envelope("painter.part_task", 3, part=part(rev=3), reason="assigned", to=[111]), bot
    )
    assert bot.send_message.call_count == 1
    await dispatch(
        envelope("painter.part_task", 4, part=part(rev=4), reason="assigned", to=[111]), bot
    )
    assert bot.send_message.call_count == 2


async def test_legacy_done_response_outsource_hides_phone(env):
    import time

    env.backend.routes[("POST", "painters/21/done/")] = {"painter": done_task(outsource=True)}
    await env.set_state(
        "PainterDone:confirm", pid=21, chat_id=555, message_id=9, note=NOTE, ts=time.time(), url=""
    )
    await env.cb("pn:sy:21", text="x")
    card = [x for x in env.session.of(EditMessageText) if "Yangi Molyar ishi" in x.text][-1]
    assert "+998901234567" not in card.text and "Karim Aliyev" in card.text


async def test_removed_part_edits_the_worker_card():
    # removal: the backend bumps the part rev, so the guarded unassigned edit applies
    bot = fake_bot(810)
    await dispatch(
        envelope("painter.part_task", 1, part=part(rev=1), reason="assigned", to=[111]), bot
    )
    bot.edit_message_text.reset_mock()
    await dispatch(envelope("painter.part_unassigned", 2, part=part(rev=2), prev=A, to=[111]), bot)
    edits = bot.edit_message_text.call_args_list
    assert len(edits) == 1 and edits[0].kwargs["chat_id"] == 111
    assert cbs(edits[0].kwargs["reply_markup"]) == []


async def test_first_card_sent_even_if_a_newer_due_set_arrived_first():
    bot = fake_bot(820)
    await dispatch(
        envelope(
            "painter.part_due_set",
            1,
            part=part(rev=2, due_date="2026-11-25"),
            how="set",
            by_name="Rahbar",
            to=[111],
            heads=[],
        ),
        bot,
    )
    bot.send_message.reset_mock()
    await dispatch(
        envelope("painter.part_task", 2, part=part(rev=1), reason="assigned", to=[111]), bot
    )
    # the task card with «Bajardim» is not lost
    assert any(
        "pn:pd:31" in cbs(c.kwargs.get("reply_markup"))
        for c in bot.send_message.call_args_list
        if c.kwargs.get("reply_markup")
    )
