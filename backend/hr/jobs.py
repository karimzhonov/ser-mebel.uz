"""Davomat schedule (runSchedule_ in davomat.txt), run every minute by celery beat
(hr/tasks.py).

The schedule decides WHO is told WHAT and WHEN; the Telegram bot renders and sends
(events: hr/events.py). Steps that need to know whether the person was reached
(2, 4, 4b, 5) send synchronously and count an ask only on a confirmed delivery. If the
bot is down the tick stops sending and un-marks the once-per-day keys, so the next
tick (the windows last 90+ minutes) tries again.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from core.bot_notify import BotUnavailable

from . import events as E
from . import report_data as RD
from . import services as S
from .constants import ETA_GRACE_MIN, MAX_ASKS, UZ_HOLIDAYS
from .models import Holiday, HolidayDecision

log = logging.getLogger("hr.jobs")


def in_win(now_min: int, at: int, length: int) -> bool:
    return at <= now_min < at + length


def upcoming_holidays(day, ahead: int):
    out = []
    for i in range(1, ahead + 1):
        d = day + timedelta(days=i)
        for k, name in UZ_HOLIDAYS:
            if k == d.isoformat() or k == d.strftime("%m-%d"):
                out.append((d, name))
    return out


def ask_holidays(day) -> list:
    asked = []
    for d, name in upcoming_holidays(day, S.setting_int("HOLIDAY_ASK_DAYS")):
        if (
            HolidayDecision.objects.filter(holiday_day=d).exists()
            or Holiday.objects.filter(day=d).exists()
        ):
            continue
        if not S.fire_once(day, f"hol_{d.isoformat()}"):
            continue
        E.holiday_ask(d, name)
        asked.append(d)
    return asked


class _Sender:
    """Synchronous per-person sends with the circuit breaker."""

    def __init__(self, day):
        self.day = day
        self.down = False

    def deliver(self, once_name: str | None, e, send) -> bool:
        """Run `send()` (an hr.events sync call) for `e`. Returns True when the person was
        reached. Skips people who blocked the bot. On BotUnavailable: stops for the tick
        and releases `once_name` so a later tick retries."""
        if self.down or e.can_dm is False:
            if self.down and once_name:
                S.unfire_once(self.day, once_name)
            return False
        try:
            answer = send()
        except BotUnavailable:
            log.warning("bot unreachable; davomat tick stops sending")
            self.down = True
            if once_name:
                S.unfire_once(self.day, once_name)
            return False
        delivered = answer.get("delivered") or []
        S.record_dm_results(delivered)
        if answer.get("duplicate"):  # an earlier try got through (timed out on our side)
            return True
        return bool(answer.get("ok")) and any(d.get("ok") for d in delivered)


def run_schedule(now_d: datetime | None = None) -> list[str]:
    now_d = now_d or S.now()
    day, nm, grace = now_d.date(), S.mod(now_d), S.setting_int("GRACE_MIN")
    done: list[str] = []
    sender = _Sender(day)

    def once(name):
        ok = S.fire_once(day, name)
        if ok:
            done.append(name)
        return ok

    # new day: freeze the previous day(s) (kelmaganlar «Kelmadi» bo'ladi)
    cur = S.state("CURDAY")
    if cur != day.isoformat():
        S.finalize_pending(day)
        S.set_state("CURDAY", day.isoformat())
        if cur:
            done.append(f"finalize:{cur}")

    # who is expected today, from one computation of the day (not a query per person)
    expected = [
        r.e
        for r in S.compute_day(day, now_d)
        if r.e.is_active
        and r.st in ("on_time", "late", "waiting", "absent", "excused", "noin")
        and S.iso_wd(day) not in S.emp_off_days(r.e)
    ]

    # 1) morning reminder in every group, before its earliest start
    if S.setting_bool("GROUP_REMIND") and expected:
        any_g = any(e.group_id for e in expected)
        for g in S.groups():
            ge = [e for e in expected if e.group_id == g.id] if any_g else expected
            if not ge:
                continue
            starts = sorted({S.emp_start(e) for e in ge})
            if not in_win(nm, starts[0] - S.setting_int("REMIND_BEFORE_MIN"), 30) or not once(
                f"morning_{g.chat_id}"
            ):
                continue
            E.morning(g.chat_id, starts)

    rows_now = S.compute_day(day, now_d)

    # 2) ask privately who hasn't reported after their own start
    miss_now = []
    for r in rows_now:
        if r.st != "waiting":
            continue
        st = S.emp_start(r.e)
        name = f"ask_{r.e.telegram_id}"
        if not in_win(nm, st + grace + 1, 90) or not once(name):
            continue
        miss_now.append(r)
        if sender.deliver(name, r.e, lambda r=r, st=st: E.ask_eta(r.e, st, day, repeat=False)):
            r.a = S.set_att(day, r.e, asked=(r.g("asked") or 0) + 1)
    if miss_now and S.setting_bool("GROUP_LIST_MISSING") and not sender.down:
        for g in S.groups():
            names = [
                ("@" + r.e.username) if r.e.username else r.e.name
                for r in miss_now
                if r.e.group_id == g.id
            ]
            if names:
                E.missing_list(g.chat_id, names)

    # 4) ask again
    rep = S.setting_int("REPEAT_ASK_MIN")
    if rep > grace:
        for r in rows_now:
            if r.st != "waiting" or r.g("eta") or (r.g("asked") or 0) >= MAX_ASKS:
                continue
            name = f"rep_{r.e.telegram_id}"
            if not in_win(nm, S.emp_start(r.e) + rep, 90) or not once(name):
                continue
            if sender.deliver(
                name, r.e, lambda r=r: E.ask_eta(r.e, S.emp_start(r.e), day, repeat=True)
            ):
                r.a = S.set_att(day, r.e, asked=(r.g("asked") or 0) + 1)

    # 4b) work is over, no leaving report
    for r in rows_now:
        if not r.g("in_time") or r.g("out_time"):
            continue
        end = S.parse_hm(r.a.work_end) if r.a.work_end else S.emp_end(r.e)
        name = f"outrem_{r.e.telegram_id}"
        if not in_win(nm, end + S.setting_int("OUT_REMIND_MIN"), 120) or not once(name):
            continue
        sender.deliver(name, r.e, lambda r=r: E.out_reminder(r.e, day))

    # 5) the time they promised has passed
    for r in S.compute_day(day, now_d):
        if r.st != "waiting" or not r.g("eta") or r.g("eta_sent"):
            continue
        if nm < S.parse_hm(r.a.eta) + ETA_GRACE_MIN:
            continue
        S.set_att(day, r.e, eta_sent=True)
        if (r.g("asked") or 0) >= MAX_ASKS:
            continue
        if sender.down:
            S.set_att(day, r.e, eta_sent=False)  # try again on a later tick
            continue
        eta_hm = S.hm(r.a.eta)
        if sender.deliver(None, r.e, lambda r=r, eta_hm=eta_hm: E.eta_passed(r.e, eta_hm, day)):
            S.set_att(day, r.e, asked=(r.g("asked") or 0) + 1)
            done.append(f"eta:{r.e.telegram_id}")
        elif sender.down:
            S.set_att(day, r.e, eta_sent=False)

    # 6) daily report (11:30)
    if in_win(nm, S.parse_hm(S.setting("REPORT_TIME")) or 690, 180) and once("report"):
        rows = S.compute_day(day, now_d)
        if expected or any(r.g("in_time") for r in rows):
            E.day_report(S.hm_str(nm), RD.day_report_data(day, now_d))

    # 7) last day of the month: month report, «Oy xodimi» (and «Yil xodimi» on 31.12)
    if (
        (day + timedelta(days=1)).month != day.month
        and nm >= (S.parse_hm(S.setting("MONTH_REPORT_TIME")) or 1140)
        and once("month")
    ):
        ym = day.strftime("%Y-%m")
        E.month_report(ym, RD.period_report_data(day.replace(day=1), day, now_d))
        rows_m = S.ranking_rows(ym, only_active=True)
        if rows_m:
            E.winner_pick("m", ym, rows_m)
        if day.month == 12 and day.day == 31:
            rows_y = S.ranking_rows(year=str(day.year))
            if rows_y:
                E.winner_pick("y", str(day.year), rows_y)

    # 8) ask about upcoming holidays
    if nm >= 600:
        done += [f"holask:{d}" for d in ask_holidays(day)]
    return done


def tick():
    """Entry point for the scheduler loop (every minute)."""
    try:
        return run_schedule()
    except Exception:  # noqa: BLE001
        log.exception("davomat tick failed")
        return []
