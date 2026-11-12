"""Painter buttons: «Bajardim» FSM and head presets (real dispatcher, scripted backend)."""

import time

from aiogram.methods import EditMessageReplyMarkup, EditMessageText

from bot.backend.client import BackendDown, Conflict, Forbidden, NotFound, ServiceRefusal
from bot.crm.texts import NEW_BTN
from bot.painter.api import DOWN_TEXT

from .conftest import URL, buttons, cbs, done_task, task

DONE = "painters/21/done/"
DUE = "painters/21/due/"
TYPE = "painters/21/type/"
NOTE = "Eshiklar bo'yaldi, 4 ta"
TCARD = "🎨 Yangi Molyar ishi\n\nBuyurtma №406"


def card_kb():
    return {
        "inline_keyboard": [
            [{"text": "✅ Bajardim", "callback_data": "pn:dn:21"}],
            [{"text": "🌐 Saytda ochish", "url": URL}],
        ]
    }


async def start(env):
    await env.cb("pn:dn:21", text=TCARD, markup=card_kb())


async def to_confirm(env, note=NOTE):
    await start(env)
    await env.text(note)


def alert(env):
    a = env.session.answers()[-1]
    return a.text if a.show_alert else None


async def test_full_path_posts_note_and_edits_card(env):
    env.backend.routes[("POST", DONE)] = {"painter": done_task()}
    await start(env)
    assert await env.state() == "PainterDone:note"
    assert "nima ish qilindi" in env.session.last().text
    await env.text(NOTE)
    assert await env.state() == "PainterDone:confirm"
    last = env.session.last()
    assert NOTE in last.text
    assert cbs(last.reply_markup) == ["pn:sy:21", "pn:se:21", "pn:q"]
    await env.cb("pn:sy:21", text="Tekshiring")
    assert env.backend.to(DONE)[0][2] == {"note": NOTE}
    e = env.session.of(EditMessageText)
    card = [x for x in e if "Yangi Molyar ishi" in x.text][-1]
    assert card.message_id == 9 and "✅ Bajarildi — Molyar usta" in card.text
    assert buttons(card.reply_markup) == [("🌐 Saytda ochish", None, URL)]
    assert any(x.text == "✅ Bajarildi" for x in e)
    assert await env.state() is None
    assert env.session.answers()[-1].text == "✅ Bajarildi"


async def test_short_and_long_note_reask(env):
    await start(env)
    await env.text("ok")
    assert "juda qisqa" in env.session.last().text
    assert await env.state() == "PainterDone:note"
    await env.text("x" * 2001)
    assert "juda uzun" in env.session.last().text
    assert await env.state() == "PainterDone:note"
    await env.text("yetarli izoh")
    assert await env.state() == "PainterDone:confirm"


async def test_restart_goes_back_to_note(env):
    await to_confirm(env)
    await env.cb("pn:se:21", text="Tekshiring")
    assert await env.state() == "PainterDone:note"
    assert "nima ish qilindi" in env.session.last().text


async def test_400_field_note_reasks(env):
    env.backend.routes[("POST", DONE)] = ServiceRefusal("Izoh juda qisqa", status=400, field="note")
    await to_confirm(env)
    await env.cb("pn:sy:21", text="Tekshiring")
    assert await env.state() == "PainterDone:note"
    assert "Izoh juda qisqa" in env.session.last().text


async def test_400_other_clears_and_alerts(env):
    env.backend.routes[("POST", DONE)] = ServiceRefusal("Rover tugamagan", status=400)
    await to_confirm(env)
    await env.cb("pn:sy:21", text="Tekshiring")
    assert alert(env) == "Rover tugamagan" and await env.state() is None


async def test_409_and_404_clear_alert_and_link_only(env):
    for exc in (Conflict("Allaqachon bajarilgan", status=409), NotFound("Topilmadi", status=404)):
        env.backend.routes[("POST", DONE)] = exc
        await to_confirm(env)
        await env.cb("pn:sy:21", text="Tekshiring")
        assert alert(env) == str(exc.detail)
        assert await env.state() is None
        kb = [c for c in env.session.of(EditMessageReplyMarkup) if c.message_id == 9]
        # the task card gets the link only (the summary message, same id here, is then stripped)
        assert kb and all(not cbs(c.reply_markup) for c in kb)
        assert ("🌐 Saytda ochish", None, URL) in buttons(kb[-2].reply_markup)
        env.session.calls.clear()


async def test_403_clears_and_removes_keyboard(env):
    env.backend.routes[("POST", DONE)] = Forbidden("Ruxsat yo'q", status=403)
    await to_confirm(env)
    await env.cb("pn:sy:21", text="Tekshiring")
    assert alert(env) == "Ruxsat yo'q" and await env.state() is None
    kb = [c for c in env.session.of(EditMessageReplyMarkup) if c.message_id == 9]
    assert kb and not buttons(kb[-1].reply_markup)


async def test_backend_down_clears(env):
    env.backend.routes[("POST", DONE)] = BackendDown("down")
    await to_confirm(env)
    await env.cb("pn:sy:21", text="Tekshiring")
    assert alert(env) == DOWN_TEXT and await env.state() is None


async def test_ttl_expired_is_stale(env):
    await env.set_state(
        "PainterDone:note", pid=21, chat_id=555, message_id=9, ts=time.time() - 4000
    )
    await env.text(NOTE)
    assert env.session.last().text == "Bu tugma eskirgan."
    assert await env.state() is None


async def test_busy_with_other_feature_state(env):
    await env.set_state("Lead:name")
    await start(env)
    assert alert(env) == "Avval boshqa amalni tugating"
    assert await env.state() == "Lead:name"


async def test_cancel_button_and_command(env):
    await start(env)
    await env.cb("pn:q", text="x")
    assert await env.state() is None
    await start(env)
    await env.text("/bekor")
    assert await env.state() is None and env.session.last().text == "Bekor qilindi."


async def test_menu_button_clears_and_skips(env):
    await start(env)
    await env.text(NEW_BTN)
    assert await env.state() != "PainterDone:note"
    assert not env.backend.to(DONE)


async def test_submit_without_state_is_stale(env):
    await env.cb("pn:sy:21", text="Tekshiring")
    assert alert(env) == "Bu tugma eskirgan."
    assert not env.backend.to(DONE)


# ---- head presets


def head_kb():
    return {
        "inline_keyboard": [
            [{"text": "+10 kun", "callback_data": "pn:dd:10:21"}],
            [{"text": "🌐 Saytda ochish", "url": URL}],
        ]
    }


async def test_due_preset_posts_days_and_edits(env):
    env.backend.routes[("POST", DUE)] = {"painter": task(due_date="2026-11-25", rev=4)}
    await env.cb("pn:dd:10:21", text="🗓 Molyar uchun muddat qo'ying", markup=head_kb())
    assert env.backend.to(DUE)[0][2] == {"days": 10}
    e = env.session.of(EditMessageText)[-1]
    assert "Molyar uchun muddat qo'ying" in e.text and "25.11.2026" in e.text
    assert cbs(e.reply_markup) == ["pn:dd:5:21", "pn:dd:10:21", "pn:dd:14:21"]


async def test_due_preset_409_strips_presets(env):
    env.backend.routes[("POST", DUE)] = Conflict("Molyar ishi bajarilgan", status=409)
    await env.cb("pn:dd:10:21", text="x", markup=head_kb())
    assert alert(env) == "Molyar ishi bajarilgan"
    kb = env.session.of(EditMessageReplyMarkup)[-1].reply_markup
    assert cbs(kb) == [] and ("🌐 Saytda ochish", None, URL) in buttons(kb)


async def test_due_preset_403_alerts_only(env):
    env.backend.routes[("POST", DUE)] = Forbidden("Ruxsat yo'q", status=403)
    await env.cb("pn:dd:14:21", text="x", markup=head_kb())
    assert alert(env) == "Ruxsat yo'q"
    assert not env.session.of(EditMessageReplyMarkup)


def team_kb():
    return {
        "inline_keyboard": [
            [{"text": "Emal", "callback_data": "pn:ty:3:21"}],
            [{"text": "🌐 Saytda ochish", "url": URL}],
        ]
    }


async def test_team_pick_posts_type_and_edits_all_cards(env):
    from bot.painter import messages

    await messages.remember("r21", 999, 55, "team")  # another head's card
    env.backend.routes[("POST", TYPE)] = {"painter": task(rev=4)}
    await env.cb("pn:ty:3:21", text="🎨 Rover tayyor", markup=team_kb())
    assert env.backend.to(TYPE)[0][2] == {"type_id": 3}
    edits = env.session.of(EditMessageText)
    assert all("✅ Jamoa: Emal (Molyar usta)" in e.text for e in edits)
    assert len(edits) == 2
    assert all(cbs(e.reply_markup) == [] for e in edits)
    assert env.session.answers()[-1].text == "✅ Tanlandi"


async def test_team_pick_409_strips_buttons(env):
    env.backend.routes[("POST", TYPE)] = Conflict("Molyar ishi bajarilgan", status=409)
    await env.cb("pn:ty:3:21", text="x", markup=team_kb())
    assert alert(env) == "Molyar ishi bajarilgan"
    kb = env.session.of(EditMessageReplyMarkup)[-1].reply_markup
    assert cbs(kb) == [] and ("🌐 Saytda ochish", None, URL) in buttons(kb)


async def test_team_pick_403_400_404_alert_only(env):
    for exc, msg in (
        (Forbidden("Ruxsat yo'q", status=403), "Ruxsat yo'q"),
        (ServiceRefusal("Rover tugamagan", status=400), "Rover tugamagan"),
        (NotFound("Molyar yoki jamoa topilmadi", status=404), "Molyar yoki jamoa topilmadi"),
    ):
        env.backend.routes[("POST", TYPE)] = exc
        await env.cb("pn:ty:3:21", text="x", markup=team_kb())
        assert alert(env) == msg
    assert not env.session.of(EditMessageReplyMarkup)
    assert not env.session.of(EditMessageText)


async def test_team_pick_backend_down(env):
    env.backend.routes[("POST", TYPE)] = BackendDown("x")
    await env.cb("pn:ty:3:21", text="x", markup=team_kb())
    assert alert(env) == DOWN_TEXT
