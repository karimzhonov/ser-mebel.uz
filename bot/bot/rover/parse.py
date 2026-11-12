"""Typed amount of the rover job (UZS integers only)."""

from __future__ import annotations

import re
from decimal import Decimal

MAX_DIGITS = 10
NOTE_MIN = 3
NOTE_MAX = 2000

_SUFFIX = re.compile(r"(so['`ʻʼ’]?m|sum|som|uzs|сум|сўм)\.?$", re.I)
_GROUPED = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")
_SPACES = re.compile(r"[\s   ]+")


def parse_amount(text) -> Decimal | None:
    """«250 000», «250.000», «250,000», «1 200 000 so'm» -> Decimal; None when not a
    positive whole sum of at most 10 digits (fractions, signs, currency signs are refused)."""
    s = _SPACES.sub("", str(text or "")).strip()
    s = _SUFFIX.sub("", s)
    if _GROUPED.match(s):
        s = re.sub(r"[.,]", "", s)
    if not s.isascii() or not s.isdigit():
        return None
    s = s.lstrip("0")
    if not s or len(s) > MAX_DIGITS:
        return None
    return Decimal(s)


def note_ok(text) -> bool:
    t = str(text or "").strip()
    return NOTE_MIN <= len(t) <= NOTE_MAX
