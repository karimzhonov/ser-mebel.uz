"""Money parsing and formatting — a faithful port of the helpers in code.txt, so a
message that worked in the old bot («1.5 mln», «4200$ avans Назира 406») works here."""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

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
    # USE_TZ=False and TIME_ZONE=Asia/Tashkent: naive local time, like the sheet.
    return datetime.now()


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


def month_bounds(ym: str) -> tuple[date, date]:
    start = date(int(ym[:4]), int(ym[5:7]), 1)
    end = date.fromisoformat(add_months(ym, 1) + "-01") - timedelta(days=1)
    return start, end


def month_name(ym: str) -> str:
    return f"{MON[int(ym[5:7])]} {ym[:4]}"


def month_full(ym: str) -> str:
    return f"{MON_FULL[int(ym[5:7])]} {ym[:4]}"


def ddmm(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else "—"


def days_between(a: date, b: date) -> int:
    return (b - a).days


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


_SOM = re.compile(r"so['ʻ’`]?m|сўм|сум|sum", re.I)
_AMOUNT = re.compile(r"^([\d][\d\s.,]*?)\s*(k|ming|минг|тыс|mln|million|млн|m)?$", re.I)
USD_RE = re.compile(r"\$|usd|dollar|доллар", re.I)


def parse_amount(text) -> Decimal | None:
    """'150000', '150 000', '150k', '150 ming', '1.5 mln', '1,5mln', "2 000 000 so'm",
    '4200.50' → number; anything else → None."""
    if text is None:
        return None
    t = _SOM.sub("", str(text).lower()).strip()
    m = _AMOUNT.match(t)
    if not m:
        return None
    num_s, mult = m.group(1).strip(), (m.group(2) or "").lower()
    f = 1
    if mult in ("k", "ming", "минг", "тыс"):
        f = 1000
    elif mult:
        f = 1_000_000
    ns = re.sub(r"\s", "", num_s)
    try:
        if f > 1 or re.fullmatch(r"\d+[.,]\d{1,2}", ns):
            val = float(ns.replace(",", ".")) * f
        else:
            dg = re.sub(r"[\s.,]", "", num_s)
            if not dg.isdigit():
                return None
            val = float(int(dg))
    except ValueError:
        return None
    val = round(val) if (f > 1 or val >= 1000) else round(val * 100) / 100
    return Decimal(str(val)) if val > 0 else None


def parse_money(text) -> tuple[Decimal | None, str]:
    cur = "USD" if USD_RE.search(text or "") else "UZS"
    return parse_amount(USD_RE.sub(" ", str(text or "")).strip()), cur


def guess_category(text: str, categories) -> str | None:
    """The keyword that appears first in the text wins (guessCat_)."""
    t = f" {str(text or '').lower()} "
    best, pos = None, 10**9
    for c in categories:
        for w in c.keywords or []:
            i = t.find(w)
            if 0 <= i < pos:
                pos, best = i, c.code
    return best


def find_order(text: str, ids: list[str]) -> str | None:
    known = {str(i).upper(): i for i in ids}
    for tok in re.split(r"[\s,;()]+", str(text or "")):
        tok = tok.upper().lstrip("#")
        if not tok:
            continue
        if tok in known:
            return known[tok]
        m = re.fullmatch(r"([A-ZА-ЯЁ]+)-?0*(\d+)", tok)
        if m:
            n = f"{m.group(1)}-{int(m.group(2)):03d}"
            if n in known:
                return known[n]
        if tok.isdigit():
            for k, v in known.items():
                if k.isdigit() and int(k) == int(tok):
                    return v
    return None


_QUICK = re.compile(r"^(\d[\d\s.,]*\d|\d)\s*(k|ming|mln|m)?\s*(\$|usd)?\s+(.+)$", re.I | re.S)


def parse_quick(text: str, order_ids: list[str], categories) -> dict | None:
    """Quick entry: '350000 furnitura 406 petlya', '4200$ avans Назира 406'."""
    if not text:
        return None
    t = str(text).strip()
    lead_usd = t.startswith("$")
    m = _QUICK.match(re.sub(r"^\$\s*", "", t))
    if not m:
        return None
    val = parse_amount(m.group(1) + (m.group(2) or ""))
    if not val:
        return None
    rest = m.group(4).strip()
    is_rest = bool(re.search(r"qoldiq|остат|доплат|ostatok", rest, re.I))
    is_adv = not is_rest and bool(re.search(r"avans|аванс|предоплат|oldindan", rest, re.I))
    return {
        "kind": "income" if (is_adv or is_rest) else "expense",
        "cur": "USD" if (lead_usd or m.group(3)) else "UZS",
        "val": val,
        "cat": "qoldiq" if is_rest else "avans" if is_adv else guess_category(rest, categories),
        "ord": find_order(rest, order_ids),
        "com": rest,
    }


def safe_cell(s: str) -> str:
    """Text that starts with = + - @ is a formula in Excel — prefix it."""
    s = str(s or "")[:300]
    return "'" + s if re.match(r"^[=+\-@]", s) else s
