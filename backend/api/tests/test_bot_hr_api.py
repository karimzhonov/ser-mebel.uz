"""HR (davomat) part of the internal bot API (/api/v1/bot/hr/...). Ports the behaviour
the old Telegram handlers (hr/telegram.py) had: the bot now forwards raw facts and these
endpoints decide. Boss = Telegram id 100 (finance admin = HR admin)."""

from datetime import date, datetime

import pytest

from core.bot_notify import BotUnavailable  # noqa: F401
from hr import services as S
from hr.models import Attendance, Employee, Holiday, Leave, PointAdjustment, Winner, WorkGroup
from hr.tests.hrkit import GROUP, ts

pytestmark = pytest.mark.django_db
DAY = date(2026, 10, 26)
BOSS = 100
CHAT = {"id": GROUP, "title": "Zavod", "username": ""}
VIDEO = {"video_note": True}


def at(h, m=0):
    return datetime(2026, 10, 26, h, m)


def gm(bot, uid, when, media=VIDEO, text="", chat=None, forwarded=False, name="Jasur"):
    return bot.post(
        "hr/group-message/",
        actor=uid,
        data={
            "chat": chat or CHAT,
            "message_id": 55,
            "date": ts(when),
            "from": {"id": uid, "is_bot": False, "first_name": name},
            "forwarded": forwarded,
            "media": media,
            "text": text,
        },
    ).data


def att(uid=500, day=DAY):
    return Attendance.objects.get(employee__telegram_id=uid, day=day)


def cb(bot, uid, action, arg="", day="2026-10-26"):
    return bot.post("hr/callback/", actor=uid, data={"action": action, "day": day, "arg": arg}).data


def text(bot, uid, t):
    return bot.post("hr/private-text/", actor=uid, data={"text": t}).data


def emp(group, uid=500, name="Jasur"):
    e, _ = S.upsert_emp({"id": uid, "first_name": name}, group)
    return e


# ================================================================== group reports
def test_connect_group_is_admin_only(bot_client, boss):
    body = {"chat_id": -100555, "title": "Filial 2"}
    assert bot_client.post("hr/groups/", actor=500, data=body).status_code == 403
    r = bot_client.post("hr/groups/", actor=BOSS, data=body)
    assert r.status_code == 201 and r.data == {
        "chat_id": -100555,
        "title": "Filial 2",
        "is_active": True,
    }
    assert WorkGroup.objects.filter(chat_id=-100555, title="Filial 2", is_active=True).exists()
    assert bot_client.get("hr/groups/", actor=500).data[0]["chat_id"] == -100555
    assert bot_client.delete("hr/groups/-100555/", actor=500).status_code == 403
    assert bot_client.delete("hr/groups/-100555/", actor=BOSS).status_code == 204
    assert not WorkGroup.objects.get(chat_id=-100555).is_active


def test_on_time_report_then_leaving_report_full_day_points(bot_client, group, clock):
    clock.set(8, 55)
    r = gm(bot_client, 500, at(8, 45))
    assert r["action"] == "checkin" and r["react"] == "\U0001f525" and r["reply"] is None
    dm = r["dm"]
    assert dm["kind"] == "checkin_on_time" and dm["at"] == "08:45" and dm["uniform_ask"] is True
    assert dm["employee"]["telegram_id"] == 500 and dm["end"] == "18:00"
    a = att()
    assert a.status == "on_time" and a.in_time.strftime("%H:%M") == "08:45"
    assert cb(bot_client, 500, "uni", "1")["reply"]["kind"] == "uniform_yes"
    out = gm(bot_client, 500, at(18, 5))  # leaving report
    assert out["action"] == "checkout" and out["dm"]["kind"] == "checkout"
    a = att()
    assert a.out_time.strftime("%H:%M") == "18:05" and not a.early_min
    S.finalize_day(DAY)
    assert (
        att().finalized and att().points == 10 + 2 + 2 + 5
    )  # on time, early bird, uniform, left ok


def test_grace_boundary_and_start_of_checkin_window(bot_client, group, clock):
    emp(group, 501, "Olim")
    assert gm(bot_client, 501, at(4, 30), name="Olim")["action"] == "ignored"  # before CHECKIN_FROM
    assert not Attendance.objects.filter(employee__telegram_id=501, in_time__isnull=False).exists()
    ok = gm(bot_client, 500, at(9, 15))  # GRACE_MIN = 15: still on time
    assert att(500).status == "on_time" and ok["dm"]["kind"] == "checkin_on_time"
    late = gm(bot_client, 501, at(9, 16), name="Olim")
    assert att(501).status == "late" and late["dm"]["kind"] == "checkin_late"
    assert late["dm"]["late_min"] == 16 and late["react"] == "✍"


def test_late_report_asks_reason_and_records_comment(bot_client, group, clock, bot_events):
    clock.set(9, 40)
    r = gm(bot_client, 500, at(9, 40))
    assert r["dm"]["kind"] == "checkin_late" and r["dm"]["late_min"] == 40
    a = att()
    assert a.status == "late" and a.late_min == 40 and a.wait == "lr"
    assert a.link == "https://t.me/c/777/55"
    ans = cb(bot_client, 500, "lr", "0")
    assert ans["clear_kb"] is True and ans["reply"]["kind"] == "late_reason_ask"
    assert ans["reply"]["data"]["reason"] == "Sababsiz"
    r = text(bot_client, 500, "tirbandlik bo'ldi")
    assert (
        r["handled"] is True
        and r["outcome"] == "late_comment"
        and r["data"]["late_reason"] == "Sababsiz"
    )
    a = att()
    assert a.late_reason == "Sababsiz" and a.late_comment == "tirbandlik bo'ldi" and a.wait == ""
    assert bot_events == []  # MANAGER_LIVE_ALERTS is off by default


def test_live_alerts_when_enabled(bot_client, group, clock, bot_events, boss):
    S.set_setting("MANAGER_LIVE_ALERTS", "1")
    clock.set(9, 40)
    gm(bot_client, 500, at(9, 40))
    alert = bot_events.one("hr.live_alert")
    assert alert["kind"] == "late" and alert["admins"] == [BOSS]
    assert alert["data"] == {
        "group_title": "Zavod",
        "in_time": "09:40",
        "late_min": 40,
        "link": "https://t.me/c/777/55",
    }
    cb(bot_client, 500, "lr", "1")
    text(bot_client, 500, "mashina buzildi")
    kinds = [e["kind"] for e in bot_events.of("hr.live_alert")]
    assert kinds == ["late", "late_comment"]
    clock.set(9, 50)
    emp(group, 501, "Olim")
    cb(bot_client, 501, "eta", "20")
    assert bot_events.of("hr.live_alert")[-1]["data"] == {"eta": "10:10"}


def test_early_leave_asks_reason(bot_client, group, clock):
    clock.set(9, 0)
    gm(bot_client, 500, at(9, 0))
    clock.set(16, 0)
    r = gm(bot_client, 500, at(16, 0))
    assert (
        r["action"] == "checkout"
        and r["dm"]["kind"] == "checkout_early"
        and r["dm"]["early_min"] == 120
    )
    a = att()
    assert a.early_min == 120 and a.wait == "er"
    assert cb(bot_client, 500, "er", "1")["reply"]["kind"] == "early_reason_ask"
    t = text(bot_client, 500, "rahbar ruxsat berdi")
    assert t["outcome"] == "early_comment" and t["data"]["early_reason"] == "Sababli"
    a = att()
    assert a.early_reason == "Sababli" and a.early_comment == "rahbar ruxsat berdi"
    # a second leaving report after the reason is known: no new question
    again = gm(bot_client, 500, at(16, 30))
    assert again["dm"] is None


def test_second_video_right_after_arrival_is_not_a_leaving_report(bot_client, group, clock):
    gm(bot_client, 500, at(9, 0))
    r = gm(bot_client, 500, at(9, 20))  # OUT_MIN_GAP = 60
    assert r["action"] == "ignored" and att().out_time is None


def test_leaving_report_without_check_in(bot_client, group, clock):
    emp(group)
    r = gm(bot_client, 500, at(17, 30))  # less than 2h before the end of the day
    assert r["action"] == "leave_only" and r["dm"]["kind"] == "leave_without_checkin"
    a = att()
    assert a.no_checkin and a.out_time.strftime("%H:%M") == "17:30" and not a.in_time
    again = gm(bot_client, 500, at(17, 45))
    assert again["action"] == "leave_only" and again["dm"] is None  # told once


def test_photo_instead_of_video_note_is_warned_once(bot_client, group, clock):
    first = gm(bot_client, 500, at(8, 50), media={"photo": True})
    assert first["action"] == "format_warning" and first["dm"]["kind"] == "format_warning"
    assert att().warned and not att().in_time
    assert gm(bot_client, 500, at(8, 51), media={"photo": True})["action"] == "ignored"


def test_forwarded_report_is_ignored(bot_client, group, clock):
    assert gm(bot_client, 500, at(8, 50), forwarded=True)["action"] == "ignored"
    assert not Attendance.objects.filter(in_time__isnull=False).exists()


def test_unwatched_group_inactive_group_and_admins_are_ignored(bot_client, group, clock):
    other = {"id": -1009999, "title": "Boshqa"}
    assert gm(bot_client, 500, at(8, 50), chat=other)["action"] == "ignored"
    assert gm(bot_client, BOSS, at(8, 50))["action"] == "ignored"  # the boss in the group
    assert not Employee.objects.exists()
    group.is_active = False
    group.save()
    assert gm(bot_client, 500, at(8, 50))["action"] == "ignored" and not Employee.objects.exists()


def test_blocked_bot_gets_no_dm_instruction(bot_client, group, clock):
    e = emp(group)
    Employee.objects.filter(pk=e.pk).update(can_dm=False)
    r = gm(bot_client, 500, at(8, 50))
    assert r["action"] == "checkin" and r["dm"] is None


def test_reply_ack_mode(bot_client, group, clock):
    S.set_setting("GROUP_ACK", "reply")
    r = gm(bot_client, 500, at(9, 40))
    assert r["react"] is None and r["reply"] == {"status": "late", "at": "09:40", "late_min": 40}
    S.set_setting("GROUP_ACK", "none")
    assert gm(bot_client, 501, at(8, 40))["react"] is None


# ================================================================== the employee himself
def test_cant_come_with_reason_notifies_admins(bot_client, group, clock, bot_events, boss):
    emp(group)
    clock.set(8, 0)
    assert bot_client.post("hr/cant-come/", actor=500).data["result"] == "ask_reason"
    ans = cb(bot_client, 500, "rsn", "sick")
    assert ans["reply"]["kind"] == "excused_done"
    a = att()
    assert a.status == "excused" and a.excuse == "Kasal"
    alert = bot_events.one("hr.live_alert")
    assert (
        alert["kind"] == "excused"
        and alert["data"] == {"reason": "Kasal"}
        and alert["admins"] == [BOSS]
    )
    S.finalize_day(DAY)
    assert att().points is None  # excused: no penalty
    assert bot_client.post("hr/cant-come/", actor=999).data["result"] == "not_employee"


def test_cant_come_other_reason_is_typed(bot_client, group, clock, bot_events, boss):
    emp(group)
    clock.set(8, 0)
    assert cb(bot_client, 500, "cant")["reply"]["kind"] == "cant_ask"
    assert att().wait == "reason"
    r = text(bot_client, 500, "bolam kasal")
    assert r["outcome"] == "excused" and att().excuse == "bolam kasal" and att().status == "excused"
    assert bot_events.one("hr.live_alert")["data"] == {"reason": "bolam kasal"}


def test_cant_come_after_report_is_refused(bot_client, group, clock):
    gm(bot_client, 500, at(8, 50))
    assert bot_client.post("hr/cant-come/", actor=500).data["result"] == "already_in"


def test_off_day_request_flow(bot_client, group, clock, bot_events, boss):
    emp(group)
    ans = cb(bot_client, 500, "offreq")
    assert ans["reply"]["kind"] == "offreq_sent" and att().off_requested
    req = bot_events.one("hr.off_request")
    assert (
        req["admins"] == [BOSS]
        and req["day"] == "2026-10-26"
        and req["employee"]["telegram_id"] == 500
    )
    assert (
        bot_client.post(
            "hr/off-requests/",
            actor=500,
            data={"employee_tg": 500, "day": "2026-10-26", "approve": True},
        ).status_code
        == 403
    )
    r = bot_client.post(
        "hr/off-requests/",
        actor=BOSS,
        data={"employee_tg": 500, "day": "2026-10-26", "approve": True},
    )
    assert r.status_code == 200
    assert att().status == "off" and not S.expected_today(
        Employee.objects.get(telegram_id=500), DAY
    )
    assert bot_events.one("hr.off_request_answered")["approve"] is True
    # rejected requests keep the day a working day
    emp(group, 501, "Olim")
    cb(bot_client, 501, "offreq")
    bot_client.post(
        "hr/off-requests/",
        actor=BOSS,
        data={"employee_tg": 501, "day": "2026-10-26", "approve": False},
    )
    assert att(501).status != "off" and att(501).off_requested is False


def test_old_button_is_refused(bot_client, group, clock):
    emp(group)
    r = cb(bot_client, 500, "eta", "20", day="2026-10-20")
    assert r["alert"] is True and r["answer"] == "Bu tugma eskirgan (boshqa kun uchun edi)."
    assert r["reply"] is None
    assert cb(bot_client, 999, "eta", "20")["answer"] == "Siz ro'yxatda yo'qsiz"
    assert cb(bot_client, 500, "eta", "20", day="garbage")["answer"] == ""


def test_eta_by_button_and_by_text(bot_client, group, clock):
    emp(group)
    emp(group, 501, "Olim")
    clock.set(9, 20)
    r = cb(bot_client, 500, "eta", "20")
    assert r["reply"] == {
        "kind": "eta_ok",
        "data": {"employee": r["reply"]["data"]["employee"], "eta": "09:40"},
    }
    assert att(500).eta.strftime("%H:%M") == "09:40"
    # typed answer only while the bot is waiting for it (it asked, nothing reported yet)
    assert text(bot_client, 501, "20 daqiqa")["handled"] is False
    S.set_att(DAY, Employee.objects.get(telegram_id=501), asked=1)
    r = text(bot_client, 501, "20 daqiqa")
    assert r["outcome"] == "eta" and r["data"]["eta"] == "09:40"


def test_report_button_after_arrival_is_acknowledged(bot_client, group, clock):
    gm(bot_client, 500, at(8, 50))
    r = cb(bot_client, 500, "cant")
    assert (
        r["answer"].startswith("Siz bugun otchet tashlagansiz")
        and r["clear_kb"]
        and r["reply"] is None
    )


def test_finance_looking_text_is_not_stolen(bot_client, group, clock):
    """A finance member who is also an employee: «350000 furnitura» is money, not an ETA."""
    e = emp(group)
    S.set_att(DAY, e, asked=1)
    r = text(bot_client, 500, "350000 furnitura")
    assert r["handled"] is False and att().eta is None
    # even while waiting for a lateness comment
    gm(bot_client, 500, at(9, 40))
    cb(bot_client, 500, "lr", "0")
    assert text(bot_client, 500, "350000 furnitura")["handled"] is False
    assert att().late_comment == "" and att().wait == "lc"


def test_private_text_of_strangers_and_idle_employees(bot_client, group, clock):
    assert text(bot_client, 999, "salom")["handled"] is False
    emp(group)
    assert text(bot_client, 500, "salom")["handled"] is False  # nothing is being asked
    assert text(bot_client, 500, "  ")["handled"] is False


def test_employee_start_and_status(bot_client, group, clock):
    user = {"id": 500, "first_name": "Jasur", "username": "jasur"}
    r = bot_client.post("hr/start/", actor=500, data={"user": user, "group_chat_id": None})
    assert r.data == {"employee": None}  # not in any work group
    assert bot_client.post("hr/start/", actor=501, data={"user": user}).status_code == 403
    r = bot_client.post("hr/start/", actor=500, data={"user": user, "group_chat_id": GROUP})
    e = r.data["employee"]
    assert e["telegram_id"] == 500 and e["can_dm"] is True and e["hours_label"] == "09:00–18:00"
    assert (
        e["ontime_until"] == "09:15"
        and e["off_label"] == "rahbar belgilaydi"
        and e["group"]["chat_id"] == GROUP
    )
    again = bot_client.post("hr/start/", actor=500, data={"user": user})
    assert again.data["employee"]["number"] == e["number"]  # known now, no group needed
    status = bot_client.get("hr/me/status/", actor=500).data
    assert status["employee"]["telegram_id"] == 500 and status["month"]["rank"] == 1
    assert status["today"]["st"] in ("waiting", "absent")
    assert bot_client.get("hr/me/status/", actor=999).status_code == 404


def test_dm_status_and_delivery_results_flip_can_dm(bot_client, group):
    e = emp(group)
    bot_client.post(
        "hr/dm-status/", actor=500, data={"telegram_id": 500, "ok": False, "blocked": True}
    )
    assert Employee.objects.get(pk=e.pk).can_dm is False
    bot_client.post("hr/dm-status/", actor=500, data={"telegram_id": 500, "ok": True})
    assert Employee.objects.get(pk=e.pk).can_dm is True
    S.record_dm_results(
        [{"chat_id": 500, "ok": False, "blocked": True}, {"chat_id": -1, "ok": True}]
    )
    assert Employee.objects.get(pk=e.pk).can_dm is False
    S.record_dm_results([{"chat_id": 500, "ok": False, "blocked": False}])  # transient failure
    assert Employee.objects.get(pk=e.pk).can_dm is False
    S.record_dm_results([{"chat_id": 500, "ok": True, "blocked": False}])
    assert Employee.objects.get(pk=e.pk).can_dm is True


def test_whoami_marks_employee_reachable(bot_client, group):
    e = emp(group)
    assert e.can_dm is None
    r = bot_client.post("whoami/", actor=500, data={"user": {"id": 500}})
    assert r.data["hr"]["employee"]["telegram_id"] == 500
    assert Employee.objects.get(pk=e.pk).can_dm is True


# ================================================================== membership
def test_joins_leaves_and_bot_added(bot_client, group, bot_events, boss):
    users = [
        {"id": 500, "first_name": "Jasur", "is_bot": False},
        {"id": 900, "first_name": "Bot", "is_bot": True},
        {"id": BOSS, "first_name": "Boss", "is_bot": False},
    ]
    r = bot_client.post("hr/members/joined/", actor=999, data={"chat": CHAT, "users": users})
    assert r.data == {"welcome": [{"name": "Jasur"}]}
    assert (
        Employee.objects.filter(telegram_id=500).exists()
        and not Employee.objects.filter(telegram_id__in=[900, BOSS]).exists()
    )
    Employee.objects.filter(telegram_id=500).update(can_dm=True)
    assert (
        bot_client.post("hr/members/joined/", actor=999, data={"chat": CHAT, "users": users}).data[
            "welcome"
        ]
        == []
    )
    other = {"id": -1009999}
    assert (
        bot_client.post("hr/members/joined/", actor=999, data={"chat": other, "users": users}).data[
            "welcome"
        ]
        == []
    )
    # someone removed by another bot is dropped, once, and the admins are told
    left = bot_client.post("hr/members/left/", actor=999, data={"chat": CHAT, "user": users[0]})
    assert left.status_code == 200 and Employee.objects.get(telegram_id=500).is_active is False
    assert bot_events.one("hr.employee_left") == {"admins": [BOSS], "name": "Jasur"}
    bot_client.post("hr/members/left/", actor=999, data={"chat": CHAT, "user": users[0]})
    assert len(bot_events.of("hr.employee_left")) == 1
    # the bot is added to a new group: tell the admins, once per unwatched group
    new = {"id": -100123, "title": "Yangi filial", "type": "supergroup"}
    bot_client.post("hr/bot-membership/", actor=999, data={"chat": new, "status": "member"})
    assert bot_events.one("hr.bot_added_to_group")["title"] == "Yangi filial"
    bot_client.post("hr/bot-membership/", actor=999, data={"chat": CHAT, "status": "member"})
    bot_client.post("hr/bot-membership/", actor=999, data={"chat": new, "status": "left"})
    assert len(bot_events.of("hr.bot_added_to_group")) == 1


# ================================================================== admin commands
def test_admin_commands_map_to_services(bot_client, group, clock, bot_events, boss):
    e = emp(group)
    n = e.number
    assert bot_client.get("hr/employees/", actor=500).status_code == 403
    r = bot_client.post(
        "hr/leaves/",
        actor=BOSS,
        data={"employee": n, "date_from": "27.10.2026", "date_to": "29.10.2026", "reason": "kasal"},
    )
    assert r.status_code == 201 and Leave.objects.get().reason == "kasal"
    assert bot_events.one("hr.leave_added")["date_to"] == "2026-10-29"
    assert len(bot_client.get("hr/leaves/", actor=BOSS).data) == 1
    assert bot_client.delete(f"hr/leaves/{r.data['number']}/", actor=BOSS).status_code == 204
    assert bot_client.delete("hr/leaves/99/", actor=BOSS).status_code == 404
    r = bot_client.post(
        "hr/points/", actor=BOSS, data={"employee": n, "value": "+10", "reason": "Mijozdan rahmat"}
    )
    assert r.status_code == 201 and PointAdjustment.objects.get().value == 10
    pe = bot_events.one("hr.points_added")
    assert pe["value"] == 10 and pe["from_site"] is False and pe["employee"]["telegram_id"] == 500
    assert (
        bot_client.post("hr/points/", actor=BOSS, data={"employee": n, "value": 500}).status_code
        == 400
    )
    r = bot_client.patch(
        f"hr/employees/{n}/", actor=BOSS, data={"work_start": "10:00", "work_end": "19:00"}
    )
    assert r.data["hours_label"] == "10:00–19:00" and r.data["ontime_until"] == "10:15"
    e.refresh_from_db()
    assert (e.work_start, e.work_end) == ("10:00", "19:00")
    assert (
        bot_client.patch(
            f"hr/employees/{n}/", actor=BOSS, data={"work_start": "19:00", "work_end": "10:00"}
        ).status_code
        == 400
    )
    assert (
        bot_client.patch(f"hr/employees/{n}/", actor=BOSS, data={"reset_hours": True}).data[
            "work_start"
        ]
        == ""
    )
    assert (
        bot_client.post(f"hr/employees/{n}/notify/", actor=BOSS, data={"what": "hours"}).status_code
        == 204
    )
    assert bot_events.one("hr.hours_set")["employee"]["telegram_id"] == 500
    r = bot_client.patch(f"hr/employees/{n}/", actor=BOSS, data={"off_days": [6, 7]})
    assert r.data["off_days"] == [6, 7] and r.data["off_label"] == "Shanba, Yakshanba"
    r = bot_client.patch(f"hr/employees/{n}/", actor=BOSS, data={"toggle_off_day": 6})
    assert r.data["off_days"] == [7]
    assert (
        bot_client.patch(f"hr/employees/{n}/", actor=BOSS, data={"off_days": "general"}).data[
            "off_days"
        ]
        is None
    )
    assert (
        bot_client.post(
            f"hr/employees/{n}/notify/", actor=BOSS, data={"what": "off_days"}
        ).status_code
        == 204
    )
    assert bot_events.one("hr.off_days_set")
    assert (
        bot_client.patch(f"hr/employees/{n}/", actor=BOSS, data={"is_active": False}).data[
            "is_active"
        ]
        is False
    )
    assert [
        x["telegram_id"] for x in bot_client.get("hr/employees/?active=1", actor=BOSS).data
    ] == []
    assert (
        bot_client.get(f"hr/employees/{e.telegram_id}/", actor=BOSS).data["number"] == n
    )  # by tg id too
    assert bot_client.get("hr/employees/9999/", actor=BOSS).status_code == 404
    r = bot_client.post("hr/day-off/", actor=BOSS, data={"employee": n, "date": "bugun"})
    assert r.data["day"] == "2026-10-26" and att().status == "off"
    assert bot_events.one("hr.day_off_set")["day"] == "2026-10-26"
    assert (
        bot_client.post(
            "hr/day-off/", actor=BOSS, data={"employee": n, "date": "kecha-kecha"}
        ).status_code
        == 400
    )


def test_settings_endpoints(bot_client, group, boss):
    assert bot_client.get("hr/settings/", actor=500).status_code == 403
    rows = bot_client.get("hr/settings/", actor=BOSS).data
    assert {"key": "GRACE_MIN", "label": "Kechikishga ruxsat (daq)", "value": "15"} in rows
    r = bot_client.put("hr/settings/GRACE_MIN/", actor=BOSS, data={"value": "10"})
    assert r.data["value"] == "10" and S.setting_int("GRACE_MIN") == 10
    assert (
        bot_client.put("hr/settings/GRACE_MIN/", actor=BOSS, data={"value": "abc"}).status_code
        == 400
    )
    assert bot_client.put("hr/settings/NOPE/", actor=BOSS, data={"value": "1"}).status_code == 400


def test_holidays_and_decision(bot_client, group, clock, bot_events, boss):
    r = bot_client.post("hr/holidays/", actor=BOSS, data={"day": "01.01.2027", "name": "Yangi yil"})
    assert r.status_code == 201 and Holiday.objects.filter(day=date(2027, 1, 1)).exists()
    assert [h["name"] for h in bot_client.get("hr/holidays/", actor=BOSS).data] == ["Yangi yil"]
    assert bot_client.delete("hr/holidays/2027-01-01/", actor=BOSS).status_code == 204
    assert bot_client.delete("hr/holidays/2027-01-01/", actor=BOSS).status_code == 404
    g = bot_client.get("hr/holidays/2027-03-21/decision/", actor=BOSS).data
    assert g == {"day": "2027-03-21", "name": "Navro'z bayrami", "decided": False, "days": None}
    r = bot_client.post(
        "hr/holidays/2027-01-01/decision/", actor=BOSS, data={"n": 2, "start": "2027-01-01"}
    )
    assert (
        r.status_code == 200
        and r.data["days"] == ["2027-01-01", "2027-01-02"]
        and r.data["name"] == "Yangi yil"
    )
    assert set(Holiday.objects.values_list("day", flat=True)) >= {
        date(2027, 1, 1),
        date(2027, 1, 2),
    }
    ev = bot_events.one("hr.holiday_applied")
    assert (
        ev["n"] == 2
        and ev["groups"] == [GROUP]
        and ev["admins"] == [BOSS]
        and ev["days"] == r.data["days"]
    )
    assert (
        bot_client.post("hr/holidays/2027-01-01/decision/", actor=BOSS, data={"n": 1}).status_code
        == 409
    )
    assert bot_client.get("hr/holidays/2027-01-01/decision/", actor=BOSS).data["decided"] is True
    assert (
        bot_client.post("hr/holidays/2027-01-01/decision/", actor=500, data={"n": 1}).status_code
        == 403
    )


def test_month_winner_announced_once(bot_client, group, clock, bot_events, boss):
    emp(group)
    body = {"kind": "m", "period": "2026-10", "employee_tg": 500}
    assert bot_client.post("hr/winners/", actor=500, data=body).status_code == 403
    r = bot_client.post("hr/winners/", actor=BOSS, data=body)
    assert r.status_code == 201 and r.data == {"groups_count": 1}
    assert bot_client.post("hr/winners/", actor=BOSS, data=body).status_code == 409
    assert Winner.objects.count() == 1
    ev = bot_events.one("hr.winner_announced")
    assert (
        ev["kind"] == "m"
        and ev["period"] == "2026-10"
        and ev["groups"] == [GROUP]
        and ev["employee"]["telegram_id"] == 500
    )
    assert (
        bot_client.post("hr/winners/", actor=BOSS, data={**body, "period": "2026"}).status_code
        == 400
    )
    assert (
        bot_client.post("hr/winners/", actor=BOSS, data={**body, "employee_tg": 1}).status_code
        == 404
    )


def test_reports_ranking_and_reset(bot_client, group, clock, boss):
    emp(group)
    emp(group, 501, "Olim")
    gm(bot_client, 500, at(8, 50))
    clock.set(12, 0)
    live = bot_client.get("hr/reports/day/", actor=BOSS).data
    assert live["kind"] == "live" and live["expected"] == 2 and live["empty"] is False
    assert [x["name"] for x in live["on_time"]] == ["Jasur"] and [
        x["name"] for x in live["absent"]
    ] == ["Olim"]
    assert bot_client.get("hr/reports/day/", actor=500).status_code == 403
    S.finalize_day(DAY)
    clock.set(8, 0, day=27)  # the next morning: 26.10 is a finished day
    past = bot_client.get("hr/reports/day/?date=2026-10-26", actor=BOSS).data
    assert past["kind"] == "past" and past["on_time"] == 1 and past["absent_names"] == ["Olim"]
    empty = bot_client.get("hr/reports/day/?date=2026-09-01", actor=BOSS).data
    assert empty == {"kind": "past", "day": "2026-09-01", "empty": True}
    per = bot_client.get("hr/reports/period/?from=2026-10-01&to=2026-10-31", actor=BOSS).data
    assert per["kind"] == "period" and per["on_time"] == 1 and per["rows"][0]["telegram_id"] == 500
    rank = bot_client.get("hr/ranking/?month=2026-10", actor=BOSS).data
    assert rank[0]["name"] == "Jasur" and set(rank[0]) == {
        "telegram_id",
        "name",
        "pts",
        "disc",
        "bonus",
        "adj",
        "wins",
    }
    assert bot_client.get("hr/ranking/?year=2026", actor=BOSS).status_code == 200
    assert bot_client.get("hr/ranking/?month=oct", actor=BOSS).status_code == 400
    assert bot_client.post("hr/reset/", actor=500, data={"since": "2026-10-27"}).status_code == 403
    assert bot_client.post("hr/reset/", actor=BOSS, data={"since": "2026-10-27"}).status_code == 204
    assert not Attendance.objects.exists() and S.since() == date(2026, 10, 27)


def test_everything_in_admin_land_is_closed_to_employees(bot_client, group, clock, boss):
    emp(group)
    for method, path in [
        ("get", "hr/employees/"),
        ("get", "hr/employees/1/"),
        ("get", "hr/leaves/"),
        ("get", "hr/holidays/"),
        ("get", "hr/settings/"),
        ("get", "hr/reports/day/"),
        ("get", "hr/ranking/"),
        ("post", "hr/points/"),
        ("post", "hr/day-off/"),
        ("post", "hr/groups/"),
    ]:
        assert getattr(bot_client, method)(path, actor=500).status_code == 403, path
