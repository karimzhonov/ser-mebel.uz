"""Small formatting / parsing helpers of the davomat bot (ports of hr/services.py helpers).

The backend stays the source of truth for every rule; these only render values and parse
what an admin typed in a command so the old error texts stay the same.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from html import escape

from .texts import MONTHS, WEEKDAYS


def esc(v) -> str:
    return escape("" if v is None else str(v), quote=False)


def ism(name: str | None) -> str:
    """First word of the name, HTML-escaped (the old `ism(e)`)."""
    n = (name or "").strip().split()
    return esc(n[0] if n else "hurmatli hamkasb")


def hm_str(minutes: int) -> str:
    minutes = ((int(minutes) % 1440) + 1440) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_hm(s) -> int | None:
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", str(s or "").strip())
    if not m:
        return None
    h, mi = int(m[1]), int(m[2])
    return h * 60 + mi if h <= 23 and mi <= 59 else None


def fmt_min(m) -> str:
    m = round(m or 0)
    if m < 60:
        return f"{m} daq"
    h, r = divmod(m, 60)
    return f"{h} soat {r} daq" if r else f"{h} soat"


def fmt_day(d: date) -> str:
    return f"{d.day}-{MONTHS[d.month - 1]}, {WEEKDAYS[d.isoweekday() - 1]}"


def month_name(ym: str) -> str:
    return f"{MONTHS[int(ym[5:7]) - 1]} {ym[:4]}"


def last_day_of_month(ym: str) -> date:
    y, m = int(ym[:4]), int(ym[5:7])
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return nxt - timedelta(days=1)


def parse_days(s) -> list[int]:
    out: list[int] = []
    for p in re.sub(r"\s", "", str(s or "")).split(","):
        if p.isdigit() and 1 <= int(p) <= 7 and int(p) not in out:
            out.append(int(p))
    return sorted(out)


def days_label(arr) -> str:
    return ", ".join(WEEKDAYS[d - 1] for d in arr) if arr else "yo'q"


def parse_date(s, today: date) -> date | None:
    """bugun | ertaga | YYYY-MM-DD | dd.mm[.yyyy] -> date, or None."""
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
