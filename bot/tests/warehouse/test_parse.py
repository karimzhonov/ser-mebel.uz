from decimal import Decimal as D

import pytest

from bot.warehouse.parse import parse_price, parse_qty


@pytest.mark.parametrize(
    "text,want",
    [
        ("12", D("12")),
        ("1,5", D("1.5")),
        ("1.5", D("1.5")),
        ("1 200", D("1200")),
        (" 3 ", D("3")),
        ("0,25", D("0.25")),
    ],
)
def test_qty_ok(text, want):
    assert parse_qty(text) == want


@pytest.mark.parametrize("text", ["", "0", "-3", "abc", "1,5,5x", "1.2345", "12 kg"])
def test_qty_bad(text):
    assert parse_qty(text) is None


def test_qty_zero_allowed_for_minimum():
    assert parse_qty("0", allow_zero=True) == D("0")
    assert parse_qty("-1", allow_zero=True) is None


@pytest.mark.parametrize(
    "text,want",
    [
        ("120000", (D("120000"), "UZS")),
        ("120 000 so'm", (D("120000"), "UZS")),
        ("12.5$", (D("12.5"), "USD")),
        ("$12,5", (D("12.5"), "USD")),
        ("1.2mln", (D("1200000"), "UZS")),
        ("1 200 000", (D("1200000"), "UZS")),
        ("15 usd", (D("15"), "USD")),
        ("50k", (D("50000"), "UZS")),
    ],
)
def test_price_ok(text, want):
    assert parse_price(text) == want


@pytest.mark.parametrize("text", ["", "0", "-5", "narx", "$", "so'm", "12.5.5"])
def test_price_bad(text):
    assert parse_price(text) is None


@pytest.mark.parametrize("text", ["120.000", "120,000", "1.200.000", "1,200,000"])
def test_price_dot_comma_groups_are_thousands_in_som(text):
    amount, cur = parse_price(text)
    assert cur == "UZS" and amount in (D("120000"), D("1200000"))


def test_price_decimals_kept_for_usd_and_qty():
    assert parse_price("120.000$") == (D("120.000"), "USD")
    assert parse_price("12,5 usd") == (D("12.5"), "USD")
    assert parse_qty("1.500") == D("1.5")
