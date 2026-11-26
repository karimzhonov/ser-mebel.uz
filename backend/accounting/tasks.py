"""Celery tasks of Moliya. Schedules: accounting/schedule.py (celery beat, DB)."""

from celery import shared_task

from . import followup, jobs
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
    followup.hourly_orders(9 <= at.hour <= 21)
    return True


@shared_task(bind=True, max_retries=3, default_retry_delay=20)
def order_ready(self, ref: str):
    """An order just became Готов: the payment sheet goes now (hourly_orders is the
    fallback). Queued by accounting/signals.py. The result says why a card was or
    wasn't sent; only a not-yet-visible status history is worth retrying."""
    res = followup.order_ready(ref)
    if res == followup.READY_NO_DATE and self.request.retries < self.max_retries:
        raise self.retry()
    return res


@shared_task
def salary_reminder():
    """The day before a worker's pay day: remind the accountant (accounting/salary.py).
    Runs hourly 10:00–20:00; salary.remind sends each worker + pay date once."""
    from . import salary

    return salary.remind()


@shared_task
def cleanup():
    jobs.cleanup()


@shared_task
def assign_overheads():
    """Stage 3: fix the overhead share of every order that became Готов (from
    FIN_OVERHEAD_SINCE) and has none yet. Idempotent — a share is written once
    (OrderOverhead.order_ref is unique), so a redelivered or doubled run adds nothing."""
    from . import overhead

    return overhead.assign_pending()
