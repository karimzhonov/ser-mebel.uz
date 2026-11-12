"""Painter buttons: «Bajardim» FSM and head presets (real dispatcher, scripted backend)."""

import time

from aiogram.methods import EditMessageReplyMarkup, EditMessageText

from bot.assembly.api import DOWN_TEXT
from bot.backend.client import BackendDown, Conflict, Forbidden, NotFound, ServiceRefusal
from bot.crm.texts import NEW_BTN

from .conftest import URL, buttons, cbs, checking_task, done_task, task

DONE = "assemblies/21/finish/"
DUE = "assemblies/21/due/"
TYPE = "assemblies/21/assembler/"
NOTE = "Eshiklar bo'yaldi, 4 ta"
TCARD = "🔧 Yangi Yig'ish/O'rnatish ishi\n\nBuyurtma №406"


def card_kb():
    return {
        "inline_keyboard": [
            [{"text": "✅ O'rnatildi", "callback_data": "as:fn:21"}],
            [{"text": "🌐 Saytda ochish", "url": URL}],
        ]
    }


async def start(env):
    await env.cb("as:fn:21", text=TCARD, markup=card_kb())


async def to_confirm(env, note=NOTE):
    await start(env)
    await env.text(note)


def alert(env):
    a = env.session.answers()[-1]
    return a.text if a.show_alert else None


async def test_full_path_posts_note_and_edits_card(env):
    env.backend.routes[("POST", DONE)] = {"assembly": checking_task()}
    await start(env)
    assert await env.state() == "AssemblyFinish:note"
    assert "nima ish qilindi" in env.session.last().text
    await env.text(NOTE)
    assert await env.state() == "AssemblyFinish:confirm"
    last = env.session.last()
    assert NOTE in last.text
    assert cbs(last.reply_markup) == ["as:sy:21", "as:se:21", "as:q"]
    await env.cb("as:sy:21", text="Tekshiring")
    assert env.backend.to(DONE)[0][2] == {"note": NOTE}
    e = env.session.of(EditMessageText)
    card = [x for x in e if "Yangi Yig'ish/O'rnatish ishi" in x.text][-1]
    assert card.message_id == 9 and "✅ O'rnatildi — Yig'uvchi usta" in card.text
    assert "⏳ Tekshiruvda" in card.text
    assert buttons(card.reply_markup) == [("🌐 Saytda ochish", None, URL)]
    assert any(x.text == "✅ O'rnatildi" for x in e)
    assert await env.state() is None
    assert env.session.answers()[-1].text == "✅ O'rnatildi"


async def test_short_and_long_note_reask(env):
    await start(env)
    await env.text("ok")
    assert "juda qisqa" in env.session.last().text
    assert await env.state() == "AssemblyFinish:note"
    await env.text("x" * 2001)
    assert "juda uzun" in env.session.last().text
    assert await env.state() == "AssemblyFinish:note"
    await env.text("yetarli izoh")
    assert await env.state() == "AssemblyFinish:confirm"


async def test_restart_goes_back_to_note(env):
    await to_confirm(env)
    await env.cb("as:se:21", text="Tekshiring")
    assert await env.state() == "AssemblyFinish:note"
    assert "nima ish qilindi" in env.session.last().text


async def test_400_field_note_reasks(env):
    env.backend.routes[("POST", DONE)] = ServiceRefusal("Izoh juda qisqa", status=400, field="note")
    await to_confirm(env)
    await env.cb("as:sy:21", text="Tekshiring")
    assert await env.state() == "AssemblyFinish:note"
    assert "Izoh juda qisqa" in env.session.last().text


async def test_400_other_clears_and_alerts(env):
    env.backend.routes[("POST", DONE)] = ServiceRefusal("Detallashtirish tugamagan", status=400)
    await to_confirm(env)
    await env.cb("as:sy:21", text="Tekshiring")
    assert alert(env) == "Detallashtirish tugamagan" and await env.state() is None


async def test_409_and_404_clear_alert_and_link_only(env):
    for exc in (Conflict("Allaqachon bajarilgan", status=409), NotFound("Topilmadi", status=404)):
        env.backend.routes[("POST", DONE)] = exc
        await to_confirm(env)
        await env.cb("as:sy:21", text="Tekshiring")
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
    await env.cb("as:sy:21", text="Tekshiring")
    assert alert(env) == "Ruxsat yo'q" and await env.state() is None
    kb = [c for c in env.session.of(EditMessageReplyMarkup) if c.message_id == 9]
    assert kb and not buttons(kb[-1].reply_markup)


async def test_backend_down_clears(env):
    env.backend.routes[("POST", DONE)] = BackendDown("down")
    await to_confirm(env)
    await env.cb("as:sy:21", text="Tekshiring")
    assert alert(env) == DOWN_TEXT and await env.state() is None


async def test_ttl_expired_is_stale(env):
    await env.set_state(
        "AssemblyFinish:note", pid=21, chat_id=555, message_id=9, ts=time.time() - 4000
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
    await env.cb("as:q", text="x")
    assert await env.state() is None
    await start(env)
    await env.text("/bekor")
    assert await env.state() is None and env.session.last().text == "Bekor qilindi."


async def test_menu_button_clears_and_skips(env):
    await start(env)
    await env.text(NEW_BTN)
    assert await env.state() != "AssemblyFinish:note"
    assert not env.backend.to(DONE)


async def test_submit_without_state_is_stale(env):
    await env.cb("as:sy:21", text="Tekshiring")
    assert alert(env) == "Bu tugma eskirgan."
    assert not env.backend.to(DONE)


# ---- head presets


def head_kb():
    return {
        "inline_keyboard": [
            [{"text": "+10 kun", "callback_data": "as:dd:10:21"}],
            [{"text": "🌐 Saytda ochish", "url": URL}],
        ]
    }


async def test_due_preset_posts_days_and_edits(env):
    env.backend.routes[("POST", DUE)] = {"assembly": task(due_date="2026-11-25", rev=4)}
    await env.cb("as:dd:10:21", text="🗓 Yig'ish uchun muddat qo'ying", markup=head_kb())
    assert env.backend.to(DUE)[0][2] == {"days": 10}
    e = env.session.of(EditMessageText)[-1]
    assert "Yig'ish uchun muddat qo'ying" in e.text and "25.11.2026" in e.text
    assert cbs(e.reply_markup) == ["as:dd:5:21", "as:dd:10:21", "as:dd:14:21"]


async def test_due_preset_409_strips_presets(env):
    env.backend.routes[("POST", DUE)] = Conflict("Yig'ish ishi bajarilgan", status=409)
    await env.cb("as:dd:10:21", text="x", markup=head_kb())
    assert alert(env) == "Yig'ish ishi bajarilgan"
    kb = env.session.of(EditMessageReplyMarkup)[-1].reply_markup
    assert cbs(kb) == [] and ("🌐 Saytda ochish", None, URL) in buttons(kb)


async def test_due_preset_403_alerts_only(env):
    env.backend.routes[("POST", DUE)] = Forbidden("Ruxsat yo'q", status=403)
    await env.cb("as:dd:14:21", text="x", markup=head_kb())
    assert alert(env) == "Ruxsat yo'q"
    assert not env.session.of(EditMessageReplyMarkup)


def team_kb():
    return {
        "inline_keyboard": [
            [{"text": "Yig'uvchi usta", "callback_data": "as:us:5:21"}],
            [{"text": "🌐 Saytda ochish", "url": URL}],
        ]
    }


async def test_team_pick_posts_user_and_edits_all_cards(env):
    from bot.assembly import messages

    await messages.remember("r21", 999, 55, "team")  # another head's card
    env.backend.routes[("POST", TYPE)] = {"assembly": task(rev=4)}
    await env.cb("as:us:5:21", text="🔧 Yig'ishga tushdi", markup=team_kb())
    assert env.backend.to(TYPE)[0][2] == {"user_id": 5}
    edits = env.session.of(EditMessageText)
    assert all("✅ Jamoa: Yig'uvchi usta" in e.text for e in edits)
    assert len(edits) == 2
    assert all(cbs(e.reply_markup) == [] for e in edits)
    assert env.session.answers()[-1].text == "✅ Tanlandi"


async def test_team_pick_409_strips_buttons(env):
    env.backend.routes[("POST", TYPE)] = Conflict("Yig'ish ishi bajarilgan", status=409)
    await env.cb("as:us:5:21", text="x", markup=team_kb())
    assert alert(env) == "Yig'ish ishi bajarilgan"
    kb = env.session.of(EditMessageReplyMarkup)[-1].reply_markup
    assert cbs(kb) == [] and ("🌐 Saytda ochish", None, URL) in buttons(kb)


async def test_team_pick_403_400_404_alert_only(env):
    for exc, msg in (
        (Forbidden("Ruxsat yo'q", status=403), "Ruxsat yo'q"),
        (ServiceRefusal("Detallashtirish tugamagan", status=400), "Detallashtirish tugamagan"),
        (
            NotFound("Yig'ish yoki yig'uvchi topilmadi", status=404),
            "Yig'ish yoki yig'uvchi topilmadi",
        ),
    ):
        env.backend.routes[("POST", TYPE)] = exc
        await env.cb("as:us:5:21", text="x", markup=team_kb())
        assert alert(env) == msg
    assert not env.session.of(EditMessageReplyMarkup)
    assert not env.session.of(EditMessageText)


async def test_team_pick_backend_down(env):
    env.backend.routes[("POST", TYPE)] = BackendDown("x")
    await env.cb("as:us:5:21", text="x", markup=team_kb())
    assert alert(env) == DOWN_TEXT


async def test_team_pick_409_different_assembler_started(env):
    env.backend.routes[("POST", TYPE)] = Conflict(
        "Jamoa allaqachon tanlangan: Boshqa — o'zgartirish saytda", status=409
    )
    await env.cb("as:us:5:21", text="x", markup=team_kb())
    assert "Jamoa allaqachon tanlangan" in alert(env)
    kb = env.session.of(EditMessageReplyMarkup)[-1].reply_markup
    assert cbs(kb) == []


CONFIRM = "assemblies/21/confirm/"
HEAD_TXT = "🔧 O'rnatib bo'lishdi — №406"


def ok_kb():
    return {
        "inline_keyboard": [
            [{"text": "✅ Tayyor", "callback_data": "as:ok:21"}],
            [{"text": "🌐 Saytda ochish", "url": URL}],
        ]
    }


def last_kb(env):
    return cbs(env.session.of(EditMessageReplyMarkup)[-1].reply_markup)


async def test_confirm_asks_then_back(env):
    await env.cb("as:ok:21", text=HEAD_TXT, markup=ok_kb())
    assert last_kb(env) == ["as:oky:21", "as:bk:21"]
    assert "Готов bo'ladi" in env.session.answers()[-1].text
    await env.cb("as:bk:21", text=HEAD_TXT, markup=ok_kb())
    assert last_kb(env) == ["as:ok:21"]
    assert env.backend.to(CONFIRM) == []


async def test_confirm_posts_and_edits_card(env):
    env.backend.routes[("POST", CONFIRM)] = {
        "assembly": done_task(confirmed_by={"id": 14, "name": "Rahbar"})
    }
    await env.cb("as:oky:21", text=HEAD_TXT, markup=ok_kb())
    assert env.backend.to(CONFIRM)[0][2] == {}
    card = env.session.of(EditMessageText)[-1]
    assert "Rahbar tasdiqladi" in card.text
    assert buttons(card.reply_markup) == [("🌐 Saytda ochish", None, URL)]
    assert env.session.answers()[-1].text == "✅ Tayyor"


async def test_confirm_409_strips_buttons(env):
    env.backend.routes[("POST", CONFIRM)] = Conflict("Allaqachon tayyor", status=409)
    await env.cb("as:oky:21", text=HEAD_TXT, markup=ok_kb())
    assert last_kb(env) == []
    assert alert(env) == "Allaqachon tayyor"


async def test_confirm_400_403_404_restore_button(env):
    for exc in (
        ServiceRefusal("Yig'uvchi hali bosmagan", status=400),
        Forbidden("Ruxsat yo'q", status=403),
        NotFound("yo'q", status=404),
    ):
        env.backend.routes[("POST", CONFIRM)] = exc
        await env.cb("as:oky:21", text=HEAD_TXT, markup=ok_kb())
        assert last_kb(env) == ["as:ok:21"]
        assert alert(env)


async def test_confirm_backend_down_restores_button(env):
    env.backend.routes[("POST", CONFIRM)] = BackendDown("down")
    await env.cb("as:oky:21", text=HEAD_TXT, markup=ok_kb())
    assert last_kb(env) == ["as:ok:21"]
    assert alert(env) == DOWN_TEXT
