"""Celery tasks of Moliya. Schedules: accounting/schedule.py (celery beat, DB)."""

from celery import shared_task

from . import jobs
from . import services as S
from .text import now


def _once_today(name: str, fn, *args) -> bool:
    """Run `fn` at most once per day for `name` (FinanceJobRun guard)."""
    if not S.once(f"job:{name}:{now().date().isoformat()}"):
        return False
    fn(*args)
    return True


@shared_task
def daily_reminder():
    return _once_today("daily", jobs.daily_reminder)


@shared_task
def admin_daily():
    return _once_today("admin", jobs.admin_daily)


@shared_task
def month_job():
    return _once_today("month", jobs.month_job)


@shared_task
def hourly_orders():
    """Order follow-up (deadlines, Готов sheets, bonus, feedback) every hour;
    messages only in the daytime (9:00–21:00), like the Apps Script."""
    at = now()
    if not S.once(f"job:orders:{at.date().isoformat()}:{at.hour}"):
        return False
    jobs.hourly_orders(9 <= at.hour <= 21)
    return True


@shared_task
def cleanup():
    jobs.cleanup()


@shared_task
def replay_updates():
    jobs.replay_updates()
