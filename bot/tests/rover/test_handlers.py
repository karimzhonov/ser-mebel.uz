"""The rover buttons (real dispatcher, scripted backend)."""

from aiogram.methods import EditMessageReplyMarkup, EditMessageText

from bot.backend.client import BackendDown, Conflict, Forbidden, NotFound, ServiceRefusal
from bot.rover.api import DOWN_TEXT

from .conftest import URL, buttons, cbs, done_task

CARD = "🛠 Rover ishini tekshiring\n\nBuyurtma №406"
PATH = ("POST", "rovers/12/confirm/")


def open_kb():
    return {
        "inline_keyboard": [
            [{"text": "✅ Bajarildi", "callback_data": "rv:ok:12"}],
            [{"text": "🌐 Saytda ochish", "url": URL}],
        ]
    }


async def press(env, data):
    await env.cb(data, text=CARD, markup=open_kb())


def last_kb(env):
    calls = env.session.of(EditMessageReplyMarkup)
    return calls[-1].reply_markup if calls else None


async def test_ok_swaps_to_confirm_and_keeps_url(env):
    await press(env, "rv:ok:12")
    kb = buttons(last_kb(env))
    assert ("✅ Ha, tasdiqlayman", "rv:oky:12", None) in kb
    assert ("↩️ Orqaga", "rv:bk:12", None) in kb
    assert ("🌐 Saytda ochish", None, URL) in kb
    assert not env.backend.to("rovers/12/confirm/")


async def test_back_restores_card_keyboard(env):
    await press(env, "rv:bk:12")
    assert cbs(last_kb(env)) == ["rv:ok:12"]
    assert ("🌐 Saytda ochish", None, URL) in buttons(last_kb(env))


async def test_confirm_posts_and_edits_to_done(env):
    env.backend.routes[PATH] = {"rover": done_task()}
    await press(env, "rv:oky:12")
    call = env.backend.to("rovers/12/confirm/")[0]
    method, body = call[0], call[2]
    assert (method, body) == ("POST", {})
    e = env.session.of(EditMessageText)[-1]
    assert "✅ Tasdiqlandi — Tekshiruvchi" in e.text
    assert buttons(e.reply_markup) == [("🌐 Saytda ochish", None, URL)]
    a = env.session.answers()[-1]
    assert a.text == "✅ Tasdiqlandi" and not a.show_alert


async def test_conflict_alerts_and_strips_buttons(env):
    env.backend.routes[PATH] = Conflict("Allaqachon tasdiqlangan", status=409)
    await press(env, "rv:oky:12")
    a = env.session.answers()[-1]
    assert a.show_alert and a.text == "Allaqachon tasdiqlangan"
    assert cbs(last_kb(env)) == []
    assert not env.session.of(EditMessageText)


async def test_forbidden_alerts(env):
    env.backend.routes[PATH] = Forbidden("Ruxsat yo'q", status=403)
    await press(env, "rv:oky:12")
    a = env.session.answers()[-1]
    assert a.show_alert and a.text == "Ruxsat yo'q"
    assert not env.session.of(EditMessageText)
    assert cbs(last_kb(env)) == ["rv:ok:12"]


async def test_not_submitted_400_restores_card_keyboard(env):
    env.backend.routes[PATH] = ServiceRefusal("Rover hali topshirilmagan", status=400)
    await press(env, "rv:oky:12")
    a = env.session.answers()[-1]
    assert a.show_alert and a.text == "Rover hali topshirilmagan"
    assert cbs(last_kb(env)) == ["rv:ok:12"]
    assert ("🌐 Saytda ochish", None, URL) in buttons(last_kb(env))


async def test_not_found_404_strips_buttons_keeps_link(env):
    env.backend.routes[PATH] = NotFound("Topilmadi", status=404)
    await press(env, "rv:oky:12")
    a = env.session.answers()[-1]
    assert a.show_alert
    assert buttons(last_kb(env)) == [("🌐 Saytda ochish", None, URL)]


async def test_backend_down(env):
    env.backend.routes[PATH] = BackendDown("down")
    await press(env, "rv:oky:12")
    a = env.session.answers()[-1]
    assert a.show_alert and a.text == DOWN_TEXT
    assert cbs(last_kb(env)) == ["rv:ok:12"]
