"""Scheduled jobs of the finance bot (hourly()/hourlyBody_ in code.txt).

run_due() is called every minute by `manage.py finance_scheduler`; every job is
guarded by a FinanceJobRun key, so a restart or a second scheduler never sends a
reminder twice.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from constance import config

from . import services as S
from .finance.excel import month_xlsx
from .finance.text import (
    add_months,
    cur_month,
    esc,
    money,
    month_bounds,
    month_full,
    now,
    num,
    today,
)
from .finance_models import FinanceJobRun, MonthReport, ProcessedUpdate
from .telegram import api
from .telegram.api import b, ik
from .telegram.bonus import hourly_orders
from .telegram.notify import to_admins
from .telegram.texts import KB_STAFF

log = logging.getLogger("finance.jobs")


def _safe(name, fn, *args):
    try:
        fn(*args)
    except Exception:  # noqa: BLE001 — one failing job must not stop the others
        log.exception("job %s failed", name)


def daily_reminder():
    """19:00 — staff who wrote nothing today get «did you enter today's costs?»."""
    t = today()
    wrote = set(S.period_ops(t, t).values_list("author_id", flat=True))
    for s in S.staff():
        if s.id in wrote:
            continue
        api.send(
            s.telegram_id,
            f"📝 <b>{esc(s.name)}</b>, bugungi kirim-chiqimlarni kiritdingizmi?\n💳 Hamyonda: {money(S.balance(s))}",
            ik([[b("➖ Chiqim kiritish", "go:chiqim")], [b("✅ Bugun xarajat bo'lmadi", "noexp")]]),
        )


def month_job():
    """10:00 — month end: «submit your report»; first days: who hasn't submitted."""
    t, ym = today(), cur_month()
    _, end = month_bounds(ym)
    left = (end - t).days
    if left < int(config.FIN_MONTH_END_DAYS or 3):
        when = "bugun oyning oxirgi kuni" if left == 0 else f"oy tugashiga {left + 1} kun qoldi"
        done = set(MonthReport.objects.filter(month=ym).values_list("member_id", flat=True))
        for s in S.staff():
            if s.id in done:
                continue
            api.send(
                s.telegram_id,
                f"📅 <b>Diqqat: {when}!</b>\n\n1) Barcha kirim-chiqimlarni kiriting\n2) «📤 Oylik hisob» tugmasi orqali hisobni topshiring\n\n💳 Hamyonda: {money(S.balance(s))}",
                KB_STAFF,
            )
    if t.day <= 3:
        pm = add_months(ym, -1)
        ps, pe = month_bounds(pm)
        done = set(MonthReport.objects.filter(month=pm).values_list("member_id", flat=True))
        late = [s for s in S.staff() if s.id not in done and S.period_ops(ps, pe, s).exists()]
        for s in late:
            api.send(
                s.telegram_id,
                f"⏰ <b>{month_full(pm)} hisobi hali topshirilmagan!</b>\n«📤 Oylik hisob» tugmasini bosing.",
                KB_STAFF,
            )
        if late and t.day == 3:
            to_admins(
                f"⏰ {month_full(pm)} hisobini topshirmaganlar:\n"
                + "\n".join(f"• {esc(s.name)}" for s in late)
            )


def admin_daily():
    """21:00 — the day's summary to the admins; on the 1st also last month's Excel."""
    t = today()
    rows = list(S.period_ops(t, t))
    sm = S.summary(t, t)
    lines = [
        f"🌙 <b>Kun yakuni · {t:%d.%m.%Y}</b>",
        "",
        f"🔴 Xarajat: <b>{num(-sm['expense'])}</b>",
        f"🟢 Daromad: <b>{num(sm['income'])}</b>",
        f"💸 Xodimlarga berildi: {num(sm['given_to_staff'])}",
        f"📝 Amallar: {len(rows)}",
    ]
    if sm["boss_personal"]:
        lines.append(f"👔 Rahbar xarajatlari (alohida): {num(sm['boss_personal'])}")
    if sm["home"]:
        lines.append(f"🏠 Uy uchun (alohida): {num(sm['home'])}")
    by: dict[str, S.Decimal] = {}
    for x in rows:
        if S.is_company_expense(x):
            by[x.member.name] = by.get(x.member.name, S.ZERO) + x.amount
    if by:
        lines += ["", "<b>Kim qancha sarfladi:</b>"] + [
            f"• {esc(k)} — {num(v)}" for k, v in by.items()
        ]
    wrote = {x.author_id for x in rows}
    silent = [s for s in S.staff() if s.id not in wrote]
    if silent:
        lines += ["", "😶 Bugun yozmaganlar: " + ", ".join(esc(s.name) for s in silent)]
    issues = S.checks()
    high = sum(1 for i in issues if i["level"] == "h")
    if issues:
        lines += [
            "",
            f"🔍 Tekshiruv: {len(issues)} ta kamchilik"
            + (f", 🔴 {high} ta jiddiy" if high else "")
            + " — «🔍 Tekshiruv» tugmasi",
        ]
    to_admins("\n".join(lines), ik([[b("📊 Oy ma'lumoti", f"inf:all:{cur_month()}:x")]]))
    if t.day == 1:
        pm = add_months(cur_month(), -1)
        content, name = month_xlsx(pm)
        for a in S.admins():
            api.send_document(a.telegram_id, content, name, f"📥 {month_full(pm)} — oylik hisobot")


def replay_updates():
    """Updates the webhook accepted but a restart interrupted (outbox in
    ProcessedUpdate): run them again, at most 3 tries each."""
    from .telegram.router import run_recorded

    stale = now() - timedelta(minutes=2)
    for pu in ProcessedUpdate.objects.filter(
        done=False, created_at__lt=stale, attempts__lt=3
    ).order_by("update_id")[:50]:
        if pu.payload:
            _safe("replay", run_recorded, pu.payload)
        else:
            ProcessedUpdate.objects.filter(pk=pu.pk).update(done=True)


def cleanup():
    ProcessedUpdate.objects.filter(created_at__lt=now() - timedelta(days=3)).delete()
    FinanceJobRun.objects.filter(created_at__lt=now() - timedelta(days=150)).delete()


def run_due(at=None):
    """Run whatever is due at this minute. Returns the list of jobs started."""
    at = at or now()
    day, h = at.date().isoformat(), at.hour
    ran = []

    def once(key, fn):
        if S.once(f"job:{key}:{day}"):
            ran.append(key)
            _safe(key, fn)

    if h == int(config.FIN_REMINDER_HOUR or 19):
        once("daily", daily_reminder)
    if h == int(config.FIN_ADMIN_REPORT_HOUR or 21):
        once("admin", admin_daily)
    if h == 10:
        once("month", month_job)
    # order follow-up (deadlines, Готов sheets, bonus, feedback) — every hour;
    # messages only in the daytime, like the Apps Script (9:00–21:00)
    if S.once(f"job:orders:{day}:{h}"):
        ran.append("orders")
        _safe("orders", hourly_orders, 9 <= h <= 21)
    once("cleanup", cleanup)
    _safe("replay", replay_updates)
    # davomat (HR) keeps its own once-per-day markers; it only shares the process
    from hr.jobs import tick as hr_tick

    if hr_tick():
        ran.append("hr")
    return ran
