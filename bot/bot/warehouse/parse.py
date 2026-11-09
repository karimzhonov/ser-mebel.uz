"""Typed numbers of the warehouse flows. Pure functions (no Telegram, no I/O)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

MAX_DIGITS = 12
_THOUSANDS = re.compile(r"^\d{1,3}([.,]\d{3}){2,}$")
_GROUPED = re.compile(r"^\d{1,3}([.,]\d{3})+$")
_NUMBER = re.compile(r"^\d+([.,]\d+)?$")
_USD = ("$", "usd", "dollar", "dollor", "доллар")
_UZS = ("so'm", "som", "sum", "so`m", "so‘m", "soʻm", "uzs", "сум", "сўм")
# longest first, so «mln» is not eaten as «m»
_MULT = (
    ("million", 10**6),
    ("mlrd", 10**9),
    ("mln", 10**6),
    ("ming", 10**3),
    ("min", 10**3),
    ("млн", 10**6),
    ("k", 10**3),
    ("m", 10**6),
)


def _to_decimal(s: str) -> Decimal | None:
    s = s.strip()
    if _THOUSANDS.match(s):
        s = re.sub(r"[.,]", "", s)
    elif _NUMBER.match(s):
        s = s.replace(",", ".")
    else:
        return None
    if len(s.replace(".", "")) > MAX_DIGITS:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _squash(text: str) -> str:
    return re.sub(r"[\s  ]+", " ", (text or "").strip().lower())


def parse_qty(text: str, *, allow_zero: bool = False) -> Decimal | None:
    """«1,5», «1 200» -> Decimal (max 3 decimals). Zero / negative / garbage -> None."""
    s = _squash(text)
    if not s or s.startswith("-"):
        return None
    s = re.sub(r"(?<=\d) (?=\d{3}(\D|$))", "", s)  # «1 200»
    s = s.replace(" ", "")
    d = _to_decimal(s)
    if d is None or d.as_tuple().exponent < -3:
        return None
    if d == 0 and not allow_zero:
        return None
    return d


def parse_price(text: str) -> tuple[Decimal, str] | None:
    """«120000», «120 000 so'm», «12.5$», «$12,5», «1.2mln» -> (amount, "UZS"|"USD")."""
    s = _squash(text)
    if not s or s.startswith("-"):
        return None
    cur = "UZS"
    for w in _USD:
        if w in s:
            cur = "USD"
            s = s.replace(w, " ")
    for w in _UZS:
        if w in s:
            s = s.replace(w, " ")
    s = s.strip()
    mult = 1
    for w, m in _MULT:
        if s.endswith(w):
            mult = m
            s = s[: -len(w)].strip()
            break
    s = re.sub(r"(?<=\d) (?=\d{3}(\D|$))", "", s)
    s = s.replace(" ", "")
    if cur == "UZS" and mult == 1 and _GROUPED.match(s):
        s = re.sub(r"[.,]", "", s)  # «120.000» / «120,000» are thousands in so'm
    d = _to_decimal(s)
    if d is None or d <= 0:
        return None
    d = (d * mult).quantize(Decimal("0.01"))
    if d <= 0:
        return None
    return d, cur
