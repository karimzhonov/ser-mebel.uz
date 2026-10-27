"""The davomat schedule decides who to ask and when; the bot sends. Sync steps count an ask
only on a confirmed delivery and stop quietly when the bot is down."""

from datetime import date, datetime

import pytest

from core.bot_notify import BotUnavailable
from hr import services as S
from hr.jobs import run_schedule
from hr.models import Attendance, Employee, HrState
from hr.tests.conftest import GROUP

pytestmark = pytest.mark.django_db
DAY = date(2026, 10, 26)


class FakeBot:
    """Stands in for core.bot_notify.send_event_sync."""

    def __init__(self):
        self.calls = []
        self.ids = []
        self.down = False
        self.unreachable = set()  # telegram ids that blocked the bot

    def __call__(self, event, data, timeout=10, envelope_id=None):
        self.ids.append(envelope_id)
        if self.down:
            raise BotUnavailable("down")
        self.calls.append((event, data))
        tg = data["employee"]["telegram_id"]
        blocked = tg in self.unreachable
        return {
            "ok": True,
            "delivered": [
                {
                    "chat_id": tg,
                    "ok": not blocked,
                    "blocked": blocked,
                    "message_id": None if blocked else 1,
                }
            ],
        }

    def of(self, event):
        return [d for e, d in self.calls if e == event]


@pytest.fixture
def bot(monkeypatch):
    fake = FakeBot()
    monkeypatch.setattr("hr.events.send_event_sync", fake)
    return fake


def people(group):
    a, _ = S.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    b, _ = S.upsert_emp({"id": 501, "first_name": "Olim"}, group)
    Employee.objects.update(can_dm=True)
    return a, b


def att(uid, day=DAY):
    return Attendance.objects.get(employee__telegram_id=uid, day=day)


def test_full_morning_to_next_day(bot, bot_events, group, clock, boss):
    people(group)
    done = run_schedule(datetime(2026, 10, 26, 8, 35))  # morning reminder in the group
    assert f"morning_{GROUP}" in done
    morning = bot_events.one("hr.morning")
    assert morning == {"chat_id": GROUP, "starts": ["09:00"], "uniform_check": True}
    clock.set(9, 20)
    run_schedule(clock.t)
    asked = bot.of("hr.ask_eta")
    assert {a["employee"]["telegram_id"] for a in asked} == {500, 501}
    assert all(
        a["start"] == "09:00" and a["repeat"] is False and a["day"] == "2026-10-26" for a in asked
    )
    assert att(500).asked == 1 and att(501).asked == 1
    S.process_employee_callback(500, "eta", "2026-10-26", "20")
    assert att(500).eta.strftime("%H:%M") == "09:40"
    S.process_group_report(
        chat={"id": GROUP},
        message_id=1,
        ts=int(datetime(2026, 10, 26, 9, 5).replace(tzinfo=S.TZ).timestamp()),
        user={"id": 501, "first_name": "Olim"},
        media={"video_note": True},
    )
    clock.set(9, 46)
    run_schedule(clock.t)
    passed = bot.of("hr.eta_passed")
    assert [p["employee"]["telegram_id"] for p in passed] == [500] and passed[0]["eta"] == "09:40"
    assert att(500).asked == 2 and att(500).eta_sent is True
    run_schedule(datetime(2026, 10, 26, 11, 31))
    report = bot_events.one("hr.day_report")
    assert report["now_hm"] == "11:31" and report["admins"] == [100]
    assert report["report"]["kind"] == "live" and [
        a["name"] for a in report["report"]["absent"]
    ] == ["Jasur"]
    assert [a["name"] for a in report["report"]["on_time"]] == ["Olim"]
    run_schedule(datetime(2026, 10, 26, 11, 40))
    assert len(bot_events.of("hr.day_report")) == 1  # once a day
    # next day: yesterday is frozen
    run_schedule(datetime(2026, 10, 27, 7, 0))
    assert att(500).finalized and att(500).status == "absent" and att(500).points == -15
    assert att(501).status == "on_time" and att(501).points == 10 - 2  # no leaving report


def test_an_ask_counts_only_when_the_person_was_reached(bot, bot_events, group, clock):
    people(group)
    bot.unreachable.add(500)
    clock.set(9, 20)
    run_schedule(clock.t)
    assert Attendance.objects.filter(employee__telegram_id=500, asked__gt=0).count() == 0
    assert att(501).asked == 1
    assert Employee.objects.get(telegram_id=500).can_dm is False  # blocked is remembered
    # people who blocked the bot are not tried again
    bot.calls.clear()
    clock.set(10, 5)
    run_schedule(clock.t)
    assert 500 not in {c["employee"]["telegram_id"] for c in bot.of("hr.ask_eta")}


def test_bot_down_stops_the_tick_and_the_next_tick_retries(bot, bot_events, group, clock):
    people(group)
    bot.down = True
    clock.set(9, 20)
    run_schedule(clock.t)
    assert not Attendance.objects.filter(asked__gt=0).exists()
    assert not HrState.objects.filter(
        key__startswith="f_2026-10-26_ask_"
    ).exists()  # nothing consumed
    bot.down = False
    clock.set(9, 21)
    run_schedule(clock.t)
    assert {a["employee"]["telegram_id"] for a in bot.of("hr.ask_eta")} == {500, 501}
    assert att(500).asked == 1 and att(501).asked == 1


def test_bot_down_in_the_middle_does_not_mark_the_unsent(bot, bot_events, group, clock):
    people(group)
    sent = []

    def flaky(event, data, timeout=10, envelope_id=None):
        if sent:
            raise BotUnavailable("down")
        sent.append(1)
        return bot(event, data, envelope_id=envelope_id)

    import hr.events as E

    E.send_event_sync = flaky
    try:
        clock.set(9, 20)
        run_schedule(clock.t)
    finally:
        E.send_event_sync = bot
    assert Attendance.objects.filter(asked=1).count() == 1  # first delivered, second left for later
    clock.set(9, 21)
    run_schedule(clock.t)
    assert Attendance.objects.filter(asked=1).count() == 2


def test_repeat_ask_and_ask_limit(bot, bot_events, group, clock):
    a, _ = people(group)
    clock.set(10, 5)  # start 09:00 + REPEAT_ASK_MIN 60 = 10:00
    run_schedule(clock.t)
    rep = [c for c in bot.of("hr.ask_eta") if c["repeat"]]
    assert {c["employee"]["telegram_id"] for c in rep} == {500, 501}
    S.set_att(DAY, a, asked=4)  # MAX_ASKS reached
    S.set_att(DAY, a, eta=S.to_time(9 * 60 + 30), eta_sent=False)
    bot.calls.clear()
    clock.set(10, 6)
    run_schedule(clock.t)
    assert bot.of("hr.eta_passed") == [] and att(500).eta_sent is True


def test_leaving_reminder_after_work_end(bot, bot_events, group, clock):
    a, _ = people(group)
    S.set_att(
        DAY, a, in_time=S.to_time(540), status="on_time", work_start="09:00", work_end="18:00"
    )
    clock.set(19, 5)  # 18:00 + OUT_REMIND_MIN 60
    run_schedule(clock.t)
    assert [c["employee"]["telegram_id"] for c in bot.of("hr.out_reminder")] == [500]
    run_schedule(clock.t)
    assert len(bot.of("hr.out_reminder")) == 1  # once


def test_group_list_of_missing_people(bot, bot_events, group, clock):
    people(group)
    S.set_setting("GROUP_LIST_MISSING", "1")
    clock.set(9, 20)
    run_schedule(clock.t)
    ev = bot_events.one("hr.missing_list")
    assert ev["chat_id"] == GROUP and ev["names"] == ["Jasur", "Olim"]


def test_holiday_question_is_asked_once(bot, bot_events, group, clock, boss):
    run_schedule(datetime(2026, 12, 29, 10, 5))  # 3 days before 01-01
    ev = bot_events.one("hr.holiday_ask")
    assert ev == {"admins": [100], "day": "2027-01-01", "name": "Yangi yil"}
    run_schedule(datetime(2026, 12, 29, 10, 6))
    assert len(bot_events.of("hr.holiday_ask")) == 1


def test_month_end_reports_and_winner_pick(bot, bot_events, group, clock, boss):
    a, _ = people(group)
    Attendance.objects.create(
        employee=a,
        day=date(2026, 10, 12),
        status="on_time",
        in_time="09:00",
        out_time="18:00",
        points=15,
        finalized=True,
    )
    clock.set(21, 5, day=31)
    run_schedule(datetime(2026, 10, 31, 21, 5))
    rep = bot_events.one("hr.month_report")
    assert (
        rep["ym"] == "2026-10"
        and rep["report"]["kind"] == "period"
        and rep["site_url"].endswith("/hr")
    )
    pick = bot_events.one("hr.winner_pick")
    assert (
        pick["kind"] == "m"
        and pick["period"] == "2026-10"
        and pick["rows"][0]["telegram_id"] == 500
    )
    assert "year" not in bot_events.names()
    run_schedule(datetime(2026, 10, 31, 21, 6))
    assert len(bot_events.of("hr.month_report")) == 1


def test_year_pick_on_the_last_day_of_the_year(bot, bot_events, group, clock, boss):
    a, _ = people(group)
    Attendance.objects.create(
        employee=a,
        day=date(2026, 3, 3),
        status="on_time",
        in_time="09:00",
        out_time="18:00",
        points=15,
        finalized=True,
    )
    run_schedule(datetime(2026, 12, 31, 21, 5))
    kinds = [e["kind"] for e in bot_events.of("hr.winner_pick")]
    assert kinds == ["m", "y"] or kinds == ["y"]
    assert bot_events.of("hr.winner_pick")[-1]["period"] == "2026"
