"""Finance rules in accounting.services / accounting.text (ported from the old bot tests,
which exercised them through Telegram updates)."""

from datetime import date
from decimal import Decimal

import pytest

from accounting import services as S
from accounting.models import Operation
from accounting.text import parse_amount, parse_money, parse_quick
from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- parsing (same as code.txt)
@pytest.mark.parametrize(
    "text,expected",
    [
        ("150000", 150000),
        ("150 000", 150000),
        ("150k", 150000),
        ("150 ming", 150000),
        ("1.5 mln", 1500000),
        ("1,5mln", 1500000),
        ("2 000 000 so'm", 2000000),
        ("4200.50", 4200),
        ("12.5", Decimal("12.5")),
        ("abc", None),
        ("0", None),
    ],
)
def test_parse_amount(text, expected):
    got = parse_amount(text)
    assert (got is None) if expected is None else got == Decimal(str(expected))


def test_parse_money_detects_dollars():
    assert parse_money("100$") == (Decimal("100"), "USD")
    assert parse_money("250 ming") == (Decimal("250000"), "UZS")


def test_parse_quick_entry(db):
    cats = S.categories()
    q = parse_quick("350000 furnitura 406 petlya", ["406"], cats)
    assert (
        q["kind"] == "expense"
        and q["cat"] == "furnitura"
        and q["ord"] == "406"
        and q["val"] == 350000
    )
    q = parse_quick("4200$ avans Назира 406", ["406"], cats)
    assert q["kind"] == "income" and q["cat"] == "avans" and q["cur"] == "USD"
    q = parse_quick("2000000 oylik Dilmurod", [], cats)
    assert q["cat"] == "oylik"


# ---------------------------------------------------------------- rates, handover, transfers
def test_usd_rate_failure_is_cached(db, monkeypatch, settings):
    from constance import config
    from django.core.cache import cache

    cache.clear()
    config.FIN_USD_RATE = 0.0
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise OSError("down")

    monkeypatch.setattr("accounting.services.requests.get", boom)
    assert S.usd_rate() == Decimal(str(config.USD_CURRENCY))
    S.usd_rate()
    assert len(calls) == 1
    cache.clear()


def test_set_usd_rate_validates(members):
    from constance import config

    assert S.set_usd_rate("12 500,5") == Decimal("12500.5") and config.FIN_USD_RATE == 12500.5
    for bad in ("abc", "-1", "2000000"):
        with pytest.raises(ServiceError):
            S.set_usd_rate(bad)


def test_handover_rejects_non_collection_rows(members):
    boss, ali, _ = members
    op = S.create_operation(
        member=ali, author=ali, kind="expense", amount=1000, category_code="ovqat"
    )
    with pytest.raises(ServiceError):
        S.handover_drop(op)
    with pytest.raises(ServiceError):
        S.handover_accept(op, boss)


def test_handover_cannot_be_answered_twice_or_by_staff(members):
    boss, ali, vali = members
    op = S.create_operation(
        member=ali,
        author=ali,
        kind="income",
        amount=1000,
        category_code="qoldiq",
        comment="Pul oldim (mijozdan qoldiq)",
        internal=True,
    )
    with pytest.raises(ServiceForbidden):
        S.handover_accept(op, vali)
    S.handover_accept(op, boss)
    with pytest.raises(ServiceConflict):
        S.handover_accept(op, boss)
    with pytest.raises(ServiceConflict):
        S.handover_drop(op)


def test_dropped_handover_cannot_be_restored(members):
    _, ali, _ = members
    op = S.create_operation(
        member=ali,
        author=ali,
        kind="income",
        amount=1000,
        category_code="qoldiq",
        comment="Pul oldim (mijozdan qoldiq)",
        internal=True,
    )
    S.handover_drop(op)
    with pytest.raises(ServiceError):
        S.restore_operation(Operation.objects.get(pk=op.pk))


def test_transfer_kind_cannot_be_edited(members):
    _, ali, vali = members
    out, inc = S.create_transfer(sender=ali, receiver=vali, amount=1000)
    with pytest.raises(ServiceError):
        S.update_operation(out, {"category_code": "ovqat"}, actor_admin=True)
    S.update_operation(out, {"amount": 2000}, actor_admin=True)
    inc.refresh_from_db()
    assert inc.amount == 2000


def test_transfer_deletes_both_halves(members):
    _, ali, vali = members
    out, inc = S.create_transfer(sender=ali, receiver=vali, amount=300000, author=ali)
    assert inc.pair_id == out.id and S.balance(vali) == 300000
    assert len(S.delete_operation(out)) == 2
    inc.refresh_from_db()
    assert inc.is_deleted


# ---------------------------------------------------------------- rules moved out of the router
def test_create_operation_as_enforces_roles_server_side(members):
    boss, ali, vali = members
    s = S.create_operation_as(ali, ali, kind="expense", amount=1000, category_code="ovqat")
    assert s.author_id == ali.id and s.member_id == ali.id
    with pytest.raises(ServiceForbidden):
        S.create_operation_as(ali, vali, kind="expense", amount=1000, category_code="ovqat")
    with pytest.raises(ServiceError):  # admin-only category, spoofed flag is dropped
        S.create_operation_as(
            ali, ali, kind="expense", amount=1000, category_code="uy", actor_admin=True
        )
    op = S.create_operation_as(boss, vali, kind="income", amount=1000, category_code="rahbar")
    assert op.member_id == vali.id and op.author_id == boss.id
    ali.is_feedback = True
    with pytest.raises(ServiceForbidden):  # task-only members don't book money
        S.create_operation_as(ali, ali, kind="expense", amount=1000, category_code="ovqat")


def test_salary_pay_type_is_the_bosses_choice(members):
    boss, ali, _ = members
    staff = S.create_operation_as(
        ali, ali, kind="expense", amount=1000, category_code="oylik", pay_type="Oylik", worker="X"
    )
    assert staff.pay_type == "Avans"
    chief = S.create_operation_as(
        boss, ali, kind="expense", amount=1000, category_code="oylik", pay_type="Oylik", worker="X"
    )
    assert chief.pay_type == "Oylik"


def test_attach_receipt_rules(members):
    boss, ali, vali = members
    op = S.create_operation(
        member=ali, author=ali, kind="expense", amount=1000, category_code="ovqat"
    )
    with pytest.raises(ServiceForbidden):
        S.attach_receipt(op, "F", vali)
    assert S.attach_receipt(op, "F", ali).receipt_file_id == "F"
    assert S.attach_receipt(op, "G", boss).receipt_file_id == "G"
    with pytest.raises(ServiceError):
        S.attach_receipt(op, "", ali)


def test_duty_recipients_fall_back_to_admins(members):
    boss, ali, vali = members
    got, fallback = S.duty_recipients("is_bonus_receiver")
    assert got == [vali] and fallback is False
    got, fallback = S.duty_recipients("is_feedback")
    assert got == [boss] and fallback is True


def test_month_report_target_prefers_the_open_month(members, monkeypatch):
    boss, ali, _ = members
    monkeypatch.setattr("accounting.services.today", lambda: date(2026, 11, 3))
    assert S.month_report_target(ali) == "2026-10"
    S.submit_month(ali, "2026-10")
    assert S.month_report_target(ali) == "2026-11"
    monkeypatch.setattr("accounting.services.today", lambda: date(2026, 11, 20))
    assert S.month_report_target(ali) == "2026-11"


def test_manual_order_price_and_toggle(members):
    mo = S.create_manual_order("SM-001", "Nazira", "", 0)
    assert S.set_manual_price("sm-001", "9 mln").price == 9_000_000
    assert S.toggle_manual_order("SM-001").is_closed is True
    assert S.toggle_manual_order("SM-001").closed is None
    with pytest.raises(ServiceError):
        S.set_manual_price("406", "1000")
    assert mo.pk


def test_request_amount_and_messages(members):
    _, ali, _ = members
    req = S.request_money(ali, "300$", "LDSP")
    assert req.currency == "USD" and req.orig_amount == 300
    assert S.request_amount(req)["amount"] == 300 * 12000
    assert S.request_amount(req, "250$")["orig"] == 250
    S.set_request_messages(req, [["100", "9"]])
    req.refresh_from_db()
    assert req.admin_messages == [[100, 9]]
    with pytest.raises(ServiceForbidden):  # the boss has a wallet, task-only people don't
        ali.is_site_entry = True
        S.request_money(ali, "100")


def test_feedback_photo_is_recorded_once(members, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    fb = S.receive_feedback_photo("389", "Ali", "zo'r", "F1", b"\xff\xd8 jpeg")
    assert fb.status == "received" and fb.screenshot_url.endswith(".jpg")
    with pytest.raises(ServiceConflict):
        S.receive_feedback_photo("389", "Ali", "", "F2", None)
    assert S.rename_member(members[1], "  Jasur ").name == "Jasur"


def test_wallets_overview_counts_staff_only_in_the_total(members):
    boss, ali, vali = members
    S.create_operation(member=ali, kind="income", amount=1000, category_code="boshqa_kirim")
    S.create_operation(
        member=boss,
        author=boss,
        kind="expense",
        amount=400,
        category_code="ovqat",
        actor_admin=True,
    )
    w = S.wallets_overview()
    by = {r["member"].name: r for r in w["rows"]}
    assert by["Ali"]["balance"] == 1000 and by["Rahbar"]["month_spent"] == 400
    assert w["staff_total"] == 1000 and w["pending"] == []
    assert set(S.staff()) == {ali, vali}
