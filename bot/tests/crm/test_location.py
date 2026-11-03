"""Telegram location -> lead / metering: routing, FSM, POST body, and what must NOT happen."""

from aiogram.methods import AnswerCallbackQuery

from bot.backend.client import Forbidden, ServiceRefusal

from .conftest import UID, buttons, cbs

LAT, LON = 41.311081, 69.279737
ITEMS = [
    {
        "kind": "invoice",
        "id": 41,
        "client": {"fio": "Karim", "phone": "+998901234567"},
        "status": None,
        "status_label": None,
        "when": None,
        "address": "",
        "has_point": False,
        "mine": True,
    },
    {
        "kind": "metering",
        "id": 7,
        "client": {"fio": "Dilnoza", "phone": "+998907654321"},
        "status": "created",
        "status_label": "Yangi",
        "when": "2026-11-05T10:30:00",
        "address": "Chilonzor 5",
        "has_point": True,
        "mine": False,
    },
]
CANDS = {"items": ITEMS, "can_new_lead": True}
SAVED = {
    "target": ITEMS[0],
    "changed": True,
    "filled": [{"kind": "metering", "id": 7}, {"kind": "order", "id": 3}],
    "map_url": "https://yandex.uz/maps/?ll=69.279737,41.311081&pt=69.279737,41.311081&z=17&l=map",
    "url": "https://ser-mebel.uz/call-center?open=41",
}


def allow(env, **crm):
    env.backend.who["crm"] = {"can_add_lead": True, "can_set_location": True, **crm}


def script(env, cands=CANDS, saved=SAVED):
    env.backend.routes[("GET", "crm/locations/candidates/")] = cands
    env.backend.routes[("POST", "crm/locations/")] = saved


async def send_loc(env, uid=UID, chat_type="private", forward=False, venue=None, live=None, **kw):
    extra = {"location": {"latitude": LAT, "longitude": LON}}
    if live:
        extra["location"]["live_period"] = live
    if venue:
        extra["venue"] = {
            "location": extra["location"],
            "title": "Uy",
            "address": venue,
        }
    if forward:
        extra["forward_origin"] = {
            "type": "user",
            "date": 1699990000,
            "sender_user": {"id": 99, "is_bot": False, "first_name": "Karim"},
        }
    msg = env._msg(uid, **extra)
    msg["chat"]["type"] = chat_type
    if chat_type != "private":
        msg["chat"]["id"] = -1001
        msg["chat"]["title"] = "G"
    return await env.feed(message=msg)


async def test_plain_location_asks_which_client(env):
    allow(env)
    script(env)
    await send_loc(env)
    assert await env.state() == "LocPick:target"
    assert env.backend.to("crm/locations/candidates/")[0][3] is None
    last = env.session.last()
    assert "Qaysi mijoz" in last.text
    assert cbs(last.reply_markup) == ["crm:loc:i:41", "crm:loc:m:7", "crm:loc:new", "crm:loc:x"]
    texts = [t for t, *_ in buttons(last.reply_markup)]
    assert texts[0] == "📋 #41 Karim"
    assert texts[1] == "📐 05.11 10:30 Dilnoza ✅"


async def test_forwarded_location_is_handled_the_same_not_as_a_lead(env):
    allow(env)
    script(env)
    await send_loc(env, forward=True)
    assert await env.state() == "LocPick:target"  # not Lead:name (the forward lead entry)


async def test_empty_candidates_use_the_empty_text(env):
    allow(env)
    script(env, cands={"items": [], "can_new_lead": False})
    await send_loc(env)
    assert "topilmadi" in env.session.last().text
    assert cbs(env.session.last().reply_markup) == ["crm:loc:x"]


async def test_live_location_is_announced(env):
    allow(env)
    script(env)
    await send_loc(env, live=900)
    assert "Jonli lokatsiya" in env.session.last().text
    await env.cb("crm:loc:i:41")
    body = env.backend.to("crm/locations/")[0][2]
    assert body["live"] is True


async def test_phone_text_filters_candidates(env):
    allow(env)
    script(env)
    await send_loc(env)
    await env.text("90 123 45 67")
    call = env.backend.to("crm/locations/candidates/")[1]
    assert call[3] == {"phone": "90 123 45 67"}
    assert await env.state() == "LocPick:target"
    assert cbs(env.session.last().reply_markup)[0] == "crm:loc:i:41"


async def test_bad_phone_reasks(env):
    allow(env)
    script(env)
    await send_loc(env)
    env.backend.routes[("GET", "crm/locations/candidates/")] = ServiceRefusal(
        "Telefon noto'g'ri", field="phone"
    )
    await env.text("123-45-67")
    assert "Telefon noto'g'ri" in env.session.last().text
    assert await env.state() == "LocPick:target"


async def test_phone_without_matches_offers_new_lead_seeded(env):
    allow(env)
    script(env)
    await send_loc(env)
    env.backend.routes[("GET", "crm/locations/candidates/")] = {"items": [], "can_new_lead": True}
    await env.text("+998901112233")
    last = env.session.last()
    assert "Bu raqam bo'yicha" in last.text
    assert cbs(last.reply_markup) == ["crm:loc:new", "crm:loc:x"]
    await env.cb("crm:loc:new")
    assert await env.state() == "Lead:name"
    # the location and the typed phone ride into the lead form
    await env.text("Yangi Mijoz")
    assert await env.state() == "Lead:phone"
    assert "crm:phone:use" in cbs(env.session.last().reply_markup)


async def test_pick_posts_body_and_confirms(env):
    allow(env)
    script(env)
    await send_loc(env, venue="Chilonzor 5")
    await env.cb("crm:loc:i:41")
    post = env.backend.to("crm/locations/")[0]
    assert post[0] == "POST"
    assert post[2] == {
        "target": {"kind": "invoice", "id": 41},
        "lat": LAT,
        "lon": LON,
        "address": "Chilonzor 5",
    }
    assert await env.state() is None
    last = env.session.last()
    assert "Lokatsiya saqlandi" in last.text and "ariza #41" in last.text
    assert "o'lchovga va buyurtmaga ham qo'shildi" in last.text
    assert buttons(last.reply_markup) == [
        ("🗺 Yandex xaritada", None, SAVED["map_url"]),
        ("💻 Panelda ochish", None, SAVED["url"]),
    ]


async def test_pick_metering_kind(env):
    allow(env)
    script(env)
    await send_loc(env)
    await env.cb("crm:loc:m:7")
    assert env.backend.to("crm/locations/")[0][2]["target"] == {"kind": "metering", "id": 7}


async def test_backend_refusal_is_an_alert_and_state_stays(env):
    allow(env)
    script(env)
    await send_loc(env)
    env.backend.routes[("POST", "crm/locations/")] = Forbidden("Ruxsat yo'q")
    await env.cb("crm:loc:m:7")
    alert = [a for a in env.session.answers() if isinstance(a, AnswerCallbackQuery)][-1]
    assert alert.show_alert and "Ruxsat yo'q" in alert.text
    assert await env.state() == "LocPick:target"


async def test_stale_button_without_state(env):
    allow(env)
    script(env)
    await env.cb("crm:loc:i:41")
    assert env.session.answers()[-1].text == "Bu tugma eskirgan."
    assert not env.backend.to("crm/locations/")


async def test_cancel_clears(env):
    allow(env)
    script(env)
    await send_loc(env)
    await env.cb("crm:loc:x")
    assert await env.state() is None
    assert env.session.last().text == "Bekor qilindi."


async def test_no_permission_location_is_ignored(env):
    env.backend.who["crm"] = {"can_add_lead": True, "can_set_location": False}
    await send_loc(env)
    assert await env.state() is None
    assert not env.backend.to("crm/locations/candidates/")


async def test_location_during_lead_note_is_carried_into_save(env):
    allow(env)
    script(env)
    env.backend.routes[("GET", "crm/clients/")] = {"exists": False}
    env.backend.routes[("POST", "crm/leads/")] = {"invoice": {"id": 5}, "url": ""}
    await env.text("🆕 Yangi mijoz")
    await env.text("Karim")
    await env.text("+998901234567")
    await env.cb("crm:src:telegram")
    assert await env.state() == "Lead:note"
    await send_loc(env, venue="Yunusobod 3")
    assert await env.state() == "Lead:note"  # unchanged
    assert "Lokatsiya arizaga biriktiriladi" in env.session.last().text
    assert not env.backend.to("crm/locations/candidates/")
    await env.text("izoh")
    await env.cb("crm:rem:none")
    assert "📍 Lokatsiya bor" in env.session.last().text
    await env.cb("crm:save")
    body = env.backend.to("crm/leads/")[0][2]
    assert body["location"] == {"lat": LAT, "lon": LON, "address": "Yunusobod 3"}


async def test_location_while_saving_is_ignored(env):
    allow(env)
    script(env)
    await env.set_state("Lead:saving", name="x")
    await send_loc(env)
    assert await env.state() == "Lead:saving"
    assert not env.backend.to("crm/locations/candidates/")
    assert "Lokatsiya arizaga" not in " ".join(env.session.texts())


async def test_finance_draft_state_is_untouched(env):
    allow(env)
    script(env)
    await env.set_state("OpForm:amount", draft="keep")
    await send_loc(env)
    assert await env.state() == "OpForm:amount"
    assert not env.backend.to("crm/locations/candidates/")
    assert not env.backend.to("crm/locations/")
    from aiogram.fsm.storage.base import StorageKey

    key = StorageKey(bot_id=env.bot.id, chat_id=UID, user_id=UID)
    assert (await env.dp.storage.get_data(key)) == {"draft": "keep"}


async def test_group_location_never_reaches_crm(env):
    allow(env)
    script(env)
    env.backend.routes[("POST", "hr/group-message/")] = {"action": "ignored"}
    await send_loc(env, chat_type="supergroup")
    assert await env.state() is None
    assert not env.backend.to("crm/locations/candidates/")
    assert env.backend.to("hr/group-message/")  # HR attendance still gets it


FIN = {
    "id": 7, "telegram_id": 555, "name": "Jasur", "role": "staff", "is_admin": False,
    "is_active_member": True, "is_task_only": False, "has_wallet": True,
}  # fmt: skip


async def test_unrelated_text_in_locpick_clears_and_reaches_finance(env):
    allow(env)
    script(env)
    env.backend.who["finance_member"] = dict(FIN)
    env.backend.routes[("POST", "finance/parse/")] = {"ok": False}
    await send_loc(env)
    assert await env.state() == "LocPick:target"
    await env.text("50000 taksi")
    assert await env.state() is None
    assert env.backend.to("finance/parse/")
    assert not env.backend.to("crm/locations/")


async def test_menu_button_in_locpick_clears_state(env):
    allow(env)
    script(env)
    await send_loc(env)
    from bot.hr.texts import FINANCE_MENU_BUTTONS

    await env.text(sorted(FINANCE_MENU_BUTTONS)[0])
    assert await env.state() is None


async def test_expired_pick_text_goes_on_and_button_is_stale(env):
    import time

    allow(env)
    script(env)
    env.backend.who["finance_member"] = dict(FIN)
    env.backend.routes[("POST", "finance/parse/")] = {"ok": False}
    loc = {"lat": LAT, "lon": LON, "address": "", "live": False}
    await env.set_state("LocPick:target", location=loc, ts=time.time() - 700)
    await env.cb("crm:loc:i:41")
    assert env.session.answers()[-1].text == "Bu tugma eskirgan."
    assert not env.backend.to("crm/locations/")
    assert await env.state() is None
    await env.set_state("LocPick:target", location=loc, ts=time.time() - 700)
    await env.text("+998901234567")
    assert await env.state() is None
    assert not env.backend.to("crm/locations/candidates/")
    assert env.backend.to("finance/parse/")
