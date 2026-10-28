"""Davomat (attendance) rules — the source of truth for the bot and the site.
Port of davomat.txt; function names in docstrings point to the original.

The Telegram bot (bot/ service) calls these through api/views/bot/hr.py; the
`process_*` functions decide what happened and return data, never message text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Max

from core.exceptions import ServiceConflict, ServiceError

from .constants import (
    ACK_MODES,
    BOOL_KEYS,
    CHECKIN_MODES,
    DEFAULTS,
    LABELS,
    MONTHS,
    PTS,
    REASONS,
    TIME_KEYS,
    UZ_HOLIDAYS,
    WEEKDAYS,
)
from .models import (
    Attendance,
    Employee,
    Holiday,
    HrSetting,
    HrState,
    Leave,
    PointAdjustment,
    Winner,
    WorkGroup,
)

TZ = ZoneInfo("Asia/Tashkent")


# =================================================================== time helpers
def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def from_unix(sec: int) -> datetime:
    return datetime.fromtimestamp(int(sec), TZ).replace(tzinfo=None)


def mod(d: datetime) -> int:
    return d.hour * 60 + d.minute


def parse_hm(s) -> int | None:
    if isinstance(s, time):
        return s.hour * 60 + s.minute
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", str(s or "").strip())
    if not m:
        return None
    h, mi = int(m[1]), int(m[2])
    return h * 60 + mi if h <= 23 and mi <= 59 else None


def hm_str(minutes: int) -> str:
    minutes = ((int(minutes) % 1440) + 1440) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def hm(t: time | None) -> str:
    return t.strftime("%H:%M") if t else ""


def to_time(minutes: int) -> time:
    s = hm_str(minutes)
    return time(int(s[:2]), int(s[3:]))


def fmt_min(m) -> str:
    m = round(m or 0)
    if m < 60:
        return f"{m} daq"
    h, r = divmod(m, 60)
    return f"{h} soat {r} daq" if r else f"{h} soat"


def iso_wd(d: date) -> int:
    return d.isoweekday()


def fmt_day(d: date) -> str:
    return f"{d.day}-{MONTHS[d.month - 1]}, {WEEKDAYS[d.isoweekday() - 1]}"


def month_name(ym: str) -> str:
    return f"{MONTHS[int(ym[5:7]) - 1]} {ym[:4]}"


def last_day_of_month(ym: str) -> date:
    y, m = int(ym[:4]), int(ym[5:7])
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return nxt - timedelta(days=1)


def parse_days(s) -> list[int]:
    out = []
    for p in re.sub(r"\s", "", str(s or "")).split(","):
        if p.isdigit() and 1 <= int(p) <= 7 and int(p) not in out:
            out.append(int(p))
    return sorted(out)


def days_label(arr) -> str:
    return ", ".join(WEEKDAYS[d - 1] for d in arr) if arr else "yo'q"


def parse_date(s: str, today: date) -> date | None:
    s = str(s or "").strip().lower()
    if s == "bugun":
        return today
    if s == "ertaga":
        return today + timedelta(days=1)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return date.fromisoformat(s)
        m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", s)
        if m:
            y = int(m[3]) if m[3] else today.year
            if y < 100:
                y += 2000
            return date(y, int(m[2]), int(m[1]))
    except ValueError:
        return None
    return None


# =================================================================== settings & state
_SETTINGS = {"at": 0.0, "values": None}


def _settings() -> dict:
    """All settings, cached for a few seconds: setting() is called per employee in
    every minute's schedule."""
    import time as _time

    if _SETTINGS["values"] is None or _time.monotonic() - _SETTINGS["at"] > 5:
        stored = dict(HrSetting.objects.values_list("key", "value"))
        _SETTINGS["values"] = {k: stored.get(k, v) for k, v in DEFAULTS.items()}
        _SETTINGS["at"] = _time.monotonic()
    return _SETTINGS["values"]


def clear_settings_cache():
    _SETTINGS["values"] = None


def setting(k: str) -> str:
    return _settings().get(k, DEFAULTS[k])


def setting_int(k: str) -> int:
    try:
        return int(setting(k))
    except (TypeError, ValueError):
        return int(DEFAULTS[k])


def setting_bool(k: str) -> bool:
    return str(setting(k)).lower() in ("1", "ha", "yes", "on", "true")


def all_settings() -> dict:
    return dict(_settings())


def set_setting(k: str, v) -> str:
    """setSetting_: validate and store; returns the stored value."""
    if k not in DEFAULTS:
        raise ServiceError("Noma'lum sozlama.")
    v = str(v).strip()
    val = v
    if k in TIME_KEYS:
        m = parse_hm(v)
        if m is None:
            raise ServiceError("Noto'g'ri qiymat: vaqt formati 09:00")
        val = hm_str(m)
    elif k.endswith("_MIN") or k in ("HOLIDAY_ASK_DAYS", "OUT_MIN_GAP"):
        if not v.isdigit() or int(v) > 1440:
            raise ServiceError("Noto'g'ri qiymat: 0..1440 oralig'ida son")
        val = str(int(v))
    elif k == "OFF_DAYS":
        val = ",".join(str(d) for d in parse_days(v))
    elif k == "CHECKIN_MODE" and v not in CHECKIN_MODES:
        raise ServiceError("Noto'g'ri qiymat: " + " | ".join(CHECKIN_MODES))
    elif k == "GROUP_ACK" and v not in ACK_MODES:
        raise ServiceError("Noto'g'ri qiymat: " + " | ".join(ACK_MODES))
    elif k in BOOL_KEYS:
        val = "1" if v.lower() in ("1", "ha", "yes", "on", "true") else "0"
    HrSetting.objects.update_or_create(key=k, defaults={"value": val})
    _SETTINGS["values"] = None
    return val


def label(k: str) -> str:
    return LABELS.get(k, k)


def state(k: str) -> str | None:
    row = HrState.objects.filter(key=k).first()
    return row.value if row else None


def set_state(k: str, v: str | None):
    if v is None:
        HrState.objects.filter(key=k).delete()
    else:
        HrState.objects.update_or_create(key=k, defaults={"value": str(v)})


def fire_once(day: date, name: str) -> bool:
    """fireOnce_: True only the first time for this day+name."""
    try:
        with transaction.atomic():
            HrState.objects.create(key=f"f_{day.isoformat()}_{name}"[:191], value="1")
        return True
    except IntegrityError:
        return False


def unfire_once(day: date, name: str) -> None:
    """Release a fire_once key (a send that never happened must be retried)."""
    HrState.objects.filter(key=f"f_{day.isoformat()}_{name}"[:191]).delete()


def since() -> date | None:
    v = state("SINCE")
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


def start_min() -> int:
    return parse_hm(setting("WORK_START")) or 540


def end_min() -> int:
    return parse_hm(setting("WORK_END")) or 1080


# =================================================================== people
def admin_ids() -> list[int]:
    """Admins are the finance bot's admins (adminIds_)."""
    from accounting.services import admins

    return [a.telegram_id for a in admins()]


def is_admin(tg_id) -> bool:
    return int(tg_id) in admin_ids()


def finance_member(tg_id):
    from accounting.services import member_by_tg

    return member_by_tg(tg_id)


def emp(tg_id) -> Employee | None:
    try:
        return Employee.objects.select_related("group").get(telegram_id=int(tg_id))
    except (Employee.DoesNotExist, TypeError, ValueError):
        return None


def all_emps():
    return list(Employee.objects.select_related("group").order_by("-is_active", "name"))


def active_emps():
    return list(Employee.objects.select_related("group").filter(is_active=True).order_by("name"))


def upsert_emp(user: dict, group: WorkGroup | None = None) -> tuple[Employee, bool]:
    """upsertEmp_: anyone who writes in a watched group becomes an employee."""
    name = (
        " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x)
        or user.get("username")
        or str(user["id"])
    )
    e = emp(user["id"])
    if e:
        e.name, e.username, e.is_active = name[:255], (user.get("username") or "")[:255], True
        if group:
            e.group = group
        e.save()
        return e, False
    for _ in range(5):
        try:
            with transaction.atomic():
                num = (Employee.objects.aggregate(m=Max("number"))["m"] or 0) + 1
                e = Employee.objects.create(
                    telegram_id=int(user["id"]),
                    number=num,
                    name=name[:255],
                    username=(user.get("username") or "")[:255],
                    group=group,
                    created_on=now().date(),
                    member=finance_member(user["id"]),
                )
                return e, True
        except IntegrityError:
            existing = emp(user["id"])
            if existing:
                return existing, False
    raise ServiceError("Xodimni saqlab bo'lmadi.")


def find_emp(q) -> Employee | None:
    q = str(q or "").strip().lstrip("#")
    if q.isdigit():
        return Employee.objects.filter(number=int(q)).first()
    q = q.lstrip("@").lower()
    by_u = [e for e in all_emps() if e.username and e.username.lower() == q]
    if by_u:
        return by_u[0]
    by_n = [e for e in all_emps() if q and q in e.name.lower()]
    return by_n[0] if len(by_n) == 1 else None


def emp_start(e: Employee) -> int:
    m = parse_hm(e.work_start) if e and e.work_start else None
    return start_min() if m is None else m


def emp_end(e: Employee) -> int:
    m = parse_hm(e.work_end) if e and e.work_end else None
    return end_min() if m is None else m


def emp_hours(e: Employee) -> str:
    return f"{hm_str(emp_start(e))}–{hm_str(emp_end(e))}"


def emp_off_days(e: Employee) -> list[int]:
    return list(e.off_days) if e.off_days else parse_days(setting("OFF_DAYS"))


def set_hours(e: Employee, ws: str | None, we: str | None):
    if ws and we and parse_hm(we) <= parse_hm(ws):
        raise ServiceError("Ish tugashi boshlanishidan keyin bo'lishi kerak.")
    e.work_start, e.work_end = ws or "", we or ""
    e.save(update_fields=["work_start", "work_end"])


def groups():
    return list(WorkGroup.objects.filter(is_active=True))


def group_by_chat(chat_id) -> WorkGroup | None:
    return WorkGroup.objects.filter(chat_id=int(chat_id), is_active=True).first()


# =================================================================== attendance rows
def att(day: date, e: Employee) -> Attendance | None:
    return Attendance.objects.filter(employee=e, day=day).first()


def set_att(day: date, e: Employee, **fields) -> Attendance:
    """Write only `fields` (the scheduler and the webhook may update the same row at
    the same moment — a full save would undo the other's change). If the day is
    already frozen, its points are recomputed so they match the new facts."""
    with transaction.atomic():
        a, _ = Attendance.objects.select_for_update().get_or_create(employee=e, day=day)
        for k, v in fields.items():
            setattr(a, k, v)
        a.save(update_fields=list(fields) + ["updated_at"])
        if a.finalized:
            _refreeze(a)
    return a


def _refreeze(a: Attendance):
    if not a.in_time and a.out_time and a.status in ("", "absent"):
        a.status = "noin"  # a leaving report after the day was frozen
    a.no_checkin = a.status == "noin"
    r = Row(a.employee, a.status, a, a.note)
    a.points = (
        row_points(r, a.day, datetime.combine(a.day, time(23, 59)), final=True)
        if scored(r)
        else None
    )
    a.save(update_fields=["status", "no_checkin", "points", "updated_at"])


def holiday(day: date) -> str | None:
    h = Holiday.objects.filter(day=day).first()
    return h.name if h else None


def leave_on(day: date, e: Employee) -> str | None:
    lv = Leave.objects.filter(employee=e, date_from__lte=day, date_to__gte=day).first()
    return (lv.reason or "ta'til") if lv else None


def expected_today(e: Employee, day: date) -> bool:
    if holiday(day) or leave_on(day, e):
        return False
    a = att(day, e)
    if a and a.status == "off":
        return False
    return iso_wd(day) not in emp_off_days(e)


@dataclass
class Row:
    e: Employee
    st: str
    a: Attendance | None = None
    note: str = ""
    extra: dict = field(default_factory=dict)

    def g(self, name, default=None):
        return getattr(self.a, name, default) if self.a else default


def compute_day(day: date, now_d: datetime) -> list[Row]:
    """computeDay_: every employee's state on `day` (finalized days as stored)."""
    s = since()
    if s and day < s:
        return []
    deadline = parse_hm(setting("REPORT_TIME")) or 690
    today = now_d.date()
    hol = holiday(day)
    atts = {a.employee_id: a for a in Attendance.objects.filter(day=day).select_related("employee")}
    leaves = {
        lv.employee_id: lv.reason or "ta'til"
        for lv in Leave.objects.filter(date_from__lte=day, date_to__gte=day)
    }
    out = []
    for e in all_emps():
        a = atts.get(e.id)
        if a and a.finalized:
            out.append(Row(e, a.status, a, a.note))
            continue
        if not e.is_active and not (a and (a.in_time or a.out_time)):
            continue
        if e.created_on and day < e.created_on and not a:
            continue
        note = ""
        if a and a.in_time:
            st = a.status
        elif a and a.out_time:
            st = "noin"
        elif hol:
            st, note = "holiday", hol
        elif e.id in leaves:
            st, note = "leave", leaves[e.id]
        elif a and a.status == "off":
            st, note = "off", "tasdiqlangan dam"
        elif iso_wd(day) in emp_off_days(e):
            st = "off"
        elif a and a.status == "absent":
            st = "absent"
        elif a and a.status == "excused":
            st, note = "excused", a.excuse
        elif day < today or mod(now_d) >= deadline:
            st = "absent"
        else:
            st = "waiting"
        out.append(Row(e, st, a, note))
    return out


def points_of(r: dict, done: bool) -> int:
    """pointsOf_"""
    p = 0
    st = r.get("st")
    if st == "on_time":
        p += PTS["ON_TIME"]
        if r.get("in") is not None and r.get("start") is not None and r["in"] <= r["start"] - 10:
            p += PTS["EARLY_BIRD"]
    elif st == "late":
        p += PTS["LATE_REASON"] if r.get("lr") == "Sababli" else PTS["LATE_NO_REASON"]
    elif st == "absent":
        p += PTS["ABSENT"]
    elif st == "noin":
        p += PTS["NO_IN"]
    if r.get("in") is not None:
        if r.get("uni") is True:
            p += PTS["UNIFORM_YES"]
        elif r.get("uni") is False:
            p += PTS["UNIFORM_NO"]
        if r.get("out") is not None:
            if (r.get("early") or 0) > 0:
                p += PTS["LEFT_EARLY_REASON"] if r.get("er") == "Sababli" else PTS["LEFT_EARLY"]
            else:
                p += PTS["LEFT_OK"]
        elif done:
            p += PTS["NO_OUT"]
    return p


def scored(row: Row) -> bool:
    return row.st in ("on_time", "late", "absent", "noin") or bool(row.g("in_time"))


def row_points(row: Row, day: date, now_d: datetime, final: bool = False) -> int:
    """rowPoints_: today the «no checkout» penalty waits until 2h after work end;
    a finished day (final) always counts as done, like readSheet_ did."""
    a = row.a
    if a and a.finalized and a.points is not None and not final:
        return a.points
    end = parse_hm(a.work_end) if a and a.work_end else emp_end(row.e)
    done = final or day < now_d.date() or mod(now_d) >= end + 120
    start = parse_hm(a.work_start) if a and a.work_start else emp_start(row.e)
    return points_of(
        {
            "st": row.st,
            "lr": row.g("late_reason"),
            "in": parse_hm(row.g("in_time")) if row.g("in_time") else None,
            "start": start,
            "uni": row.g("uniform"),
            "out": parse_hm(row.g("out_time")) if row.g("out_time") else None,
            "early": row.g("early_min"),
            "er": row.g("early_reason"),
        },
        done,
    )


@transaction.atomic
def finalize_day(day: date):
    """finalizeDay_: freeze the day — absent stays absent even if rules change later."""
    end_of_day = datetime.combine(day, time(23, 59))
    for r in compute_day(day, end_of_day):
        if r.a and r.a.finalized:
            continue
        a, _ = Attendance.objects.select_for_update().get_or_create(employee=r.e, day=day)
        if a.finalized:
            continue
        st = r.st
        if a.in_time and not r.g("in_time"):  # a check-in landed after the snapshot
            st = a.status or "late"
        elif a.out_time and not a.in_time and st != "noin":
            st = "noin"
        r = Row(r.e, st, a, r.note)
        a.status = r.st
        a.note = (r.note or a.note or "")[:255]
        a.points = (
            row_points(Row(r.e, r.st, a, r.note), day, end_of_day, final=True)
            if scored(Row(r.e, r.st, a))
            else None
        )
        a.group_title = r.e.group.title if r.e.group else ""
        if not a.work_start:
            a.work_start, a.work_end = hm_str(emp_start(r.e)), hm_str(emp_end(r.e))
        a.wait = ""
        a.finalized = True
        a.save()


def finalize_pending(today: date):
    """Every unfinished past day (the scheduler may have been down)."""
    days = (
        Attendance.objects.filter(finalized=False, day__lt=today)
        .values_list("day", flat=True)
        .distinct()
    )
    last = state("CURDAY")
    todo = set(days)
    if last:
        try:
            d = date.fromisoformat(last)
            while d < today:
                todo.add(d)
                d += timedelta(days=1)
        except ValueError:
            pass
    for d in sorted(todo):
        finalize_day(d)
    # once-per-day reminder markers older than 3 days are not needed (finalizeDay_)
    HrState.objects.filter(
        key__startswith="f_", created_at__lt=datetime.combine(today - timedelta(days=3), time())
    ).delete()


# =================================================================== statistics
@dataclass
class Stat:
    e: Employee
    exp: int = 0
    on_time: int = 0
    late: int = 0
    late_r: int = 0
    late_min: int = 0
    absent: int = 0
    excused: int = 0
    early_n: int = 0
    viol: int = 0
    worked: int = 0
    pts: int = 0
    adj: int = 0
    bonus: int = 0
    disc: int = 100

    def as_dict(self) -> dict:
        return {
            "employee_id": self.e.id,
            "number": self.e.number,
            "name": self.e.name,
            "expected": self.exp,
            "on_time": self.on_time,
            "late": self.late,
            "late_reasoned": self.late_r,
            "late_min": self.late_min,
            "absent": self.absent,
            "excused": self.excused,
            "left_early": self.early_n,
            "violations": self.viol,
            "worked": self.worked,
            "points": self.pts,
            "adjust": self.adj,
            "bonus": self.bonus,
            "discipline": self.disc,
        }


def period_stats(start: date, end: date, now_d: datetime) -> list[Stat]:
    """periodStats_: finalized rows + today live + admin adjustments + clean-month bonus."""
    today = now_d.date()
    stats: dict[int, Stat] = {}

    def get(e):
        if e.id not in stats:
            stats[e.id] = Stat(e)
        return stats[e.id]

    for e in active_emps():
        get(e)

    def add(e, st, a, pts):
        s = get(e)
        if st in ("on_time", "late", "absent", "excused"):
            s.exp += 1
        if st == "on_time":
            s.on_time += 1
        elif st == "late":
            s.late += 1
            s.late_min += (a.late_min or 0) if a else 0
            if a and a.late_reason == "Sababli":
                s.late_r += 1
            else:
                s.viol += 1
        elif st == "absent":
            s.absent += 1
            s.viol += 1
        elif st == "excused":
            s.excused += 1
        if (a and a.in_time) or st == "noin":
            s.worked += 1
        if st == "noin":
            s.exp += 1
            s.viol += 1
        if a and a.out_time and a.early_min:
            s.early_n += 1
            if a.early_reason != "Sababli":
                s.viol += 1
        s.pts += pts or 0

    past_end = min(end, today - timedelta(days=1))
    sn = since()
    for a in Attendance.objects.filter(
        day__gte=start, day__lte=past_end, finalized=True
    ).select_related("employee"):
        if sn and a.day < sn:
            continue
        add(a.employee, a.status, a, a.points or 0)
    if start <= today <= end:
        for r in compute_day(today, now_d):
            add(r.e, r.st, r.a, row_points(r, today, now_d) if scored(r) else 0)
    for x in PointAdjustment.objects.filter(day__gte=start, day__lte=end).select_related(
        "employee"
    ):
        s = get(x.employee)
        s.adj += x.value
        s.pts += x.value
    full_month = (
        start.day == 1 and end == last_day_of_month(start.strftime("%Y-%m")) and today >= end
    )
    out = []
    for s in stats.values():
        s.disc = round(100 * s.on_time / s.exp) if s.exp else 100
        if full_month and s.worked and not s.viol:
            s.bonus = PTS["MONTH_CLEAN"]
            s.pts += s.bonus
        if s.e.is_active or s.exp:
            out.append(s)
    out.sort(key=lambda s: (-s.pts, -s.disc, s.late_min, s.e.name))
    return out


def month_stats(ym: str, now_d: datetime) -> list[Stat]:
    return period_stats(date.fromisoformat(ym + "-01"), last_day_of_month(ym), now_d)


def year_stats(y: str, now_d: datetime) -> list[dict]:
    """yearStats_: sum of the months, plus how many times «Oy xodimi»."""
    from .models import Winner

    today = now_d.date()
    wins = {}
    for w in Winner.objects.filter(kind="m", period__startswith=f"{y}-"):
        wins[(w.period, w.employee_id)] = True
    tot: dict[int, dict] = {}
    for m in range(1, 13):
        ym = f"{y}-{m:02d}"
        if date.fromisoformat(ym + "-01") > today:
            break
        for s in month_stats(ym, now_d):
            x = tot.setdefault(
                s.e.id,
                {"e": s.e, "pts": 0, "exp": 0, "on_time": 0, "wins": 0, "bonus": 0, "adj": 0},
            )
            x["pts"] += s.pts
            x["exp"] += s.exp
            x["on_time"] += s.on_time
            x["bonus"] += s.bonus
            x["adj"] += s.adj
            if wins.get((ym, s.e.id)):
                x["wins"] += 1
    out = []
    for x in tot.values():
        x["disc"] = round(100 * x["on_time"] / x["exp"]) if x["exp"] else 100
        if x["e"].is_active and x["exp"]:
            out.append(x)
    out.sort(key=lambda x: (-x["pts"], -x["wins"], -x["disc"]))
    return out


# =================================================================== admin actions
def add_leave(e: Employee, d_from: date, d_to: date, reason: str) -> Leave:
    if d_to < d_from:
        d_from, d_to = d_to, d_from
    with transaction.atomic():
        num = (Leave.objects.aggregate(m=Max("number"))["m"] or 0) + 1
        return Leave.objects.create(
            number=num,
            employee=e,
            date_from=d_from,
            date_to=d_to,
            reason=(reason or "ta'til")[:255],
        )


def add_points(e: Employee, value: int, reason: str, day: date) -> PointAdjustment:
    if not value or abs(value) > 100:
        raise ServiceError("Ball 1 dan 100 gacha (yoki −1 dan −100 gacha) bo'lishi kerak.")
    return PointAdjustment.objects.create(
        employee=e, day=day, value=value, reason=(reason or "")[:255]
    )


def holiday_name(d: date) -> str:
    for k, name in UZ_HOLIDAYS:
        if k == d.isoformat() or k == d.strftime("%m-%d"):
            return name
    return "bayram"


def apply_holiday(hol_day: date, n: int, start_day: date | None = None) -> list[date]:
    """applyHoliday_: n days off from start_day (0 = we work)."""
    from .models import HolidayDecision

    HolidayDecision.objects.update_or_create(holiday_day=hol_day, defaults={"days": n})
    if not n:
        return []
    name = holiday_name(hol_day)
    days = [(start_day or hol_day) + timedelta(days=i) for i in range(n)]
    for d in days:
        Holiday.objects.update_or_create(day=d, defaults={"name": name})
    return days


def reset_data(since_day: date):
    """resetData_: forget attendance, points and winners; keep people and settings."""
    from .models import Winner

    with transaction.atomic():
        Attendance.objects.all().delete()
        PointAdjustment.objects.all().delete()
        Winner.objects.all().delete()
        HrState.objects.filter(key__startswith="f_").delete()
        set_state("SINCE", since_day.isoformat())
        set_state("CURDAY", now().date().isoformat())
        Employee.objects.filter(created_on__lt=since_day).update(created_on=since_day)


def parse_eta(text: str, now_min: int) -> int | None:
    """parseEta_: '20', '20 daqiqa', '1 soat', 'yarim soat', '10:30' → minute of day."""
    t = re.sub(r"[‘’`ʻʼ]", "'", str(text or "").lower()).strip()
    if not t:
        return None
    m = re.search(r"(?:^|\D)(\d{1,2})[:.](\d{2})(?!\d)", t)
    if m and ("soat" not in t or ":" in t):
        h, mi = int(m[1]), int(m[2])
        if h < 24 and mi < 60:
            tm = h * 60 + mi
            if tm < now_min - 5 and h < 12:
                tm += 720
            if tm >= now_min - 5:
                return max(tm, now_min)
    if re.search(r"bir yarim soat|1[.,]5 soat|1 yarim", t):
        return now_min + 90
    if "yarim soat" in t:
        return now_min + 30
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(soat|час|hour)", t)
    if m:
        return now_min + round(float(m[1].replace(",", ".")) * 60)
    m = re.search(r"(\d+)\s*(daq|min|м)", t)
    if m:
        return now_min + int(m[1])
    m = re.fullmatch(r"\D*(\d{1,3})\D*", t)
    if m and 1 <= int(m[1]) <= 240:
        return now_min + int(m[1])
    words = {
        "o'n besh": 15,
        "yigirma": 20,
        "o'ttiz": 30,
        "ottiz": 30,
        "qirq": 40,
        "ellik": 50,
        "o'n": 10,
        "bir": 1,
        "ikki": 2,
        "uch": 3,
        "besh": 5,
    }
    for k, v in words.items():
        if re.search(rf"(^|\s){re.escape(k)}(\s|$)", t):
            if "soat" in t:
                return now_min + v * 60
            if "daq" in t or "min" in t:
                return now_min + v
    return None


# =================================================================== site edits
ATT_EDITABLE = {
    "status",
    "in_time",
    "out_time",
    "late_min",
    "late_reason",
    "late_comment",
    "early_min",
    "early_reason",
    "early_comment",
    "uniform",
    "excuse",
    "note",
}


@transaction.atomic
def edit_attendance(a: Attendance, data: dict) -> Attendance:
    """HR correction on the site. A finished day gets its points recomputed with the
    same rules as the bot (pointsOf_)."""
    unknown = set(data) - ATT_EDITABLE
    if unknown:
        raise ServiceError("Tahrirlab bo'lmaydigan maydon: " + ", ".join(sorted(unknown)))
    a = Attendance.objects.select_for_update().select_related("employee").get(pk=a.pk)
    if a.finalized and data.get("status") == "waiting":
        raise ServiceError("Tugagan kun uchun «Hali kelmadi» holatini qo'yib bo'lmaydi.")
    for k, v in data.items():
        setattr(a, k, v)
    start = parse_hm(a.work_start) if a.work_start else emp_start(a.employee)
    if a.in_time and ("in_time" in data or ("status" in data and a.status in ("on_time", "late"))):
        # a new arrival time decides on time / late, as on check-in
        late = parse_hm(a.in_time) - start
        if "status" not in data or a.status in ("on_time", "late"):
            a.status = "on_time" if late <= setting_int("GRACE_MIN") else "late"
        a.late_min = max(late, 0)
    if a.status in ("on_time", "late") and not a.in_time:
        raise ServiceError("«Vaqtida» yoki «Kech» uchun kelgan vaqtini kiriting.")
    a.no_checkin = a.status == "noin"
    if a.finalized:
        r = Row(a.employee, a.status, a, a.note)
        a.points = (
            row_points(r, a.day, datetime.combine(a.day, time(23, 59)), final=True)
            if scored(r)
            else None
        )
    a.save()
    return a


def day_rows(day: date, now_d: datetime | None = None) -> list[dict]:
    """The board for one day (today live, past days as frozen)."""
    now_d = now_d or now()
    out = []
    for r in compute_day(day, now_d):
        a = r.a
        out.append(
            {
                "employee_id": r.e.id,
                "number": r.e.number,
                "name": r.e.name,
                "username": r.e.username,
                "group": r.e.group.title if r.e.group else (a.group_title if a else ""),
                "status": r.st,
                "attendance_id": a.id if a else None,
                "in_time": hm(r.g("in_time")),
                "out_time": hm(r.g("out_time")),
                "late_min": r.g("late_min"),
                "late_reason": r.g("late_reason") or "",
                "late_comment": r.g("late_comment") or "",
                "early_min": r.g("early_min"),
                "early_reason": r.g("early_reason") or "",
                "early_comment": r.g("early_comment") or "",
                "eta": hm(r.g("eta")),
                "uniform": r.g("uniform"),
                "note": r.note or r.g("excuse") or "",
                "link": r.g("link") or "",
                "hours": f"{a.work_start}–{a.work_end}" if a and a.work_start else emp_hours(r.e),
                "points": row_points(r, day, now_d) if scored(r) else None,
                "finalized": bool(a and a.finalized),
                "can_dm": r.e.can_dm,
            }
        )
    return out


# =================================================================== bot-facing rules
# What the davomat Telegram handlers used to decide inline (hr/telegram.py). The bot now
# forwards raw Telegram facts to api/views/bot/hr.py, which calls these functions; they
# return DATA (what happened, what to say), never message text. Docs: docs/BOT_CONTRACT.md.
def employee_dto(e: Employee) -> dict:
    effective = emp_off_days(e)
    return {
        "telegram_id": e.telegram_id,
        "number": e.number,
        "name": e.name,
        "username": e.username,
        "is_active": e.is_active,
        "can_dm": e.can_dm,
        "group": {"chat_id": e.group.chat_id, "title": e.group.title} if e.group_id else None,
        "work_start": e.work_start,
        "work_end": e.work_end,
        "hours_label": emp_hours(e),
        "ontime_until": hm_str(emp_start(e) + setting_int("GRACE_MIN")),
        "off_days": list(e.off_days) if e.off_days else None,
        "off_days_effective": effective,
        "off_label": days_label(effective) if effective else "rahbar belgilaydi",
    }


def group_dto(g: WorkGroup) -> dict:
    return {"chat_id": g.chat_id, "title": g.title, "is_active": g.is_active}


def _events():
    from . import events

    return events


def mark_dm_ok(e: Employee) -> None:
    """They wrote to the bot, so it can write back."""
    if e.can_dm is not True:
        Employee.objects.filter(pk=e.pk).update(can_dm=True)
        e.can_dm = True


def record_dm(tg_id, ok: bool, blocked: bool = False) -> None:
    """The bot tried to write to an employee privately: remember the result (dm_)."""
    e = emp(tg_id)
    if not e:
        return
    if ok:
        mark_dm_ok(e)
    elif blocked and e.can_dm is not False:
        Employee.objects.filter(pk=e.pk).update(can_dm=False)


def record_dm_results(delivered) -> None:
    """After an `hr.*` event: `delivered` is the bot's [{chat_id, ok, blocked}, ...]."""
    for d in delivered or []:
        try:
            record_dm(d.get("chat_id"), bool(d.get("ok")), bool(d.get("blocked")))
        except (TypeError, ValueError):
            continue


def msg_link(chat: dict, message_id: int) -> str:
    if chat.get("username"):
        return f"https://t.me/{chat['username']}/{message_id}"
    cid = re.sub(r"^-100|^-", "", str(chat["id"]))
    return f"https://t.me/c/{cid}/{message_id}"


_IGNORED = {"action": "ignored", "react": None, "reply": None, "dm": None}


def _dm_payload(e: Employee, kind: str, day: date, **fields) -> dict | None:
    """The DM the bot should send; None when the person blocked the bot."""
    if e.can_dm is False:
        return None
    return {
        "kind": kind,
        "employee": employee_dto(e),
        "day": day.isoformat(),
        "at": "",
        "late_min": 0,
        "early_min": 0,
        "end": hm_str(emp_end(e)),
        "uniform_ask": False,
        **fields,
    }


def process_group_report(
    *,
    chat: dict,
    message_id: int,
    ts: int,
    user: dict,
    forwarded: bool = False,
    media: dict | None = None,
    text: str = "",
) -> dict:
    """on_group_message: a message in a watched work group. Decides whether it is a
    check-in / leaving report and records it. Returns
    {action, react, reply, dm} (see docs/BOT_CONTRACT.md)."""
    with transaction.atomic():
        return _process_group_report(chat, message_id, ts, user, forwarded, media or {}, text)


def _process_group_report(chat, message_id, ts, user, forwarded, media, text) -> dict:
    group = group_by_chat(chat["id"])
    if user.get("is_bot") or not group or is_admin(user["id"]):
        return dict(_IGNORED)
    e, _ = upsert_emp(user, group)
    at = from_unix(ts or 0)
    day, at_min = at.date(), mod(at)
    if at_min < (parse_hm(setting("CHECKIN_FROM")) or 300):
        return dict(_IGNORED)
    if forwarded:
        return dict(_IGNORED)  # a forwarded report doesn't count
    mode = setting("CHECKIN_MODE").lower()
    is_vn = bool(media.get("video_note"))
    has_media = any(media.get(k) for k in ("photo", "video", "video_note", "location", "venue"))
    txt = str(text or "").lower()
    kws = [k.strip() for k in setting("KEYWORDS").lower().split(",") if k.strip()]
    has_kw = any(k in txt for k in kws)
    if mode == "video_note":
        ok = is_vn
    elif mode == "media":
        ok = has_media
    elif mode == "keyword":
        ok = has_kw
    elif mode == "any":
        ok = has_media or bool(txt.strip())
    else:
        ok = has_media or has_kw
    sn = since()
    if sn and day < sn:
        return dict(_IGNORED)
    if not expected_today(e, day):
        return dict(_IGNORED)
    # lock the day's row before deciding: two quick reports must not both be "first"
    if ok:
        Attendance.objects.select_for_update().get_or_create(employee=e, day=day)
    a = att(day, e)
    real = ok and (mode != "any" or has_media)
    ack = setting("GROUP_ACK")
    if a and a.in_time:
        if real:
            return _process_checkout(e, day, a, at_min, ack)
        return dict(_IGNORED)
    # no check-in, but less than 2h to the end of the day: this is the leaving report
    if real and ((a and a.out_time) or at_min >= emp_end(e) - 120):
        first = not (a and a.out_time)
        set_att(day, e, out_time=to_time(at_min), no_checkin=True, wait="")
        return {
            "action": "leave_only",
            "react": "\U0001fae1" if ack == "reaction" else None,
            "reply": None,
            "dm": (
                _dm_payload(e, "leave_without_checkin", day, at=hm_str(at_min)) if first else None
            ),
        }
    if not ok:
        if mode == "video_note" and (has_media or has_kw) and not (a and a.warned):
            set_att(day, e, warned=True)
            return {
                "action": "format_warning",
                "react": None,
                "reply": None,
                "dm": _dm_payload(e, "format_warning", day),
            }
        return dict(_IGNORED)
    start = emp_start(e)
    late = at_min - start
    st = "on_time" if late <= setting_int("GRACE_MIN") else "late"
    link = msg_link(chat, message_id)
    set_att(
        day,
        e,
        in_time=to_time(at_min),
        late_min=max(late, 0),
        status=st,
        link=link,
        wait="lr" if st == "late" else "",
        work_start=hm_str(start),
        work_end=hm_str(emp_end(e)),
        group_title=group.title,
    )
    react = None
    reply = None
    if ack == "reaction":
        react = "\U0001f525" if st == "on_time" else "✍"
    elif ack == "reply":
        reply = {"status": st, "at": hm_str(at_min), "late_min": max(late, 0)}
    if st == "late" and setting_bool("MANAGER_LIVE_ALERTS"):
        _events().live_alert(
            "late",
            e,
            {
                "group_title": group.title,
                "in_time": hm_str(at_min),
                "late_min": max(late, 0),
                "link": link,
            },
        )
    return {
        "action": "checkin",
        "react": react,
        "reply": reply,
        "dm": _dm_payload(
            e,
            "checkin_on_time" if st == "on_time" else "checkin_late",
            day,
            at=hm_str(at_min),
            late_min=max(late, 0),
            uniform_ask=st == "on_time" and setting_bool("UNIFORM_CHECK"),
        ),
    }


def _process_checkout(e: Employee, day: date, a: Attendance, at_min: int, ack: str) -> dict:
    """onCheckout_: a video note at least OUT_MIN_GAP after arrival = leaving."""
    in_min = parse_hm(a.in_time)
    if at_min - in_min < setting_int("OUT_MIN_GAP"):
        return dict(_IGNORED)
    end = parse_hm(a.work_end) if a.work_end else emp_end(e)
    early = max(end - at_min, 0)
    is_early = early > setting_int("LEAVE_GRACE_MIN")
    first = a.out_time is None
    wait = "er" if is_early and not a.early_reason else ("" if a.wait in ("er", "ec") else a.wait)
    set_att(
        day,
        e,
        out_time=to_time(at_min),
        early_min=early if is_early else 0,
        early_reason=a.early_reason if is_early else "",
        wait=wait,
    )
    out = {
        "action": "checkout",
        "react": ("✍" if is_early else "\U0001fae1") if ack == "reaction" else None,
        "reply": None,
        "dm": None,
    }
    if not first and not is_early:
        return out
    if not is_early:
        out["dm"] = _dm_payload(e, "checkout", day, at=hm_str(at_min), end=hm_str(end))
    elif not a.early_reason:
        out["dm"] = _dm_payload(
            e, "checkout_early", day, at=hm_str(at_min), early_min=early, end=hm_str(end)
        )
    return out


def set_eta(e: Employee, day: date, eta_min: int) -> None:
    set_att(day, e, eta=to_time(eta_min), eta_sent=False, wait="")
    if setting_bool("MANAGER_LIVE_ALERTS"):
        _events().live_alert("eta", e, {"eta": hm_str(eta_min)})


def set_excused(e: Employee, day: date, reason: str) -> None:
    set_att(day, e, status="excused", excuse=reason or "sabab ko'rsatilmadi", wait="")
    _events().live_alert("excused", e, {"reason": reason})


def _looks_finance(text: str) -> bool:
    """«350000 furnitura 406» is a finance entry; «20 daqiqa» is an ETA."""
    from accounting.text import parse_quick

    try:
        q = parse_quick(text, [], [])
        return bool(q) and (q["val"] >= 1000 or q["cur"] == "USD")
    except Exception:  # noqa: BLE001
        return False


def process_private_text(tg_id, text: str) -> dict:
    """on_private_text: a private message that may be the answer the bot waits for
    (lateness / leaving comment, reason for absence, arrival time). The bot calls it only
    when no finance flow is open. `handled: false` = not for HR."""
    text = str(text or "").strip()
    nothing = {"handled": False, "outcome": None, "data": {}}
    e = emp(tg_id)
    if not text or not e:
        return nothing
    mark_dm_ok(e)
    fin = _looks_finance(text)
    now_d = now()
    day = now_d.date()
    a = att(day, e)
    if not a:
        return nothing
    live = setting_bool("MANAGER_LIVE_ALERTS")
    if a.wait == "lc" and a.in_time and not fin:
        set_att(day, e, late_comment=text[:300], wait="")
        if live:
            _events().live_alert(
                "late_comment", e, {"late_reason": a.late_reason, "comment": text[:300]}
            )
        return {
            "handled": True,
            "outcome": "late_comment",
            "data": {
                "late_reason": a.late_reason,
                "uniform_ask": setting_bool("UNIFORM_CHECK") and a.uniform is None,
            },
        }
    if a.wait == "ec" and a.out_time and not fin:
        set_att(day, e, early_comment=text[:300], wait="")
        return {
            "handled": True,
            "outcome": "early_comment",
            "data": {"early_reason": a.early_reason},
        }
    if a.wait == "reason" and not a.in_time and not fin:
        set_excused(e, day, text[:300])
        return {"handled": True, "outcome": "excused", "data": {}}
    if not a.in_time and (a.asked or a.eta) and a.status not in ("excused", "off") and not fin:
        eta = parse_eta(text, mod(now_d))
        if eta is not None:
            set_eta(e, day, eta)
            return {"handled": True, "outcome": "eta", "data": {"eta": hm_str(eta)}}
    return nothing


def process_employee_callback(tg_id, action: str, day_iso: str, arg: str = "") -> dict:
    """The employee's `dv:` buttons (uni, lr, er, eta, here, cant, rsn, offreq).
    Returns {answer, alert, clear_kb, reply: {kind, data}|None}."""
    out = {"answer": "", "alert": False, "clear_kb": False, "reply": None}
    e = emp(tg_id)
    if not e:
        return {**out, "answer": "Siz ro'yxatda yo'qsiz"}
    today_ = now().date()
    try:
        day = date.fromisoformat(day_iso)
    except (TypeError, ValueError):
        return out
    if day != today_:
        return {**out, "answer": "Bu tugma eskirgan (boshqa kun uchun edi).", "alert": True}
    mark_dm_ok(e)
    a = att(day, e)

    def reply(kind, **data):
        return {"kind": kind, "data": {"employee": employee_dto(e), **data}}

    if action == "uni":
        set_att(day, e, uniform=arg == "1")
        return {
            **out,
            "answer": "Rahmat!",
            "clear_kb": True,
            "reply": reply("uniform_yes" if arg == "1" else "uniform_no"),
        }
    if action == "lr":
        if not (a and a.in_time):
            return out
        lr = "Sababli" if arg == "1" else "Sababsiz"
        set_att(day, e, late_reason=lr, wait="lc")
        return {**out, "clear_kb": True, "reply": reply("late_reason_ask", reason=lr)}
    if action == "er":
        if not (a and a.out_time):
            return out
        er = "Sababli" if arg == "1" else "Sababsiz"
        set_att(day, e, early_reason=er, wait="ec")
        return {**out, "clear_kb": True, "reply": reply("early_reason_ask", reason=er)}
    if a and a.in_time:
        return {**out, "answer": "Siz bugun otchet tashlagansiz ✅", "clear_kb": True}
    if action == "eta":
        try:
            minutes = int(arg)
        except (TypeError, ValueError):
            return out
        eta = mod(now()) + minutes
        set_eta(e, day, eta)
        return {
            **out,
            "answer": "Qabul qilindi",
            "clear_kb": True,
            "reply": reply("eta_ok", eta=hm_str(eta)),
        }
    if action == "here":
        return {**out, "clear_kb": True, "reply": reply("here_ok")}
    if action == "cant":
        set_att(day, e, wait="reason")
        return {**out, "clear_kb": True, "reply": reply("cant_ask")}
    if action == "rsn":
        if arg == "other":
            set_att(day, e, wait="reason")
            return {**out, "clear_kb": True, "reply": reply("reason_other")}
        set_excused(e, day, REASONS.get(arg, arg))
        return {**out, "clear_kb": True, "reply": reply("excused_done")}
    if action == "offreq":
        set_att(day, e, off_requested=True)
        _events().off_request(e, day)
        return {**out, "clear_kb": True, "reply": reply("offreq_sent")}
    return out


def cant_come(tg_id) -> dict:
    """/kelolmayman: {result: not_employee | already_in | ask_reason, day}."""
    day = now().date()
    e = emp(tg_id)
    if not e:
        return {"result": "not_employee", "day": day.isoformat()}
    mark_dm_ok(e)
    a = att(day, e)
    if a and a.in_time:
        return {"result": "already_in", "day": day.isoformat()}
    set_att(day, e, wait="reason")
    return {"result": "ask_reason", "day": day.isoformat(), "employee": employee_dto(e)}


def employee_start(user: dict, group_chat_id: int | None = None) -> Employee | None:
    """/start from a private chat. An existing employee is switched on (can_dm, active).
    A newcomer is created only when the bot found them in a work group
    (`group_chat_id`, from getChatMember over hr/groups/)."""
    e = emp(user["id"])
    if not e and group_chat_id is not None:
        g = group_by_chat(group_chat_id)
        if g:
            e, _ = upsert_emp(user, g)
    if not e:
        return None
    e.can_dm, e.is_active = True, True
    e.save(update_fields=["can_dm", "is_active"])
    return e


def members_joined(chat: dict, users: list[dict]) -> list[dict]:
    """new_chat_members in a work group -> who gets the «connect to the bot» welcome."""
    group = group_by_chat(chat["id"])
    welcome = []
    if not group:
        return welcome
    for u in users:
        if u.get("is_bot") or is_admin(u["id"]):
            continue
        e, is_new = upsert_emp(u, group)
        if is_new or e.can_dm is not True:
            welcome.append({"name": e.name})
    return welcome


def member_left(chat: dict, user: dict) -> Employee | None:
    """left_chat_member / chat_member(left|kicked): drop them from the list."""
    group = group_by_chat(chat["id"])
    if not group or not user or user.get("is_bot"):
        return None
    e = emp(user["id"])
    if e and e.is_active and e.group_id == group.id:
        e.is_active = False
        e.save(update_fields=["is_active"])
        _events().employee_left(e)
        return e
    return None


def bot_added_to_group(chat: dict, status: str) -> bool:
    """my_chat_member: the bot joined a group we don't watch yet -> tell the admins."""
    if (
        chat.get("type", "group") in ("group", "supergroup")
        and status in ("member", "administrator")
        and not group_by_chat(chat["id"])
    ):
        _events().bot_added_to_group(chat.get("title") or str(chat["id"]))
        return True
    return False


def connect_group(chat_id: int, title: str) -> WorkGroup:
    """/ulash"""
    g, _ = WorkGroup.objects.update_or_create(
        chat_id=int(chat_id), defaults={"title": (title or str(chat_id))[:255], "is_active": True}
    )
    return g


def disconnect_group(chat_id: int) -> bool:
    """/uzish"""
    return bool(WorkGroup.objects.filter(chat_id=int(chat_id)).update(is_active=False))


def set_off_days(e: Employee, days) -> Employee:
    """days: list of 1..7, or None for the general OFF_DAYS setting."""
    e.off_days = None if days is None else parse_days(",".join(str(d) for d in days))
    e.save(update_fields=["off_days"])
    return e


def toggle_off_day(e: Employee, d: int) -> tuple[Employee, bool]:
    """Add/remove one weekday from the personal list. Returns (employee, was_set)."""
    if not 1 <= int(d) <= 7:
        raise ServiceError("Hafta kuni 1 dan 7 gacha.")
    off = list(e.off_days or [])
    was = int(d) in off
    off = sorted([x for x in off if x != int(d)] if was else off + [int(d)])
    e.off_days = off
    e.save(update_fields=["off_days"])
    return e, was


def set_active(e: Employee, active: bool) -> Employee:
    e.is_active = bool(active)
    e.save(update_fields=["is_active"])
    return e


def delete_leave(number: int) -> bool:
    return bool(Leave.objects.filter(number=int(number)).delete()[0])


def set_holiday(day: date, name: str) -> Holiday:
    h, _ = Holiday.objects.update_or_create(day=day, defaults={"name": (name or "bayram")[:128]})
    return h


def delete_holiday(day: date) -> bool:
    return bool(Holiday.objects.filter(day=day).delete()[0])


def decide_holiday(hol_day: date, n: int, start_day: date | None = None) -> dict:
    """The admin answered «dam olinadimi?» once. {days, name}; ServiceConflict if decided."""
    from .models import HolidayDecision

    if n < 0 or n > 30:
        raise ServiceError("Kunlar soni 0 dan 30 gacha.")
    with transaction.atomic():
        try:
            # the unique holiday_day row is the lock: the second answer fails here
            with transaction.atomic():
                HolidayDecision.objects.create(holiday_day=hol_day, days=n)
        except IntegrityError:
            raise ServiceConflict("Bu bayram bo'yicha qaror allaqachon qabul qilingan.")
        days = apply_holiday(hol_day, n, start_day or hol_day)
    return {"days": days, "name": holiday_name(hol_day)}


def answer_off_request(e: Employee, day: date, approve: bool) -> None:
    """Admin's answer to «bugun dam olish kunim»."""
    with transaction.atomic():
        a = Attendance.objects.select_for_update().filter(employee=e, day=day).first()
        if not a or not a.off_requested:
            raise ServiceConflict("Bu so'rovga allaqachon javob berilgan.")
        if approve:
            set_att(day, e, status="off", off_requested=False)
        else:
            set_att(day, e, off_requested=False)


def announce_winner(kind: str, period: str, employee: Employee) -> dict:
    """announceWinner_ data: once per period. ServiceConflict when already announced.
    Returns {employee, pts, disc, groups: [chat_id]}."""
    if kind not in ("m", "y"):
        raise ServiceError("Noto'g'ri tur.")
    now_d = now()
    with transaction.atomic():
        if Winner.objects.select_for_update().filter(kind=kind, period=period).exists():
            raise ServiceConflict("Bu tanlov allaqachon e'lon qilingan.")
        if kind == "m":
            st = next((s for s in month_stats(period, now_d) if s.e.id == employee.id), None)
            pts, disc = (st.pts, st.disc) if st else (0, 0)
        else:
            st = next((s for s in year_stats(period, now_d) if s["e"].id == employee.id), None)
            pts, disc = (st["pts"], st["disc"]) if st else (0, 0)
        try:
            Winner.objects.create(kind=kind, period=period, employee=employee)
        except IntegrityError:
            raise ServiceConflict("Bu tanlov allaqachon e'lon qilingan.")
    return {
        "employee": employee,
        "pts": pts,
        "disc": disc,
        "groups": [g.chat_id for g in groups()],
    }


def my_status_data(e: Employee) -> dict:
    """/holatim: today's state and the month's standing."""
    now_d = now()
    day = now_d.date()
    r = next((x for x in compute_day(day, now_d) if x.e.id == e.id), None)
    allst = month_stats(day.strftime("%Y-%m"), now_d)
    idx = next((i for i, s in enumerate(allst) if s.e.id == e.id), -1)
    month = None
    if idx >= 0:
        st = allst[idx]
        month = {
            "rank": idx + 1,
            "of": len(allst),
            "pts": st.pts,
            "on_time": st.on_time,
            "late": st.late,
            "late_min": st.late_min,
            "absent": st.absent,
            "excused": st.excused,
            "early_n": st.early_n,
            "disc": st.disc,
        }
    return {
        "employee": employee_dto(e),
        "today": {
            "st": r.st if r else None,
            "in_time": hm(r.g("in_time")) if r else "",
            "out_time": hm(r.g("out_time")) if r else "",
        },
        "month": month,
    }


def ranking_rows(
    ym: str | None = None, year: str | None = None, only_active: bool = False
) -> list[dict]:
    """/reyting data. only_active: active employees with expected days (the winner pick)."""
    now_d = now()
    if year:
        return [
            {
                "telegram_id": x["e"].telegram_id,
                "name": x["e"].name,
                "pts": x["pts"],
                "disc": x["disc"],
                "bonus": x["bonus"],
                "adj": x["adj"],
                "wins": x["wins"],
            }
            for x in year_stats(year, now_d)
        ]
    return [
        {
            "telegram_id": s.e.telegram_id,
            "name": s.e.name,
            "pts": s.pts,
            "disc": s.disc,
            "bonus": s.bonus,
            "adj": s.adj,
            "wins": 0,
        }
        for s in month_stats(ym or now_d.strftime("%Y-%m"), now_d)
        if not only_active or (s.e.is_active and s.exp)
    ]
