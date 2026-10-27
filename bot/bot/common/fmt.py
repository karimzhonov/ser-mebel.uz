"""Formatting helpers (copied from backend/accounting/text.py on purpose: the bot has no
Python import of Django code). Number-ish inputs may be Decimal strings from the API."""

from __future__ import annotations

import html
from datetime import date, datetime, timedelta, timezone

TZ = timezone(timedelta(hours=5))  # Asia/Tashkent, no DST

MON = ["", "Yan", "Fev", "Mar", "Apr", "May", "Iyn", "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"]
MON_FULL = [
    "",
    "Yanvar",
    "Fevral",
    "Mart",
    "Aprel",
    "May",
    "Iyun",
    "Iyul",
    "Avgust",
    "Sentabr",
    "Oktabr",
    "Noyabr",
    "Dekabr",
]


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def today() -> date:
    return now().date()


def cur_month() -> str:
    return today().strftime("%Y-%m")


def add_months(ym: str, k: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) + k
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return f"{y}-{m:02d}"


def month_name(ym: str) -> str:
    return f"{MON[int(ym[5:7])]} {ym[:4]}"


def month_full(ym: str) -> str:
    return f"{MON_FULL[int(ym[5:7])]} {ym[:4]}"


def to_date(d) -> date | None:
    if not d:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d)[:10])
    except ValueError:
        return None


def ddmm(d) -> str:
    dd = to_date(d)
    return dd.strftime("%d.%m.%Y") if dd else "—"


def num(v) -> str:
    v = int(round(float(v or 0)))
    s = f"{abs(v):,}".replace(",", " ")
    return ("−" if v < 0 else "") + s


def money(v) -> str:
    return f"{num(v)} so'm"


def signed(v) -> str:
    return ("+" if float(v or 0) > 0 else "") + num(v)


def usd(v) -> str:
    return f"{num(v)} USD"


def fmt_cur(v, cur: str) -> str:
    """Amount in the order's currency: USD with cents and commas, UZS spaced."""
    if cur == "USD":
        v = float(v or 0)
        s = f"{abs(v):,.2f}"
        return ("-" if v < 0 else "") + s
    return num(v)


def cur_name(cur: str) -> str:
    return "$" if cur == "USD" else "so'm"


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def clip(s: str, n: int) -> str:
    s = str(s)
    if len(s) <= n:
        return s
    i = s.rfind("\n", 0, n - 3)
    return s[: i if i > 0 else n - 3] + "\n…"
