"""Scheduled jobs of the finance section (hourly()/hourlyBody_ in code.txt).

Run by celery beat through accounting/tasks.py; each task is guarded by a
FinanceJobRun key, so a beat restart or a duplicate delivery never sends a reminder
twice. The jobs decide WHO is told WHAT (data); the bot service renders the messages
(events: accounting/events.py).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from constance import config

from . import events as E
from . import services as S
from .models import FinanceJobRun, MonthReport
from .text import add_months, cur_month, month_bounds, now, today

log = logging.getLogger("finance.jobs")


def daily_reminder():
    """19:00 - staff who wrote nothing today get «did you enter today's costs?»."""
    t = today()
    wrote = set(S.period_ops(t, t).values_list("author_id", flat=True))
    for s in S.staff():
        if s.id in wrote:
            continue
        E.daily_reminder(s)


def month_job():
    """10:00 - month end: «submit your report»; first days: who hasn't submitted."""
    t, ym = today(), cur_month()
    _, end = month_bounds(ym)
    left = (end - t).days
    if left < int(config.FIN_MONTH_END_DAYS or 3):
        done = set(MonthReport.objects.filter(month=ym).values_list("member_id", flat=True))
        for s in S.staff():
            if s.id in done:
                continue
            E.month_end_reminder(s, left)
    if t.day <= 3:
        pm = add_months(ym, -1)
        ps, pe = month_bounds(pm)
        done = set(MonthReport.objects.filter(month=pm).values_list("member_id", flat=True))
        late = [s for s in S.staff() if s.id not in done and S.period_ops(ps, pe, s).exists()]
        for s in late:
            E.month_late(s, pm)
        if late and t.day == 3:
            E.month_late_admins(pm, [s.name for s in late])


def admin_daily():
    """21:00 - the day's summary to the admins; on the 1st also last month's Excel."""
    t = today()
    rows = list(S.period_ops(t, t))
    sm = S.summary(t, t)
    by: dict[str, S.Decimal] = {}
    for x in rows:
        if S.is_company_expense(x):
            by[x.member.name] = by.get(x.member.name, S.ZERO) + x.amount
    wrote = {x.author_id for x in rows}
    silent = [s.name for s in S.staff() if s.id not in wrote]
    E.admin_daily(t, sm, rows, by, silent, S.checks())
    if t.day == 1:
        E.month_excel(add_months(cur_month(), -1))


def cleanup():
    FinanceJobRun.objects.filter(created_at__lt=now() - timedelta(days=150)).delete()
