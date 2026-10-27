"""Handlers through a real Dispatcher: group outcomes, private-text routing, FSM destiny,
admin command mapping, dv: callbacks, employee_start."""

import copy

from aiogram.methods import SetMessageReaction
from aiogram.types import Message

from bot.backend.client import Conflict, Forbidden, NotFound
from bot.hr import employee_start

from .conftest import EMPLOYEE, buttons, fixture, make_actor

GROUP_RESP = fixture("misc.hr_group_message_response")
EMP = make_actor(employee=EMPLOYEE)
ADMIN = make_actor(tg=555000111, admin=True)


# ------------------------------------------------------------------ group
async def test_group_message_forwards_facts(feed, fake_backend, session):
    fake_backend.on("POST", "hr/group-message/", {"action": "ignored", "react": None, "reply": None, "dm": None})
    await feed.group(video_note={"file_id": "f", "file_unique_id": "u", "length": 240, "duration": 3})
    (c,) = fake_backend.to("hr/group-message/")
    assert c.actor == 777001
    assert c.json["media"]["video_note"] is True and c.json["media"]["photo"] is False
    assert c.json["chat"]["id"] == -1001234567890 and c.json["message_id"] == 55
    assert c.json["date"] == 1790496000 and c.json["forwarded"] is False
    assert not session.sent()


async def test_group_checkin_reacts_replies_and_dms(feed, fake_backend, session):
    fake_backend.on("POST", "hr/group-message/", GROUP_RESP)
    await feed.group(video_note={"file_id": "f", "file_unique_id": "u", "length": 240, "duration": 3})
    (r,) = session.of(SetMessageReaction)
    assert r.reaction[0].emoji == "🔥" and r.chat_id == -1001234567890
    assert "✅ Qabul qilindi, 08:55 — vaqtida" in session.texts(-1001234567890)
    dm = session.sent(777001)[0]
    assert "Xayrli tong, Dilmurod!" in dm.text and "08:55" in dm.text
    assert [b[1] for b in buttons(dm.reply_markup)] == ["dv:uni:2026-10-27:1", "dv:uni:2026-10-27:0"]
    (st,) = fake_backend.to("hr/dm-status/")
    assert st.json == {"telegram_id": 777001, "ok": True, "blocked": False}


async def test_group_late_dm_has_reason_buttons(feed, fake_backend, session):
    resp = copy.deepcopy(GROUP_RESP)
    resp["react"], resp["reply"] = "✍", None
    resp["dm"].update(kind="checkin_late", late_min=25, uniform_ask=False)
    fake_backend.on("POST", "hr/group-message/", resp)
    await feed.group(video_note={"file_id": "f", "file_unique_id": "u", "length": 240, "duration": 3})
    dm = session.sent(777001)[0]
    assert "25 daq" in dm.text
    assert [b[1] for b in buttons(dm.reply_markup)] == ["dv:lr:2026-10-27:1", "dv:lr:2026-10-27:0"]


async def test_blocked_dm_is_reported_to_backend(feed, fake_backend, session):
    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.methods import SendMessage

    session.fail[777001] = TelegramForbiddenError(
        method=SendMessage(chat_id=1, text="x"), message="Forbidden: bot was blocked by the user"
    )
    fake_backend.on("POST", "hr/group-message/", GROUP_RESP)
    await feed.group(video_note={"file_id": "f", "file_unique_id": "u", "length": 240, "duration": 3})
    (st,) = fake_backend.to("hr/dm-status/")
    assert st.json == {"telegram_id": 777001, "ok": False, "blocked": True}


async def test_group_command_ulash_non_admin_is_silent(feed, fake_backend, session):
    fake_backend.on("POST", "hr/groups/", Forbidden("Bu amal faqat rahbar uchun.", 403))
    await feed.group(text="/ulash", entities=[{"type": "bot_command", "offset": 0, "length": 6}])
    assert not session.sent()


async def test_group_ulash_connects_and_warns(feed, fake_backend, session):
    fake_backend.on("POST", "hr/groups/", {"chat_id": -1001234567890, "title": "T", "is_active": True})
    session.members[(-1001234567890, 42)] = "member"
    await feed.group(text="/ulash", entities=[{"type": "bot_command", "offset": 0, "length": 6}])
    (c,) = fake_backend.to("hr/groups/")
    assert c.json == {"chat_id": -1001234567890, "title": "Chilonzor filiali"}
    assert "guruhi kuzatuvga olindi" in session.texts(777001)[0]
    assert "admin" in session.texts(777001)[0]  # the bot is not a group admin
    group_msg = session.sent(-1001234567890)[0]
    assert buttons(group_msg.reply_markup)[0][2] == "https://t.me/sermebel_bot?start=davomat"


async def test_new_members_welcome(feed, fake_backend, session):
    fake_backend.on("POST", "hr/members/joined/", {"welcome": [{"name": "Ali"}]})
    await feed.group(new_chat_members=[{"id": 9, "is_bot": False, "first_name": "Ali"}])
    assert "Xush kelibsiz, Ali!" in session.texts(-1001234567890)[0]


async def test_chat_member_left_and_my_chat_member(feed, fake_backend, session):
    fake_backend.on("POST", "hr/members/left/", {})
    fake_backend.on("POST", "hr/bot-membership/", {})
    await feed.chat_member("chat_member", "left")
    await feed.chat_member("chat_member", "member")  # a join through chat_member: ignored
    await feed.chat_member("my_chat_member", "member")
    assert len(fake_backend.to("hr/members/left/")) == 1
    assert fake_backend.to("hr/bot-membership/")[0].json["status"] == "member"


# ------------------------------------------------------------------ private text routing
async def test_private_text_handled_replies_and_stops(feed, fake_backend, session, set_actor, finance):
    set_actor(EMP)
    fake_backend.on("POST", "hr/private-text/", fixture("misc.hr_private_text_response"))
    await feed.private("20 daqiqa")
    assert fake_backend.to("hr/private-text/")[0].json == {"text": "20 daqiqa"}
    assert "Soat 10:30 ga kutamiz" in session.texts(777001)[0]
    assert finance.messages == []


async def test_private_text_not_handled_falls_to_finance(feed, fake_backend, set_actor, finance, session):
    set_actor(EMP)
    fake_backend.on("POST", "hr/private-text/", {"handled": False, "outcome": None, "data": {}})
    await feed.private("350000 furnitura 406")
    assert finance.messages == ["350000 furnitura 406"]
    assert not session.sent()


async def test_private_text_skipped_while_finance_state_is_set(feed, fake_backend, set_actor, finance, dp):
    from aiogram.fsm.storage.base import StorageKey

    set_actor(EMP)
    key = StorageKey(bot_id=42, chat_id=777001, user_id=777001)
    await dp.fsm.storage.set_state(key, "Tx:amount")
    await feed.private("20 daqiqa")
    assert fake_backend.to("hr/private-text/") == []
    assert finance.messages == ["20 daqiqa"]


async def test_private_text_skipped_for_finance_menu_button(feed, fake_backend, set_actor, finance):
    set_actor(EMP)
    await feed.private("➖ Chiqim")
    assert fake_backend.to("hr/private-text/") == []
    assert finance.messages == ["➖ Chiqim"]


async def test_non_employee_text_never_calls_hr(feed, fake_backend, set_actor, finance):
    set_actor(make_actor(tg=5))
    await feed.private("salom", uid=5)
    assert fake_backend.calls == [] and finance.messages == ["salom"]


# ------------------------------------------------------------------ FSM destiny
async def test_holiday_state_does_not_touch_finance_draft(feed, fake_backend, set_actor, dp, finance):
    from aiogram.fsm.storage.base import StorageKey

    set_actor(ADMIN)
    uid = 555000111
    key = StorageKey(bot_id=42, chat_id=uid, user_id=uid)
    await dp.fsm.storage.set_state(key, "Tx:amount")
    await dp.fsm.storage.set_data(key, {"draft": {"amount": 5}})
    fake_backend.on("GET", "hr/holidays/2026-12-08/decision/", {"day": "2026-12-08", "name": "Konstitutsiya kuni", "decided": False, "days": None})
    await feed.callback("dv:hol:2026-12-08:x", uid=uid)
    hr_key = StorageKey(bot_id=42, chat_id=uid, user_id=uid, destiny="hr")
    assert await dp.fsm.storage.get_state(hr_key) == "HolidayDays:days"
    assert await dp.fsm.storage.get_state(key) == "Tx:amount"
    assert (await dp.fsm.storage.get_data(key)) == {"draft": {"amount": 5}}


async def test_holiday_days_answer_posts_decision(feed, fake_backend, set_actor, dp, session):
    from aiogram.fsm.storage.base import StorageKey

    set_actor(ADMIN)
    uid = 555000111
    hr_key = StorageKey(bot_id=42, chat_id=uid, user_id=uid, destiny="hr")
    await dp.fsm.storage.set_state(hr_key, "HolidayDays:days")
    await dp.fsm.storage.set_data(hr_key, {"hol_day": "2026-12-08"})
    fake_backend.on("POST", "hr/holidays/2026-12-08/decision/", {"days": ["2026-12-08"], "name": "x"})
    await feed.private("3 10.12", uid=uid)
    (c,) = fake_backend.to("hr/holidays/2026-12-08/decision/")
    assert c.json["n"] == 3 and c.json["start"].endswith("-12-10")
    assert await dp.fsm.storage.get_state(hr_key) is None


async def test_holiday_days_ignored_while_finance_state_set(feed, fake_backend, set_actor, dp, finance):
    from aiogram.fsm.storage.base import StorageKey

    set_actor(ADMIN)
    uid = 555000111
    await dp.fsm.storage.set_state(StorageKey(bot_id=42, chat_id=uid, user_id=uid), "Tx:amount")
    await dp.fsm.storage.set_state(
        StorageKey(bot_id=42, chat_id=uid, user_id=uid, destiny="hr"), "HolidayDays:days"
    )
    await feed.private("3", uid=uid)
    assert fake_backend.calls == [] and finance.messages == ["3"]


# ------------------------------------------------------------------ admin commands
async def test_admin_commands_need_hr_admin(feed, fake_backend, set_actor, finance):
    set_actor(EMP)
    await feed.private("/dxodimlar")
    assert fake_backend.calls == []
    assert finance.messages == ["/dxodimlar"]  # falls through


async def test_dam_maps_to_day_off(feed, fake_backend, set_actor, session):
    set_actor(ADMIN)
    fake_backend.on("GET", "hr/employees/5/", EMPLOYEE)
    fake_backend.on("POST", "hr/day-off/", {"employee": EMPLOYEE, "day": "2026-10-27"})
    await feed.private("/dam 5 25.10.2026", uid=555000111)
    (c,) = fake_backend.to("hr/day-off/")
    assert c.json == {"employee": "5", "date": "2026-10-25"} and c.actor == 555000111
    assert "dam kuni" in session.texts(555000111)[0]


async def test_ball_validates_and_posts(feed, fake_backend, set_actor, session):
    set_actor(ADMIN)
    fake_backend.on("GET", "hr/employees/5/", EMPLOYEE)
    fake_backend.on("POST", "hr/points/", {"employee": EMPLOYEE, "value": 10, "reason": "rahmat"})
    await feed.private("/ball 5 +10 rahmat", uid=555000111)
    assert fake_backend.to("hr/points/")[0].json == {"employee": "5", "value": 10, "reason": "rahmat"}
    await feed.private("/ball 5 500", uid=555000111)
    assert len(fake_backend.to("hr/points/")) == 1
    assert "ko'pi bilan 100" in session.texts(555000111)[-1]


async def test_tatil_and_ishvaqti_map_args(feed, fake_backend, set_actor, session):
    set_actor(ADMIN)
    fake_backend.on("GET", "hr/employees/5/", EMPLOYEE)
    fake_backend.on("POST", "hr/leaves/", {"number": 3, "date_from": "2026-11-01", "date_to": "2026-11-05", "reason": "kasal", "employee": EMPLOYEE})
    await feed.private("/tatil 5 01.11.2026 05.11.2026 kasal", uid=555000111)
    assert fake_backend.to("hr/leaves/")[0].json == {
        "employee": "5", "date_from": "2026-11-01", "date_to": "2026-11-05", "reason": "kasal"
    }
    fake_backend.on("PATCH", "hr/employees/5/", {**EMPLOYEE, "hours_label": "10:00–19:00"})
    fake_backend.on("POST", "hr/employees/5/notify/", None)
    await feed.private("/ishvaqti 5 10-19", uid=555000111)
    assert fake_backend.to("hr/employees/5/", "PATCH")[0].json == {"work_start": "10:00", "work_end": "19:00"}
    assert fake_backend.to("hr/employees/5/notify/")[0].json == {"what": "hours"}


async def test_dsozla_and_reyting_and_dhisobot(feed, fake_backend, set_actor, session):
    set_actor(ADMIN)
    fake_backend.on("PUT", "hr/settings/REPORT_TIME/", {"key": "REPORT_TIME", "label": "Kunlik hisobot vaqti", "value": "11:30"})
    await feed.private("/dsozla report_time 11:30", uid=555000111)
    assert fake_backend.to("hr/settings/REPORT_TIME/")[0].json == {"value": "11:30"}
    fake_backend.on("GET", "hr/ranking/", [])
    await feed.private("/reyting yil", uid=555000111)
    assert fake_backend.to("hr/ranking/")[0].params["year"].isdigit()
    fake_backend.on("GET", "hr/reports/day/", fixture("dto.day_report_data.1"))
    await feed.private("/dhisobot 27.10.2026", uid=555000111)
    assert fake_backend.to("hr/reports/day/")[0].params == {"date": "2026-10-27"}
    assert "Kech qolganlar" in session.texts(555000111)[-1]


async def test_unknown_employee_message(feed, fake_backend, set_actor, session):
    set_actor(ADMIN)
    fake_backend.on("GET", "hr/employees/99/", NotFound("Xodim topilmadi.", 404))
    await feed.private("/dchiqar 99", uid=555000111)
    assert "Xodim topilmadi: 99" in session.texts(555000111)[0]


async def test_menu_button_opens_menu(feed, fake_backend, set_actor, session):
    set_actor(ADMIN)
    await feed.private("🕘 Davomat", uid=555000111)
    cbs = [b[1] for b in buttons(session.sent(555000111)[0].reply_markup)]
    assert "dv:m:today" in cbs and "dv:m:help" in cbs


# ------------------------------------------------------------------ callbacks
async def test_employee_callback_relays_and_renders(feed, fake_backend, set_actor, session):
    set_actor(EMP)
    fake_backend.on("POST", "hr/callback/", fixture("misc.hr_callback_response"))
    await feed.callback("dv:uni:2026-10-27:1")
    (c,) = fake_backend.to("hr/callback/")
    assert c.json == {"action": "uni", "day": "2026-10-27", "arg": "1"}
    assert "Toza va tartibli" in session.texts(777001)[0]


async def test_admin_button_refused_for_employee(feed, fake_backend, set_actor, session):
    set_actor(EMP)
    await feed.callback("dv:rst:2026-10-27")
    assert fake_backend.calls == []


async def test_dv_callbacks_never_reach_finance(feed, fake_backend, set_actor, finance):
    set_actor(EMP)
    fake_backend.on("POST", "hr/callback/", {"answer": "", "alert": False, "clear_kb": False, "reply": None})
    await feed.callback("dv:eta:2026-10-27:10")
    assert finance.callbacks == []


async def test_winner_announce_conflict(feed, fake_backend, set_actor, session):
    set_actor(ADMIN)
    fake_backend.on("GET", "hr/employees/777001/", EMPLOYEE)
    fake_backend.on("POST", "hr/winners/", Conflict("Bu tanlov allaqachon e'lon qilingan.", 409))
    await feed.callback("dv:ann:m:2026-10:777001", uid=555000111)
    assert fake_backend.to("hr/winners/")[0].json == {
        "kind": "m", "period": "2026-10", "employee_tg": 777001
    }


async def test_off_request_answer(feed, fake_backend, set_actor):
    set_actor(ADMIN)
    fake_backend.on("GET", "hr/employees/777001/", EMPLOYEE)
    fake_backend.on("POST", "hr/off-requests/", {})
    await feed.callback("dv:offok:2026-10-27:777001", uid=555000111)
    assert fake_backend.to("hr/off-requests/")[0].json == {
        "employee_tg": 777001, "day": "2026-10-27", "approve": True
    }


# ------------------------------------------------------------------ /start and commands
def _msg(uid=777001) -> Message:
    return Message.model_validate(
        {
            "message_id": 1, "date": 1790496000, "chat": {"id": uid, "type": "private"},
            "from": {"id": uid, "is_bot": False, "first_name": "Dilmurod"}, "text": "/start",
        }
    )


async def test_employee_start_existing(fake_backend, tgbot, session):
    m = _msg().as_(tgbot)
    fake_backend.on("POST", "hr/start/", {"employee": EMPLOYEE})
    assert await employee_start(m, EMP, via_link=False) is True
    assert fake_backend.to("hr/start/")[0].json["group_chat_id"] is None
    assert "davomat yordamchisiman" in session.texts(777001)[0]


async def test_employee_start_plain_stranger_is_not_handled(fake_backend, tgbot, session):
    m = _msg(5).as_(tgbot)
    fake_backend.on("GET", "hr/groups/", [])
    fake_backend.on("POST", "hr/start/", {"employee": None})
    assert await employee_start(m, make_actor(tg=5), via_link=False) is False
    assert not session.sent()


async def test_employee_start_link_stranger_gets_hint(fake_backend, tgbot, session):
    m = _msg(5).as_(tgbot)
    fake_backend.on("GET", "hr/groups/", [])
    fake_backend.on("POST", "hr/start/", {"employee": None})
    assert await employee_start(m, make_actor(tg=5), via_link=True) is True
    assert "topilmadingiz" in session.texts(5)[0]


async def test_employee_start_finds_newcomer_in_group(fake_backend, tgbot, session):
    m = _msg(5).as_(tgbot)
    session.members[(-1001234567890, 5)] = "member"
    fake_backend.on("GET", "hr/groups/", [{"chat_id": -1001234567890, "title": "T", "is_active": True}])
    fake_backend.on("POST", "hr/start/", {"employee": EMPLOYEE})
    assert await employee_start(m, make_actor(tg=5), via_link=False) is True
    assert fake_backend.to("hr/start/")[0].json["group_chat_id"] == -1001234567890


async def test_holatim_and_kelolmayman(feed, fake_backend, set_actor, session):
    set_actor(EMP)
    fake_backend.on(
        "GET", "hr/me/status/",
        {"employee": EMPLOYEE, "today": {"st": "on_time", "in_time": "08:55", "out_time": ""},
         "month": {"rank": 2, "of": 9, "pts": 42, "on_time": 20, "late": 1, "late_min": 12,
                   "absent": 0, "excused": 0, "early_n": 0, "disc": 95}},
    )
    await feed.private("/holatim")
    t = session.texts(777001)[0]
    assert "✅ Vaqtida, keldi 08:55" in t and "2-o'rin" in t and "(jami 12 daq)" in t
    fake_backend.on("POST", "hr/cant-come/", {"result": "ask_reason", "day": "2026-10-27", "employee": EMPLOYEE})
    await feed.private("/kelolmayman")
    kb = session.sent(777001)[-1].reply_markup
    assert "dv:rsn:2026-10-27:other" in [b[1] for b in buttons(kb)]


async def test_backend_refusal_is_shown(feed, fake_backend, set_actor, session):
    from bot.backend.client import ServiceRefusal

    set_actor(ADMIN)
    fake_backend.on("PUT", "hr/settings/GRACE_MIN/", ServiceRefusal("Noto'g'ri qiymat", 400))
    await feed.private("/kechikish abc", uid=555000111)
    assert session.texts(555000111)[-1] == "❌ Noto'g'ri qiymat"
