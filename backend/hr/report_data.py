"""Data behind the davomat reports (day / past day / period). The bot renders the text;
the shapes are exactly the values the old text builders read (docs/BOT_CONTRACT.md)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from . import services as S
from .models import Attendance

_FIVE = ("on_time", "late", "waiting", "absent", "excused")


def _hm(t) -> str:
    return S.hm(t)


def day_report_data(day: date, now_d: datetime) -> dict:
    """dayReport_: today's live state."""
    rows = S.compute_day(day, now_d)
    by = {k: [] for k in _FIVE}
    rest = []
    for r in rows:
        (by[r.st] if r.st in _FIVE else rest).append(r)
    expected = sum(len(by[k]) for k in _FIVE)
    by["late"].sort(key=lambda r: -(r.g("late_min") or 0))
    out = {
        "kind": "live",
        "day": day.isoformat(),
        "empty": not expected and not by["on_time"] and not by["late"],
        "expected": expected,
        "on_time": [
            {"name": r.e.name, "in_time": _hm(r.g("in_time"))}
            for r in sorted(by["on_time"], key=lambda r: _hm(r.g("in_time")))
        ],
        "late": [
            {
                "name": r.e.name,
                "in_time": _hm(r.g("in_time")),
                "late_min": r.g("late_min") or 0,
                "late_reason": r.g("late_reason") or "",
                "late_comment": r.g("late_comment") or "",
            }
            for r in by["late"]
        ],
        "waiting": [
            {
                "name": r.e.name,
                "eta": _hm(r.g("eta")),
                "asked": r.g("asked") or 0,
                "can_dm": r.e.can_dm,
            }
            for r in by["waiting"]
        ],
        "absent": [{"name": r.e.name, "eta": _hm(r.g("eta")) or None} for r in by["absent"]],
        "excused": [{"name": r.e.name, "note": r.note} for r in by["excused"]],
        "leave": [{"name": r.e.name, "note": r.note} for r in rest if r.st == "leave"],
        "rest_count": len(rest),
        "no_uniform": [r.e.name for r in rows if r.g("uniform") is False],
        "groups": [],
        "yesterday_early": [],
        "yesterday_no_out": [],
        "not_connected": [r.e.name for r in rows if r.e.can_dm is False and r.e.is_active],
    }
    groups = S.groups()
    if len(groups) > 1:
        for g in groups:
            gr = [r for r in rows if r.e.group_id == g.id]
            if not gr:
                continue
            c = {k: 0 for k in _FIVE}
            for r in gr:
                if r.st in c:
                    c[r.st] += 1
            out["groups"].append({"title": g.title, **c})
    yrows = list(
        Attendance.objects.filter(
            day=day - timedelta(days=1), in_time__isnull=False
        ).select_related("employee")
    )
    out["yesterday_early"] = [
        {
            "name": a.employee.name,
            "out_time": _hm(a.out_time),
            "early_min": a.early_min,
            "early_reason": a.early_reason,
            "early_comment": a.early_comment,
        }
        for a in yrows
        if a.out_time and a.early_min
    ]
    out["yesterday_no_out"] = [a.employee.name for a in yrows if not a.out_time]
    return out


def past_day_report_data(day: date) -> dict:
    """pastDayReport_: a finished day, from the frozen rows."""
    rows = list(Attendance.objects.filter(day=day, finalized=True).select_related("employee"))
    if not rows:
        return {"kind": "past", "day": day.isoformat(), "empty": True}

    def by(st):
        return [a for a in rows if a.status == st]

    return {
        "kind": "past",
        "day": day.isoformat(),
        "empty": False,
        "expected": len([a for a in rows if a.status in ("on_time", "late", "absent", "excused")]),
        "on_time": len(by("on_time")),
        "late": len(by("late")),
        "absent": len(by("absent")),
        "excused": len(by("excused")),
        "late_rows": [
            {
                "name": a.employee.name,
                "in_time": _hm(a.in_time),
                "late_min": a.late_min or 0,
                "late_reason": a.late_reason,
                "late_comment": a.late_comment,
            }
            for a in sorted(by("late"), key=lambda a: -(a.late_min or 0))
        ],
        "absent_names": [a.employee.name for a in by("absent")],
    }


def period_report_data(start: date, end: date, now_d: datetime) -> dict:
    """periodReport_: ranking of a week / month."""
    st = S.period_stats(start, end, now_d)
    out = {
        "kind": "period",
        "date_from": start.isoformat(),
        "date_to": min(end, now_d.date()).isoformat(),
        "empty": not st,
    }
    if not st:
        return out
    exp, on = sum(s.exp for s in st), sum(s.on_time for s in st)
    out.update(
        on_time=on,
        late=sum(s.late for s in st),
        late_reasoned=sum(s.late_r for s in st),
        absent=sum(s.absent for s in st),
        excused=sum(s.excused for s in st),
        discipline=round(100 * on / exp) if exp else 100,
        late_min=sum(s.late_min for s in st),
        rows=[
            {
                "telegram_id": s.e.telegram_id,
                "name": s.e.name,
                "pts": s.pts,
                "on_time": s.on_time,
                "late": s.late,
                "absent": s.absent,
                "early_n": s.early_n,
                "disc": s.disc,
                "late_min": s.late_min,
                "late_r": s.late_r,
                "viol": s.viol,
                "bonus": s.bonus,
                "adj": s.adj,
            }
            for s in st
        ],
    )
    return out
