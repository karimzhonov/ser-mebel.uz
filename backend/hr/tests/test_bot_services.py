"""hr.services rules behind the bot API: points, frozen days, statistics. (Behaviour tests
of the endpoints themselves: api/tests/test_bot_hr_api.py.)"""

from datetime import date, datetime

import pytest

from hr import services as S
from hr.models import Attendance, Employee
from hr.tests.conftest import ts

pytestmark = pytest.mark.django_db
DAY = date(2026, 10, 26)
CHAT = {"id": -100777, "title": "Zavod"}


def report(uid, when, media=None, **kw):
    return S.process_group_report(
        chat=CHAT,
        message_id=7,
        ts=ts(when),
        user={"id": uid, "first_name": "Jasur"},
        media=media or {"video_note": True},
        **kw,
    )


def att(uid=500):
    return Attendance.objects.get(employee__telegram_id=uid, day=DAY)


def test_clean_month_bonus(group, clock):
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


def test_late_report_after_day_was_frozen_recomputes_points(group, clock):
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    S.finalize_day(DAY)
    assert att().status == "absent" and att().points == -15
    clock.set(9, 0, day=27)
    report(500, datetime(2026, 10, 26, 9, 40))  # a retried update from yesterday
    a = att()
    assert a.status == "late" and a.points == -5 - 2  # late without reason, no leaving report


def test_off_approved_on_frozen_day_clears_penalty(group, clock):
    e, _ = S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    S.finalize_day(DAY)
    S.set_att(DAY, e, off_requested=True)
    S.answer_off_request(e, DAY, True)
    assert att().status == "off" and att().points is None


def test_finalize_keeps_a_check_in_that_landed_after_the_snapshot(group, clock, monkeypatch):
    e, _ = S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    real = S.compute_day

    def snapshot_then_checkin(day, now_d):
        rows = real(day, now_d)  # sees no arrival yet -> «absent»
        Attendance.objects.update_or_create(
            employee=e, day=day, defaults={"in_time": "09:40", "status": "late", "late_min": 40}
        )
        return rows

    monkeypatch.setattr(S, "compute_day", snapshot_then_checkin)
    S.finalize_day(DAY)
    a = att()
    assert a.status == "late" and a.points == -5 - 2


def test_member_removed_by_another_bot_is_deactivated(group, clock, bot_events, boss):
    S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    S.member_left(CHAT, {"id": 500, "is_bot": False})
    assert Employee.objects.get(telegram_id=500).is_active is False
    assert bot_events.one("hr.employee_left")["name"] == "Jasur"


def test_winner_announcement_is_atomic_and_once(group, clock):
    from core.exceptions import ServiceConflict

    e, _ = S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    res = S.announce_winner("m", "2026-10", e)
    assert res["groups"] == [-100777] and res["pts"] == 0 and res["disc"] == 100
    with pytest.raises(ServiceConflict):
        S.announce_winner("m", "2026-10", e)


def test_toggle_and_set_off_days(group, clock):
    e, _ = S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    S.set_off_days(e, [7, 6, 6])
    assert e.off_days == [6, 7]
    e, was = S.toggle_off_day(e, 6)
    assert was is True and e.off_days == [7]
    e, was = S.toggle_off_day(e, 1)
    assert was is False and e.off_days == [1, 7]
    S.set_off_days(e, None)
    assert Employee.objects.get(pk=e.pk).off_days is None


def test_employee_dto_shape(group, clock):
    e, _ = S.upsert_emp({"id": 500, "first_name": "Jasur", "username": "j"}, group)
    d = S.employee_dto(e)
    assert d == {
        "telegram_id": 500,
        "number": 1,
        "name": "Jasur",
        "username": "j",
        "is_active": True,
        "can_dm": None,
        "group": {"chat_id": -100777, "title": "Zavod"},
        "work_start": "",
        "work_end": "",
        "hours_label": "09:00–18:00",
        "ontime_until": "09:15",
        "off_days": None,
        "off_days_effective": [],
        "off_label": "rahbar belgilaydi",
    }
