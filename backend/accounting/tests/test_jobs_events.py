"""Scheduled finance jobs and the order follow-up: they decide who is told what (events);
the bot service renders. `S.once` keeps every reminder to once."""

from datetime import date, timedelta

import pytest
from constance import config

from accounting import events as E
from accounting import followup, jobs, tasks
from accounting import services as S
from accounting.models import ClientFeedback, FinanceJobRun, MonthReport, OrderBonus, SiteEntryTask
from oauth.models import TelegramMember

pytestmark = pytest.mark.django_db


def booked(member, amount=1000, **kw):
    return S.create_operation(
        member=member, author=member, kind="expense", amount=amount, category_code="ovqat", **kw
    )


# ---------------------------------------------------------------- daily jobs
def test_daily_reminder_goes_to_every_silent_staff_member(members, bot_events):
    boss, ali, vali = members
    booked(ali)
    jobs.daily_reminder()
    evs = bot_events.of("finance.daily_reminder")
    assert [e["member"]["telegram_id"] for e in evs] == [
        300
    ]  # Ali wrote today, the boss isn't staff
    assert evs[0]["balance"] == "0.00"


def test_admin_daily_sends_the_summary_and_the_excel_only_on_the_first(
    members, bot_events, monkeypatch
):
    boss, ali, vali = members
    booked(ali, 5000)
    jobs.admin_daily()
    ev = bot_events.one("finance.admin_daily")
    assert ev["summary"]["expense"] == "5000.00" and ev["ops_count"] == 1 and ev["admins"] == [100]
    assert ev["by_member"] == [{"name": "Ali", "sum": "5000.00"}] and ev["silent"] == ["Vali"]
    assert "checks" in ev and not bot_events.of("finance.month_excel")
    monkeypatch.setattr("accounting.jobs.today", lambda: date(2026, 11, 1))
    monkeypatch.setattr("accounting.jobs.cur_month", lambda: "2026-11")
    jobs.admin_daily()
    excel = bot_events.one("finance.month_excel")
    assert excel == {"month": "2026-10", "admins": [100]}


def test_month_job_reminds_late_submitters_and_tells_the_boss_on_the_third(
    members, bot_events, monkeypatch
):
    boss, ali, vali = members
    booked(ali, 1000, on_date=date(2026, 10, 20), actor_admin=True)
    MonthReport.objects.create(
        member=vali, month="2026-11", submitted_at="2026-11-01T10:00", balance=0
    )
    monkeypatch.setattr("accounting.jobs.today", lambda: date(2026, 11, 3))
    monkeypatch.setattr("accounting.jobs.cur_month", lambda: "2026-11")
    jobs.month_job()
    # end of month is far away: no "last days" reminders
    assert not bot_events.of("finance.month_end_reminder")
    late = bot_events.of("finance.month_late")
    assert [(e["member"]["telegram_id"], e["month"]) for e in late] == [(200, "2026-10")]
    assert bot_events.one("finance.month_late_admins") == {
        "month": "2026-10",
        "names": ["Ali"],
        "admins": [100],
    }


def test_month_job_end_of_month_reminder(members, bot_events, monkeypatch):
    monkeypatch.setattr("accounting.jobs.today", lambda: date(2026, 10, 30))
    monkeypatch.setattr("accounting.jobs.cur_month", lambda: "2026-10")
    jobs.month_job()
    evs = bot_events.of("finance.month_end_reminder")
    assert {e["member"]["telegram_id"] for e in evs} == {200, 300} and evs[0]["left_days"] == 1


def test_each_task_runs_once_a_day_and_only_once_per_hour(members, bot_events):
    assert tasks.admin_daily() is True
    assert tasks.hourly_orders() is True
    assert tasks.admin_daily() is False
    assert tasks.hourly_orders() is False
    assert len(bot_events.of("finance.admin_daily")) == 1
    tasks.cleanup()


def test_beat_schedule_follows_settings_and_has_no_update_replay(db):
    from django_celery_beat.models import PeriodicTask

    from accounting.schedule import sync_periodic_tasks

    config.FIN_REMINDER_HOUR = 18
    sync_periodic_tasks()
    sync_periodic_tasks()  # idempotent
    t = PeriodicTask.objects.get(task="accounting.tasks.daily_reminder")
    assert t.crontab.hour == "18" and t.crontab.minute == "0"
    assert PeriodicTask.objects.filter(task="hr.tasks.tick").count() == 1
    assert not PeriodicTask.objects.filter(task__contains="replay_updates").exists()
    # a row left over from before the bot moved out is removed by the sync
    PeriodicTask.objects.create(
        name="moliya: uzilgan update'lar", task="accounting.tasks.replay_updates", crontab=t.crontab
    )
    sync_periodic_tasks()
    assert not PeriodicTask.objects.filter(task__contains="replay_updates").exists()


def test_cleanup_only_touches_job_markers(db):
    old = FinanceJobRun.objects.create(key="old")
    FinanceJobRun.objects.filter(pk=old.pk).update(created_at="2020-01-01T00:00")
    FinanceJobRun.objects.create(key="new")
    jobs.cleanup()
    assert list(FinanceJobRun.objects.values_list("key", flat=True)) == ["new"]


# ---------------------------------------------------------------- Готов, bonus
def make_done(site_order, since_days_ago=1):
    config.FIN_BONUS_SINCE = (date.today() - timedelta(days=since_days_ago)).isoformat()
    site_order.status = "done"
    site_order.save()


def test_new_ready_orders_are_capped_at_five_per_pass(
    members, bot_events, db_client, default_factory
):
    from djmoney.money import Money

    from order.models import Order

    config.FIN_BONUS_SINCE = (date.today() - timedelta(days=1)).isoformat()
    for n in range(500, 508):
        o = Order.objects.create(
            order_number=n,
            client=db_client,
            reception_date=date.today(),
            factory=default_factory,
            price=Money(1000, "USD"),
            lost_money=Money(0, "USD"),
        )
        o.status = "done"  # a new order always starts in the waiting list
        o.save()
    followup.hourly_orders(ok_hour=True)
    assert OrderBonus.objects.count() == 5 and len(bot_events.of("finance.ready_card")) == 5
    followup.hourly_orders(ok_hour=True)
    assert OrderBonus.objects.count() == 8 and len(bot_events.of("finance.ready_card")) == 8
    assert not followup.new_ready_orders([], ok_hour=False)  # nothing at night


def test_order_becoming_ready_queues_the_card_once(site_order, django_capture_on_commit_callbacks, ready_queue):
    with django_capture_on_commit_callbacks(execute=True):
        site_order.status = "done"
        site_order.save()
    assert ready_queue == ["406"]
    with django_capture_on_commit_callbacks(execute=True):
        site_order.desc = "edited after Готов"
        site_order.save()  # already Готов: nothing new
    assert ready_queue == ["406"]


def test_order_ready_sends_the_card_at_once_at_any_hour(members, site_order, bot_events):
    make_done(site_order)
    assert tasks.order_ready("406") is True  # no ok_hour gate: night is fine too
    ev = bot_events.one("finance.ready_card")
    assert ev["bonus"]["order_ref"] == "406" and ev["to"] == [300]
    assert OrderBonus.objects.filter(order_ref="406").count() == 1
    assert ClientFeedback.objects.filter(order_ref="406").exists()
    # neither a second run nor the hourly fallback sends it again
    assert tasks.order_ready("406") is False
    followup.hourly_orders(ok_hour=True)
    assert len(bot_events.of("finance.ready_card")) == 1


def test_order_ready_skips_orders_ready_before_bonus_since(members, site_order, bot_events):
    make_done(site_order)
    config.FIN_BONUS_SINCE = (date.today() + timedelta(days=1)).isoformat()
    assert tasks.order_ready("406") is False
    assert not OrderBonus.objects.exists() and bot_events == []


def test_order_ready_ignores_orders_that_are_not_ready(members, site_order, bot_events):
    config.FIN_BONUS_SINCE = (date.today() - timedelta(days=1)).isoformat()
    assert tasks.order_ready("406") is False
    assert tasks.order_ready("99999") is False
    assert not OrderBonus.objects.exists()


def test_nothing_is_sent_at_night(members, site_order, bot_events):
    make_done(site_order)
    followup.hourly_orders(ok_hour=False)
    assert not OrderBonus.objects.exists() and bot_events == []


def test_zero_rest_asks_to_close_once_and_only_by_day(members, site_order, bot_events):
    make_done(site_order)
    followup.hourly_orders(ok_hour=True)
    site_order.lost_money = site_order.price
    site_order.save()
    followup.bonus_check(
        "406", ok_hour=False
    )  # right after a booking: no question at night/immediately
    assert not bot_events.of("finance.bonus_zero")
    followup.bonus_check("406", ok_hour=True)
    ev = bot_events.one("finance.bonus_zero")
    assert ev["money_state"]["rest"] == "0.00" and ev["percent"] == "0.50" and ev["to"] == [300]
    followup.bonus_check("406", ok_hour=True)
    assert len(bot_events.of("finance.bonus_zero")) == 1


@pytest.mark.parametrize(
    "age,key,label", [(2, "d3", "3 kunlik"), (6, "d7", "7 kunlik"), (29, "d30", "30 kunlik")]
)
def test_term_reminders_come_the_day_before(members, site_order, bot_events, age, key, label):
    make_done(site_order, since_days_ago=age)
    followup.hourly_orders(ok_hour=True)  # opens the bonus
    OrderBonus.objects.update(ready_date=date.today() - timedelta(days=age))
    followup.bonus_check("406", ok_hour=True)
    ev = bot_events.one("finance.bonus_term_reminder")
    assert ev["label"] == label and ev["rest"] == "600.00"
    followup.bonus_check("406", ok_hour=True)
    assert len(bot_events.of("finance.bonus_term_reminder")) == 1
    assert OrderBonus.objects.get().reminders[key]


def test_after_thirty_days_the_bonus_expires_silently(members, site_order, bot_events):
    make_done(site_order, since_days_ago=0)
    followup.hourly_orders(ok_hour=True)
    OrderBonus.objects.update(ready_date=date.today() - timedelta(days=31))
    bot_events.clear()
    followup.bonus_check("406", ok_hour=True)
    bn = OrderBonus.objects.get()
    assert bn.status == "expired" and bn.bonus == 0 and bot_events == []


def test_feedback_is_asked_after_three_days_and_reminded_after_two_more(members, bot_events):
    TelegramMember.objects.filter(telegram_id=300).update(is_feedback=True)
    fb = ClientFeedback.objects.create(
        order_ref="406", client="Nazira", ready_date=date.today() - timedelta(days=2)
    )
    followup.feedback_check(ok_hour=True)
    assert not bot_events.of("finance.feedback_ask")  # only 2 days
    ClientFeedback.objects.filter(pk=fb.pk).update(ready_date=date.today() - timedelta(days=3))
    followup.feedback_check(ok_hour=False)
    assert not bot_events.of("finance.feedback_ask")
    followup.feedback_check(ok_hour=True)
    ask = bot_events.one("finance.feedback_ask")
    assert ask["to"] == [300] and ask["fallback"] is False and ask["feedback"]["status"] == "asked"
    ClientFeedback.objects.filter(pk=fb.pk).update(asked_date=date.today() - timedelta(days=2))
    followup.feedback_check(ok_hour=True)
    followup.feedback_check(ok_hour=True)
    assert len(bot_events.of("finance.feedback_remind")) == 1


def test_duty_without_a_holder_falls_back_to_the_admins(members, bot_events):
    ClientFeedback.objects.create(order_ref="406", ready_date=date.today() - timedelta(days=3))
    followup.feedback_check(ok_hour=True)
    ev = bot_events.one("finance.feedback_ask")
    assert (
        ev["to"] == [100]
        and ev["fallback"] is True
        and ev["fallback_who"] == "Mijoz fikri menejeri"
    )


def test_site_entry_reminder_the_day_after(members, bot_events):
    SiteEntryTask.objects.create(code="a", date=date.today(), order_ref="406")
    old = SiteEntryTask.objects.create(
        code="b", date=date.today() - timedelta(days=1), order_ref="389"
    )
    followup.site_entry_remind(ok_hour=True)
    ev = bot_events.one("finance.site_entry_remind")
    assert ev["task"]["code"] == "b" and ev["to"] == [100] and ev["fallback"] is True
    old.refresh_from_db()
    followup.site_entry_remind(ok_hour=True)
    assert len(bot_events.of("finance.site_entry_remind")) == 1


def test_deadline_reminders_once_per_step(members, site_order, bot_events):
    TelegramMember.objects.filter(telegram_id=200).update(is_deadline_receiver=True)
    site_order.end_date = date.today() + timedelta(days=3)
    site_order.save()
    infos = S.open_orders(["jarayonda"])
    followup.deadline_reminders(infos)
    ev = bot_events.one("finance.deadline")
    assert (
        ev["key"] == "3" and ev["left_days"] == 3 and set(ev["to"]) == {200, 300}
    )  # + bonus receiver
    assert ev["order"]["ref"] == "406" and ev["order"]["address"] == "Chilonzor"
    followup.deadline_reminders(infos)
    assert len(bot_events.of("finance.deadline")) == 1
    site_order.end_date = date.today() + timedelta(days=1)
    site_order.save()
    followup.deadline_reminders(S.open_orders(["jarayonda"]))
    last = bot_events.of("finance.deadline")[-1]
    assert last["key"] == "1" and last["to"] == [200] and last["fallback_who"] == E.WHO_DEADLINE
