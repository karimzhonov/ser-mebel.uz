"""Davomat end to end: group video notes, private answers, schedule, points."""

from datetime import date, datetime

import pytest

from hr import services as S
from hr.jobs import run_schedule
from hr.models import Attendance, Employee, Holiday, Leave, PointAdjustment, Winner, WorkGroup

from .conftest import GROUP, group_msg, press, private, send_update

pytestmark = pytest.mark.django_db
DAY = date(2026, 10, 26)


def att(uid=500, day=DAY):
    return Attendance.objects.get(employee__telegram_id=uid, day=day)


def test_ulash_connects_group(tg, boss):
    send_update(
        {
            "message": {
                "message_id": 1,
                "date": 0,
                "chat": {"id": -100555, "type": "supergroup", "title": "Filial 2"},
                "from": {"id": 100, "is_bot": False, "first_name": "Boss"},
                "text": "/ulash",
            }
        }
    )
    assert WorkGroup.objects.filter(chat_id=-100555, title="Filial 2", is_active=True).exists()


def test_on_time_report_full_day_points(tg, group, clock):
    clock.set(8, 55)
    assert group_msg(500, datetime(2026, 10, 26, 8, 45)) is True
    a = att()
    assert a.status == "on_time" and a.in_time.strftime("%H:%M") == "08:45"
    assert any(m == "setMessageReaction" for m, _, _ in tg.calls)
    assert any("formadamisiz" in t for t in tg.texts(500))
    press(500, "dv:uni:2026-10-26:1")
    group_msg(500, datetime(2026, 10, 26, 18, 5))  # leaving report
    a = att()
    assert a.out_time.strftime("%H:%M") == "18:05" and not a.early_min
    S.finalize_day(DAY)
    a = att()
    assert (
        a.finalized and a.points == 10 + 2 + 2 + 5
    )  # on time, 15 min early bird, uniform, left ok


def test_late_report_asks_reason_and_records_comment(tg, group, clock):
    clock.set(9, 40)
    group_msg(500, datetime(2026, 10, 26, 9, 40))
    a = att()
    assert a.status == "late" and a.late_min == 40 and a.wait == "lr"
    press(500, "dv:lr:2026-10-26:0")
    assert private(500, "tirbandlik bo'ldi") is True
    a = att()
    assert a.late_reason == "Sababsiz" and a.late_comment == "tirbandlik bo'ldi" and a.wait == ""


def test_early_leave_asks_reason(tg, group, clock):
    clock.set(9, 0)
    group_msg(500, datetime(2026, 10, 26, 9, 0))
    clock.set(16, 0)
    group_msg(500, datetime(2026, 10, 26, 16, 0))
    a = att()
    assert a.early_min == 120 and a.wait == "er"
    press(500, "dv:er:2026-10-26:1")
    private(500, "rahbar ruxsat berdi")
    a = att()
    assert a.early_reason == "Sababli" and a.early_comment == "rahbar ruxsat berdi"


def test_photo_instead_of_video_note_is_warned_once(tg, group, clock):
    send_update(
        {
            "message": {
                "message_id": 9,
                "date": int(datetime(2026, 10, 26, 8, 50, tzinfo=S.TZ).timestamp()),
                "chat": {"id": GROUP, "type": "supergroup"},
                "from": {"id": 500, "first_name": "Jasur"},
                "photo": [{"file_id": "P"}],
            }
        }
    )
    assert any("video-doiracha" in t for t in tg.texts(500))
    assert att().warned and not att().in_time


def test_forwarded_report_is_ignored(tg, group, clock):
    send_update(
        {
            "message": {
                "message_id": 9,
                "date": int(datetime(2026, 10, 26, 8, 50, tzinfo=S.TZ).timestamp()),
                "chat": {"id": GROUP, "type": "supergroup"},
                "from": {"id": 500, "first_name": "Jasur"},
                "video_note": {"file_id": "V"},
                "forward_date": 1,
            }
        }
    )
    assert not Attendance.objects.filter(in_time__isnull=False).exists()


def test_unwatched_group_and_admins_are_ignored(tg, group, clock):
    group_msg(500, datetime(2026, 10, 26, 8, 50), chat=-1009999)
    group_msg(100, datetime(2026, 10, 26, 8, 50))  # the boss in the group
    assert not Employee.objects.exists()


def test_schedule_asks_missing_then_eta_then_report_and_finalize(tg, group, clock):
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    S.upsert_emp({"id": 501, "first_name": "Olim"}, group)
    Employee.objects.update(can_dm=True)
    run_schedule(datetime(2026, 10, 26, 8, 35))  # morning reminder in the group
    assert any("Xayrli tong" in t for t in tg.texts(GROUP))
    clock.set(9, 20)
    run_schedule(clock.t)
    assert any("qancha vaqtda" in t for t in tg.texts(500))
    press(500, "dv:eta:2026-10-26:20")
    assert att(500).eta.strftime("%H:%M") == "09:40"
    run_schedule(datetime(2026, 10, 26, 9, 46))
    assert any("yetib kelaman degan edingiz" in t for t in tg.texts(500))
    group_msg(501, datetime(2026, 10, 26, 9, 5))
    tg.reset()
    run_schedule(datetime(2026, 10, 26, 11, 31))
    report = "\n".join(tg.texts(100))
    assert "Kunlik hisobot" in report and "Kelmaganlar" in report and "Jasur" in report
    # next day: yesterday is frozen
    run_schedule(datetime(2026, 10, 27, 7, 0))
    assert att(500).finalized and att(500).status == "absent" and att(500).points == -15
    assert att(501).status == "on_time" and att(501).points == 10 - 2  # no leaving report


def test_cant_come_with_reason(tg, group, clock):
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    clock.set(8, 0)
    private(500, "/kelolmayman")
    press(500, "dv:rsn:2026-10-26:sick")
    a = att()
    assert a.status == "excused" and a.excuse == "Kasal"
    assert any("kela olmasligini" in t for t in tg.texts(100))
    S.finalize_day(DAY)
    assert att().points is None  # excused: no penalty


def test_off_day_request_approved(tg, group, clock):
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    press(500, "dv:offreq:2026-10-26")
    assert "dv:offok:2026-10-26:500" in tg.buttons(100)
    press(100, "dv:offok:2026-10-26:500")
    assert att().status == "off"
    assert not S.expected_today(Employee.objects.get(telegram_id=500), DAY)


def test_old_button_is_refused(tg, group, clock):
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    press(500, "dv:eta:2026-10-20:20")
    assert any(
        p.get("text") == "Bu tugma eskirgan (boshqa kun uchun edi)."
        for m, p, _ in tg.calls
        if m == "answerCallbackQuery"
    )


def test_admin_commands(tg, group, clock):
    e, _ = S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    private(100, f"/tatil {e.number} 27.10.2026 29.10.2026 kasal")
    assert Leave.objects.get().reason == "kasal"
    private(100, f"/ball {e.number} +10 Mijozdan rahmat")
    assert PointAdjustment.objects.get().value == 10
    private(100, f"/ishvaqti {e.number} 10-19")
    e.refresh_from_db()
    assert (e.work_start, e.work_end) == ("10:00", "19:00")
    private(100, "/dsozla GRACE_MIN 10")
    assert S.setting_int("GRACE_MIN") == 10
    private(100, "/dsozla GRACE_MIN abc")
    assert "Noto'g'ri" in tg.last(100)
    private(100, "/bayram 01.01.2027 Yangi yil")
    assert Holiday.objects.filter(day=date(2027, 1, 1)).exists()
    private(100, "/reyting")
    assert "Reyting" in tg.last(100)
    private(100, "/dxodimlar")
    assert "Jasur" in tg.last(100)
    private(100, f"/damkun {e.number} 6,7")
    e.refresh_from_db()
    assert e.off_days == [6, 7]


def test_staff_cannot_use_admin_commands(tg, group, clock):
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    assert private(500, "/dtozala") is False


def test_holiday_ask_and_apply(tg, group, clock):
    run_schedule(datetime(2026, 12, 29, 10, 5))  # 3 days before 01-01
    assert "dv:hol:2027-01-01:2" in tg.buttons(100)
    press(100, "dv:hol:2027-01-01:2")
    assert set(Holiday.objects.values_list("day", flat=True)) >= {
        date(2027, 1, 1),
        date(2027, 1, 2),
    }
    assert any("dam olish kunlari" in t for t in tg.texts(GROUP))


def test_month_winner_announced_once(tg, group, clock):
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    press(100, "dv:ann:m:2026-10:500")
    press(100, "dv:ann:m:2026-10:500")
    assert Winner.objects.count() == 1
    assert sum("eng yaxshi xodimi" in t for t in tg.texts(GROUP)) == 1


def test_clean_month_bonus(tg, group, clock):
    e, _ = S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    Attendance.objects.create(
        employee=e,
        day=date(2026, 9, 10),
        status="on_time",
        in_time="09:00",
        out_time="18:00",
        points=15,
        finalized=True,
    )
    st = S.month_stats("2026-09", datetime(2026, 10, 26, 12, 0))
    me = next(s for s in st if s.e.id == e.id)
    assert me.bonus == 20 and me.pts == 35


def test_finance_entry_from_employee_goes_to_finance(tg, group, clock):
    """A finance member who is also a davomat employee: «350000 furnitura» is money,
    not an ETA."""
    from oauth.models import TelegramMember

    TelegramMember.objects.create(telegram_id=500, name="Jasur", role="staff")
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    S.set_att(DAY, Employee.objects.get(telegram_id=500), asked=1)
    private(500, "350000 furnitura")
    assert att().eta is None
    assert any("tekshiring" in t or "buyurtma" in t.lower() for t in tg.texts(500))


def test_start_davomat_link(tg, group, clock):
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    assert private(500, "/start davomat") is True
    assert "davomat yordamchisiman" in tg.last(500)
    assert Employee.objects.get(telegram_id=500).can_dm is True


def test_blocked_bot_is_remembered(tg, group, clock, monkeypatch):
    e, _ = S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    monkeypatch.setattr(
        "accounting.telegram.api.call",
        lambda *a, **k: {
            "ok": False,
            "error_code": 403,
            "description": "Forbidden: bot was blocked by the user",
        },
    )
    from hr.telegram import dm

    assert dm(e, "salom") is False
    assert Employee.objects.get(pk=e.pk).can_dm is False


def test_claims(tg, group, clock):
    from accounting.telegram.router import claims

    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    grp = {
        "message": {
            "message_id": 1,
            "from": {"id": 500},
            "chat": {"id": GROUP, "type": "supergroup"},
            "video_note": {},
        }
    }
    assert claims(grp) is True
    idle = {
        "message": {
            "message_id": 1,
            "from": {"id": 500},
            "chat": {"id": 500, "type": "private"},
            "text": "salom",
        }
    }
    assert claims(idle) is False  # nothing to answer → site greeting
    assert claims({"my_chat_member": {"from": {"id": 100}, "chat": {"id": GROUP}}}) is True


# ---------------------------------------------------------------- review fixes
def test_late_report_after_day_was_frozen_recomputes_points(tg, group, clock):
    e, _ = S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    S.finalize_day(DAY)
    assert att().status == "absent" and att().points == -15
    clock.set(9, 0, day=27)
    group_msg(500, datetime(2026, 10, 26, 9, 40))  # a retried update from yesterday
    a = att()
    assert a.status == "late" and a.points == -5 - 2  # late without reason, no leaving report


def test_off_approved_on_frozen_day_clears_penalty(tg, group, clock):
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    S.finalize_day(DAY)
    press(100, "dv:offok:2026-10-26:500")
    assert att().status == "off" and att().points is None


def test_finance_menu_button_is_not_a_lateness_comment(tg, group, clock):
    from oauth.models import TelegramMember

    TelegramMember.objects.create(telegram_id=500, name="Jasur", role="staff")
    clock.set(9, 40)
    group_msg(500, datetime(2026, 10, 26, 9, 40))
    press(500, "dv:lr:2026-10-26:0")
    private(500, "➖ Chiqim")
    assert att().late_comment == "" and att().wait == "lc"


def test_member_removed_by_another_bot_is_deactivated(tg, group, clock):
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    send_update(
        {
            "chat_member": {
                "chat": {"id": GROUP, "type": "supergroup"},
                "from": {"id": 999, "is_bot": True},
                "new_chat_member": {"status": "kicked", "user": {"id": 500, "is_bot": False}},
            }
        }
    )
    assert Employee.objects.get(telegram_id=500).is_active is False


def test_finalize_keeps_a_check_in_that_landed_after_the_snapshot(tg, group, clock, monkeypatch):
    e, _ = S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    real = S.compute_day

    def snapshot_then_checkin(day, now_d):
        rows = real(day, now_d)  # sees no arrival yet → «absent»
        Attendance.objects.update_or_create(
            employee=e, day=day, defaults={"in_time": "09:40", "status": "late", "late_min": 40}
        )
        return rows

    monkeypatch.setattr(S, "compute_day", snapshot_then_checkin)
    S.finalize_day(DAY)
    a = att()
    assert a.status == "late" and a.points == -5 - 2
