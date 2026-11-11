from decimal import Decimal

import pytest

from bot.rover.parse import note_ok, parse_amount


@pytest.mark.parametrize(
    "text,val",
    [
        ("250 000", 250000),
        ("250.000", 250000),
        ("250,000", 250000),
        ("1 200 000", 1200000),
        ("250000", 250000),
        ("250 000 so'm", 250000),
        ("1 200 000 сум", 1200000),
        ("5000 UZS", 5000),
        ("100 sum", 100),
        ("100 som", 100),
    ],
)
def test_accepts(text, val):
    assert parse_amount(text) == Decimal(val)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "0",
        "000",
        "-5000",
        "$100",
        "250.5",
        "250,5",
        "abc",
        "1234567890123",
        "12345678901",
        "12 5 ab",
    ],
)
def test_rejects(text):
    assert parse_amount(text) is None


def test_note_min():
    assert not note_ok("ab") and note_ok("abc") and not note_ok("x" * 2001)
