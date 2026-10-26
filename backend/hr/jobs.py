"""Every-minute davomat schedule (runSchedule_ in davomat.txt). Called by the
scheduler process (manage.py finance_scheduler runs both bots' jobs)."""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta

from . import reports as R
from . import services as S
from .constants import ETA_GRACE_MIN, MAX_ASKS, TXT, UZ_HOLIDAYS
from .models import Holiday, HolidayDecision
from .telegram import dm, esc, eta_kb, ism, kb, notify_admins, send, site_url

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
        dd = d.isoformat()
        notify_admins(
            f"🎉 <b>{S.fmt_day(d)}</b> — {esc(name)}.\nDam olinadimi? Necha kun?",
            kb(
                [
                    [("Yo'q, ishlaymiz", f"hol:{dd}:0")],
                    [("1 kun", f"hol:{dd}:1"), ("2 kun", f"hol:{dd}:2"), ("3 kun", f"hol:{dd}:3")],
                    [("✏️ Boshqa (yozaman)", f"hol:{dd}:x")],
                ]
            ),
        )
        asked.append(d)
    return asked


def run_schedule(now_d: datetime | None = None) -> list[str]:
    now_d = now_d or S.now()
    day, nm, grace = now_d.date(), S.mod(now_d), S.setting_int("GRACE_MIN")
    done: list[str] = []

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
            t = (
                f"☀️ <b>Xayrli tong, jamoa!</b>\n\n{random.choice(TXT['morning'])}\n\n⏰ "
                + (
                    f"Ish soat <b>{S.hm_str(starts[0])}</b> da boshlanadi. "
                    if len(starts) == 1
                    else "Ish boshlanishi: "
                    + " / ".join(f"<b>{S.hm_str(x)}</b>" for x in starts)
                    + " (har kimning o'z vaqti). "
                )
                + "Kelganingizda shu yerga <b>video-doiracha</b> tashlang."
            )
            if S.setting_bool("UNIFORM_CHECK"):
                t += "\n" + random.choice(TXT["uniform"])
            send(g.chat_id, t)

    rows_now = S.compute_day(day, now_d)

    # 2) ask privately who hasn't reported after their own start
    miss_now = []
    for r in rows_now:
        if r.st != "waiting":
            continue
        st = S.emp_start(r.e)
        if not in_win(nm, st + grace + 1, 90) or not once(f"ask_{r.e.telegram_id}"):
            continue
        miss_now.append(r)
        if dm(
            r.e,
            f"Assalomu alaykum, {ism(r.e)}! 👋\nIsh soat {S.hm_str(st)} da boshlandi, guruhda hali video-doirachangizni ko'rmadim. Hammasi joyidami?\n"
            "Ishga qancha vaqtda yetib kelasiz? Tugmani bosing yoki yozing (masalan: <i>20 daqiqa</i> yoki <i>10:30</i>).",
            eta_kb(day),
        ):
            r.a = S.set_att(day, r.e, asked=(r.g("asked") or 0) + 1)
    if miss_now and S.setting_bool("GROUP_LIST_MISSING"):
        for g in S.groups():
            names = [
                esc("@" + r.e.username if r.e.username else r.e.name)
                for r in miss_now
                if r.e.group_id == g.id
            ]
            if names:
                send(g.chat_id, "⏰ Ish boshlandi. Hali otchet tashlamaganlar: " + ", ".join(names))

    # 4) ask again
    rep = S.setting_int("REPEAT_ASK_MIN")
    if rep > grace:
        for r in rows_now:
            if r.st != "waiting" or r.g("eta") or (r.g("asked") or 0) >= MAX_ASKS:
                continue
            if not in_win(nm, S.emp_start(r.e) + rep, 90) or not once(f"rep_{r.e.telegram_id}"):
                continue
            if dm(
                r.e,
                f"{ism(r.e)}, hali ham video-doirachangizni ko'rmadim. 🤔\nHammasi joyidami? Qancha vaqtda yetib kelasiz?",
                eta_kb(day),
            ):
                r.a = S.set_att(day, r.e, asked=(r.g("asked") or 0) + 1)

    # 4b) work is over, no leaving report
    for r in rows_now:
        if not r.g("in_time") or r.g("out_time"):
            continue
        end = S.parse_hm(r.a.work_end) if r.a.work_end else S.emp_end(r.e)
        if not in_win(nm, end + S.setting_int("OUT_REMIND_MIN"), 120) or not once(
            f"outrem_{r.e.telegram_id}"
        ):
            continue
        dm(
            r.e,
            f"{ism(r.e)}, ish kuningiz yakunlandi, rahmat! 🙏\nKetayotganingizda guruhga <b>video-doiracha</b> tashlashni unutmang, ketish vaqtingiz shunda qayd etiladi. 🙂",
        )

    # 5) the time they promised has passed
    for r in S.compute_day(day, now_d):
        if r.st != "waiting" or not r.g("eta") or r.g("eta_sent"):
            continue
        if nm < S.parse_hm(r.a.eta) + ETA_GRACE_MIN:
            continue
        S.set_att(day, r.e, eta_sent=True)
        if (r.g("asked") or 0) >= MAX_ASKS:
            continue
        if dm(
            r.e,
            f"{ism(r.e)}, siz soat {S.hm(r.a.eta)} da yetib kelaman degan edingiz, lekin guruhda video-doiracha hali yo'q. ⏳\n"
            "Yetib kelgan bo'lsangiz guruhga tashlang. Yana qancha vaqt kerak?",
            eta_kb(day),
        ):
            S.set_att(day, r.e, asked=(r.g("asked") or 0) + 1)
            done.append(f"eta:{r.e.telegram_id}")

    # 6) daily report (11:30)
    if in_win(nm, S.parse_hm(S.setting("REPORT_TIME")) or 690, 180) and once("report"):
        rows = S.compute_day(day, now_d)
        if expected or any(r.g("in_time") for r in rows):
            notify_admins(R.day_report(day, now_d, f"📊 Kunlik hisobot ({S.hm_str(nm)})"))

    # 7) last day of the month: month report, «Oy xodimi» (and «Yil xodimi» on 31.12)
    if (
        (day + timedelta(days=1)).month != day.month
        and nm >= (S.parse_hm(S.setting("MONTH_REPORT_TIME")) or 1140)
        and once("month")
    ):
        ym = day.strftime("%Y-%m")
        notify_admins(
            R.period_report(day.replace(day=1), day, now_d, f"🗓 Oylik hisobot ({ym})")
            + f"\n\n🌐 To'liq jadval saytda: {site_url()}"
        )
        text, k = R.month_winner_msg(ym, now_d)
        notify_admins(text, k)
        if day.month == 12 and day.day == 31:
            text, k = R.year_report(str(day.year), now_d)
            notify_admins(text, k)

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
