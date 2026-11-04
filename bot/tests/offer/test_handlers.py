"""The buttons under design / price cards and the typed answers (real dispatcher, scripted
backend)."""

import time

from aiogram.methods import EditMessageReplyMarkup, EditMessageText

from bot.backend.client import Conflict, Forbidden, ServiceRefusal
from bot.crm.texts import NEW_BTN

from .conftest import buttons, cbs, price_task, task

URL = "https://ser-mebel.uz/designs/12"
WORK = "🎨 Sizga yangi dizayn\n\n👤 Karim"
PRESENT = "🎨 Dizayn tayyor — mijozga ko'rsating\n\n👤 Karim"
PURL = "https://ser-mebel.uz/presentations?open=d12"
DUE = "offers/design/12/due/"
ANS = "offers/design/12/answer/"


def work_kb():
    return {
        "inline_keyboard": [
            [{"text": "🕒 Muddatni o'zgartirish", "callback_data": "of:dm:d:12"}],
            [{"text": "🌐 Saytda ochish", "url": URL}],
        ]
    }


def present_kb():
    return {
        "inline_keyboard": [
            [{"text": "✅ Tasdiqladi", "callback_data": "of:ok:d:12"}],
            [{"text": "🌐 Saytda ochish", "url": PURL}],
        ]
    }


async def press(env, data, text=WORK, markup=None):
    await env.cb(data, text=text, markup=markup or work_kb())


async def press_present(env, data):
    await env.cb(data, text=PRESENT, markup=present_kb())


def last_kb(env):
    calls = env.session.of(EditMessageReplyMarkup)
    return calls[-1].reply_markup if calls else None


def alert(env):
    a = [x for x in env.session.answers() if x.show_alert]
    return a[-1].text if a else None


async def test_due_menu_keeps_site_link(env):
    await press(env, "of:dm:d:12")
    kb = buttons(last_kb(env))
    assert cbs(last_kb(env)) == [
        "of:dp:1d:d:12",
        "of:dp:2d:d:12",
        "of:dp:3d:d:12",
        "of:dc:d:12",
        "of:bw:d:12",
    ]
    assert ("🌐 Saytda ochish", None, URL) in kb
    assert not env.backend.to(DUE)


async def test_back_restores_assignee_keyboard_without_tayyor(env):
    await press(env, "of:bw:d:12")
    assert cbs(last_kb(env)) == ["of:dm:d:12"]
    assert ("🌐 Saytda ochish", None, URL) in buttons(last_kb(env))


async def test_presets_send_the_codes_and_update_the_card(env):
    sent = []

    def route(json, params):
        sent.append(json)
        return {"task": task(rev=5, due_at="2026-12-27T18:00:00")}

    env.backend.routes[("POST", DUE)] = route
    for code in ("1d", "2d", "3d"):
        await press(env, f"of:dp:{code}:d:12")
    assert sent == [{"preset": "1d"}, {"preset": "2d"}, {"preset": "3d"}]
    e = env.session.of(EditMessageText)[-1]
    assert "Sizga yangi dizayn" in e.text and "27.12" in e.text
    assert cbs(e.reply_markup) == ["of:dm:d:12"]


async def test_price_preset_uses_price_path(env):
    env.backend.routes[("POST", "offers/price/15/due/")] = {"task": price_task()}
    await env.cb("of:dp:1d:p:15", text="🧮 Sizga narx hisoblash\n\n👤 K", markup=work_kb())
    assert env.backend.to("offers/price/15/due/")


async def test_preset_409_alerts_and_keeps_card(env):
    env.backend.routes[("POST", DUE)] = Conflict("Dizayn ishda emas", status=409)
    await press(env, "of:dp:1d:d:12")
    assert alert(env) == "Dizayn ishda emas"
    assert not env.session.edits()


async def test_preset_403_alerts(env):
    env.backend.routes[("POST", DUE)] = Forbidden("Bu dizayn sizga biriktirilmagan", status=403)
    await press(env, "of:dp:1d:d:12")
    assert "biriktirilmagan" in alert(env)


async def test_typed_due_success_edits_stored_message(env):
    env.backend.routes[("POST", DUE)] = {"task": task(rev=5, due_at="2026-12-26T18:00:00")}
    await press(env, "of:dc:d:12")
    assert await env.state() == "OfferDue:custom"
    assert "Yangi muddatni yozing" in env.session.last().text
    assert cbs(env.session.last().reply_markup) == ["of:q"]
    await env.text("26.12 18:00")
    assert env.backend.to(DUE)[0][2] == {"text": "26.12 18:00"}
    assert await env.state() is None
    e = env.session.of(EditMessageText)[-1]
    assert e.chat_id == 555 and e.message_id == 9 and "26.12" in e.text
    assert env.session.last().text == "✅ Saqlandi"


async def test_typed_due_400_reasks_and_keeps_state(env):
    env.backend.routes[("POST", DUE)] = ServiceRefusal(
        "O'tgan vaqt — kelajakdagi vaqtni kiriting", status=400, field="due"
    )
    await press(env, "of:dc:d:12")
    await env.text("01.01 10:00")
    last = env.session.last()
    assert "O'tgan vaqt" in last.text and "Yangi muddatni yozing" in last.text
    assert cbs(last.reply_markup) == ["of:q"]
    assert await env.state() == "OfferDue:custom"


async def test_typed_other_error_clears_state(env):
    env.backend.routes[("POST", DUE)] = Conflict("Dizayn ishda emas", status=409)
    await press(env, "of:dc:d:12")
    await env.text("26.12")
    assert await env.state() is None
    assert env.session.last().text == "Dizayn ishda emas"


async def test_typed_ttl_expired_is_stale(env):
    await env.set_state(
        "OfferDue:custom",
        k="d",
        oid=12,
        chat_id=555,
        message_id=9,
        kind="new",
        ts=time.time() - 3600,
    )
    await env.text("26.12")
    assert env.session.last().text == "Bu tugma eskirgan."
    assert await env.state() is None
    assert not env.backend.to(DUE)


async def test_cancel_command_and_button_clear_state(env):
    await press(env, "of:dc:d:12")
    await env.text("/bekor")
    assert await env.state() is None and env.session.last().text == "Bekor qilindi."
    await press(env, "of:dc:d:12")
    await env.cb("of:q", text="x")
    assert await env.state() is None


async def test_menu_button_clears_state_and_falls_through(env):
    await press(env, "of:dc:d:12")
    await env.text(NEW_BTN)
    assert await env.state() != "OfferDue:custom"
    assert not env.backend.to(DUE)


async def test_busy_when_another_flow_is_open(env):
    for state in ("Lead:name", "TaskDone:custom", "MeterTime:custom", "LocPick:target"):
        await env.set_state(state)
        await press(env, "of:dc:d:12")
        assert alert(env) == "Hozir boshqa amal ochiq. Uni tugating yoki /bekor ni bosing."
        assert await env.state() == state
    await press_present(env, "of:ch:d:12")
    assert await env.state() == "LocPick:target"


async def test_offer_state_blocks_a_location(env):
    # a location during an Offer* state is answered by crm as «another action is open»
    env.backend.who["crm"] = {"can_add_lead": True, "can_set_location": True, "linked": True}
    await env.set_state("OfferDue:custom", k="d", oid=12, ts=time.time())
    await env.feed(message=env._msg(location={"latitude": 41.3, "longitude": 69.2}))
    assert "boshqa amal ochiq" in env.session.last().text
    assert await env.state() == "OfferDue:custom"
    assert not env.backend.to("crm/locations/candidates/")


async def test_meter_ask_refused_during_offer_state(env):
    await env.set_state("OfferDue:custom", k="d", oid=12, ts=time.time())
    await env.cb("mt:rc:7", text="📏 Sizga yangi zamer")
    assert alert(env) and await env.state() == "OfferDue:custom"


# ---- manager


async def test_ok_asks_to_confirm_then_back_restores(env):
    await press_present(env, "of:ok:d:12")
    kb = last_kb(env)
    assert ("✅ Ha, mijoz tasdiqladi", "of:oky:d:12", None) in buttons(kb)
    assert ("↩️ Orqaga", "of:bk:d:12", None) in buttons(kb)
    assert ("🌐 Saytda ochish", None, PURL) in buttons(kb)
    assert not env.backend.to(ANS)
    await press_present(env, "of:bk:d:12")
    assert cbs(last_kb(env)) == ["of:ok:d:12", "of:ch:d:12", "of:no:d:12"]


async def test_confirmed_posts_approved_and_finalizes(env):
    env.backend.routes[("POST", ANS)] = {"task": task(rev=8, stage="approved"), "closed_tasks": 0}
    await press_present(env, "of:oky:d:12")
    assert env.backend.to(ANS)[0][2] == {"answer": "approved"}
    e = env.session.of(EditMessageText)[-1]
    assert "✅ Mijoz tasdiqladi" in e.text and e.reply_markup is None


async def test_price_confirmed_says_rozi(env):
    env.backend.routes[("POST", "offers/price/15/answer/")] = {
        "task": price_task(stage="approved"),
        "closed_tasks": 0,
    }
    await env.cb("of:oky:p:15", text="🧮 Narx tayyor — mijozga ko'rsating\n\n👤 K")
    assert "✅ Mijoz rozi" in env.session.of(EditMessageText)[-1].text


async def test_confirmed_409_and_403_alerts(env):
    env.backend.routes[("POST", ANS)] = Conflict("Javob allaqachon yozilgan", status=409)
    await press_present(env, "of:oky:d:12")
    assert alert(env) == "Javob allaqachon yozilgan"
    env.backend.routes[("POST", ANS)] = Forbidden("Bu mijoz sizga biriktirilmagan", status=403)
    await press_present(env, "of:oky:d:12")
    assert alert(env) == "Bu mijoz sizga biriktirilmagan"
    assert not env.session.edits()


async def test_changes_comment_flow_design(env):
    env.backend.routes[("POST", ANS)] = {"task": task(rev=9, round=2), "closed_tasks": 0}
    await press_present(env, "of:ch:d:12")
    assert await env.state() == "OfferAnswer:comment"
    assert "Nima o'zgarishi kerak" in env.session.last().text
    await env.text("Rangni o'zgartiring")
    assert env.backend.to(ANS)[0][2] == {"answer": "changes", "comment": "Rangni o'zgartiring"}
    assert await env.state() is None
    assert "✏️ Qayta ishlashga qaytdi" in env.session.of(EditMessageText)[-1].text


async def test_recalc_comment_flow_price_sends_recalc(env):
    env.backend.routes[("POST", "offers/price/15/answer/")] = {
        "task": price_task(),
        "closed_tasks": 0,
    }
    await env.cb(
        "of:ch:p:15", text="🧮 Narx tayyor — mijozga ko'rsating\n\n👤 K", markup=present_kb()
    )
    await env.text("Arzonroq")
    assert env.backend.to("offers/price/15/answer/")[0][2] == {
        "answer": "recalc",
        "comment": "Arzonroq",
    }


async def test_reason_flow_declined_and_reask_on_comment_error(env):
    env.backend.routes[("POST", ANS)] = ServiceRefusal(
        "Sababini yozing", status=400, field="comment"
    )
    await press_present(env, "of:no:d:12")
    assert await env.state() == "OfferAnswer:reason"
    await env.text("x")
    assert "Sababini yozing" in env.session.last().text
    assert await env.state() == "OfferAnswer:reason"
    env.backend.routes[("POST", ANS)] = {
        "task": task(stage="declined", last_comment="Qimmat"),
        "closed_tasks": 2,
    }
    await env.text("Qimmat")
    assert env.backend.to(ANS)[-1][2] == {"answer": "declined", "comment": "Qimmat"}
    assert await env.state() is None
    assert "❌ Rad etildi: Qimmat" in env.session.of(EditMessageText)[-1].text
