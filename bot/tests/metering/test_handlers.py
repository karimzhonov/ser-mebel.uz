"""The buttons under a zamer card and the typed answers (real dispatcher, scripted backend)."""

import time

from aiogram.methods import EditMessageReplyMarkup, EditMessageText, SendMessage

from bot.backend.client import Conflict, Forbidden, ServiceRefusal
from bot.crm.texts import NEW_BTN

from .conftest import MAP, brief, buttons, cbs

URL = "https://ser-mebel.uz/meterings/7"
CARD = "📏 Sizga yangi zamer\n\n👤 Karim"


def open_kb():
    """The keyboard of an open card, as Telegram returns it on the pressed message."""
    return {
        "inline_keyboard": [
            [{"text": "✅ O'lchov oldim", "callback_data": "mt:ms:7"}],
            [
                {"text": "📍 Xarita", "url": MAP},
                {"text": "🌐 Saytda ochish", "url": URL},
            ],
        ]
    }


async def press(env, data, text=CARD):
    await env.cb(data, text=text, markup=open_kb())


def last_kb(env):
    calls = env.session.of(EditMessageReplyMarkup)
    return calls[-1].reply_markup if calls else None


async def test_measured_asks_to_confirm_and_keeps_links(env):
    await press(env, "mt:ms:7")
    kb = buttons(last_kb(env))
    assert ("✅ Ha, o'lchov oldim", "mt:msy:7", None) in kb
    assert ("↩️ Orqaga", "mt:bk:7", None) in kb
    assert ("📍 Xarita", None, MAP) in kb and ("🌐 Saytda ochish", None, URL) in kb
    assert not env.backend.to("meterings/7/measured/")  # nothing written yet


async def test_back_restores_the_card_keyboard_with_links(env):
    await press(env, "mt:bk:7")
    kb = buttons(last_kb(env))
    assert cbs(last_kb(env)) == ["mt:ms:7", "mt:rs:7", "mt:cn:7"]
    assert ("📍 Xarita", None, MAP) in kb


async def test_confirmed_measured_posts_and_rerenders_from_response(env):
    env.backend.routes[("POST", "meterings/7/measured/")] = {
        "metering": brief(status="metering_done", rev=4),
        "url": URL,
    }
    await press(env, "mt:msy:7")
    assert env.backend.to("meterings/7/measured/")[0][0] == "POST"
    e = env.session.of(EditMessageText)[-1]
    assert "Fayllarni saytga yuklang" in e.text and "Zamer</b>" in e.text
    assert buttons(e.reply_markup) == [("📤 Saytda yuklash", None, URL)]


async def test_measured_conflict_and_forbidden_are_alerts(env):
    for exc in (
        Conflict("Allaqachon belgilangan", status=409),
        Forbidden("Bu zamer sizga biriktirilmagan", status=403),
    ):
        env.backend.routes[("POST", "meterings/7/measured/")] = exc
        await press(env, "mt:msy:7")
        a = env.session.answers()[-1]
        assert a.show_alert and a.text == exc.detail
    assert not env.session.of(EditMessageText)


async def test_reschedule_menu_has_presets_and_typed(env):
    await press(env, "mt:rs:7")
    assert cbs(last_kb(env)) == [
        "mt:rp:1h:7",
        "mt:rp:tm:7",
        "mt:rp:2d:7",
        "mt:rc:7",
        "mt:bk:7",
    ]


async def test_presets_send_the_backend_names_and_update_the_card(env):
    sent = []

    def route(json, params):
        sent.append(json)
        return {"metering": brief(status="other_day", rev=5, date_time="2026-12-26T09:00:00")}

    env.backend.routes[("POST", "meterings/7/reschedule/")] = route
    for code in ("1h", "tm", "2d"):
        await press(env, f"mt:rp:{code}:7")
    assert sent == [{"preset": "1h"}, {"preset": "tomorrow"}, {"preset": "2d"}]
    e = env.session.of(EditMessageText)[-1]
    assert "Zamer vaqti o'zgardi" in e.text and "26.12" in e.text
    assert "mt:ms:7" in cbs(e.reply_markup)


async def test_typed_time_flow_success_edits_stored_message(env):
    env.backend.routes[("POST", "meterings/7/reschedule/")] = {
        "metering": brief(status="other_day", rev=5, date_time="2026-12-26T14:30:00")
    }
    await press(env, "mt:rc:7")
    assert await env.state() == "MeterTime:custom"
    assert "Yangi vaqtni yozing" in env.session.last().text
    assert cbs(env.session.last().reply_markup) == ["mt:q"]
    await env.text("26.12 14:30")
    assert env.backend.to("meterings/7/reschedule/")[0][2] == {"text": "26.12 14:30"}
    assert await env.state() is None
    e = env.session.of(EditMessageText)[-1]
    assert e.chat_id == 555 and e.message_id == 9 and "26.12" in e.text
    assert env.session.last().text == "✅ Saqlandi"


async def test_typed_time_400_reasks_and_keeps_state(env):
    env.backend.routes[("POST", "meterings/7/reschedule/")] = ServiceRefusal(
        "O'tgan vaqt — kelajakdagi vaqtni kiriting", status=400, field="time"
    )
    await press(env, "mt:rc:7")
    await env.text("01.01 10:00")
    last = env.session.last()
    assert "O'tgan vaqt" in last.text and "Yangi vaqtni yozing" in last.text
    assert cbs(last.reply_markup) == ["mt:q"]
    assert await env.state() == "MeterTime:custom"


async def test_typed_answer_ttl_expired_is_stale(env):
    await env.set_state(
        "MeterTime:custom",
        metering=7,
        chat_id=555,
        message_id=9,
        kind="soon",
        ts=time.time() - 3600,
    )
    await env.text("14:30")
    assert env.session.last().text == "Bu tugma eskirgan."
    assert not env.backend.to("meterings/7/reschedule/") and await env.state() is None


async def test_cancel_command_and_cancel_button_clear_the_state(env):
    await press(env, "mt:rc:7")
    await env.text("/bekor")
    assert await env.state() is None and env.session.last().text == "Bekor qilindi."
    await press(env, "mt:cn:7")
    assert await env.state() == "MeterCancel:reason"
    await press(env, "mt:q")
    assert await env.state() is None and last_kb(env) is None


async def test_menu_button_clears_and_falls_through_to_crm(env):
    await press(env, "mt:cn:7")
    assert await env.state() == "MeterCancel:reason"
    await env.text(NEW_BTN)
    assert not env.backend.to("meterings/7/cancel/")
    assert await env.state() == "Lead:name"  # SkipHandler -> the crm lead form took it
    assert "Yangi mijoz" in env.session.last().text


async def test_cancel_flow_posts_reason_and_final_card_has_no_keyboard(env):
    env.backend.routes[("POST", "meterings/7/cancel/")] = {
        "metering": brief(status="dont_need", rev=6, cancel_reason="Mijoz rad etdi"),
        "lead_returned": True,
    }
    await press(env, "mt:cn:7")
    assert "Sababini yozing" in env.session.last().text
    await env.text("Mijoz rad etdi")
    assert env.backend.to("meterings/7/cancel/")[0][2] == {"reason": "Mijoz rad etdi"}
    e = env.session.of(EditMessageText)[-1]
    assert "❌ Bekor bo'ldi: Mijoz rad etdi" in e.text and e.reply_markup is None
    assert await env.state() is None and env.session.last().text == "✅ Saqlandi"


async def test_cancel_reason_400_reasks(env):
    env.backend.routes[("POST", "meterings/7/cancel/")] = ServiceRefusal(
        "Sababini yozing", status=400, field="reason"
    )
    await press(env, "mt:cn:7")
    await env.text("ha")
    assert "Sababini yozing" in env.session.last().text
    assert await env.state() == "MeterCancel:reason"


async def test_cancel_conflict_clears_state_and_shows_text(env):
    env.backend.routes[("POST", "meterings/7/cancel/")] = Conflict(
        "Allaqachon bekor qilingan", status=409
    )
    await press(env, "mt:cn:7")
    await env.text("sabab bor")
    assert env.session.last().text == "Allaqachon bekor qilingan"
    assert await env.state() is None


async def test_busy_with_other_flow_refuses_typed_prompts(env):
    for state in ("Lead:name", "TaskDone:custom", "LocPick:target"):
        await env.set_state(state, ts=time.time())
        for data in ("mt:rc:7", "mt:cn:7"):
            before = len(env.session.sent())
            await press(env, data)
            a = env.session.answers()[-1]
            assert a.show_alert and "boshqa amal ochiq" in a.text
            assert await env.state() == state and len(env.session.sent()) == before


async def test_location_during_cancel_reason_is_refused_as_busy(env):
    env.backend.who["crm"] = {"linked": True, "can_add_lead": True, "can_set_location": True}
    await press(env, "mt:cn:7")
    await env.feed(message=env._msg(location={"latitude": 41.3, "longitude": 69.2}))
    assert "boshqa amal ochiq" in env.session.last().text
    assert not env.backend.to("crm/locations/candidates/")
    assert await env.state() == "MeterCancel:reason"  # state untouched, reason still expected


async def test_crm_callbacks_unaffected_by_the_zamer_router(env):
    env.backend.routes[("GET", "crm/tasks/8/")] = {"outcomes": ["keep"], "url": ""}
    env.backend.routes[("POST", "crm/tasks/8/done/")] = {"invoice": {}, "closed_tasks": 0}
    await env.cb("crm:done:8")
    assert env.backend.to("crm/tasks/8/done/")


async def test_foreign_text_without_meter_state_is_not_taken(env):
    await env.text("14:30")
    assert not [c for c in env.backend.calls if "meterings" in c[1]]
    assert isinstance(env.session.calls, list) and not env.session.of(SendMessage)
