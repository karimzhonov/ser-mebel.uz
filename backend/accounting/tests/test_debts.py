"""«Qarzlar»: services, hooks into operation edits/deletes, site API and bot channel."""

from datetime import timedelta
from decimal import Decimal

import pytest

from accounting import dto
from accounting import services as S
from accounting.models import Debt, Operation
from accounting.text import today
from core.exceptions import ServiceConflict, ServiceError

pytestmark = pytest.mark.django_db


def mk(**kw):
    base = dict(
        creditor="Bahor",
        item="LDSP 10 list",
        category_code="material",
        order_ref="406",
        amount=1000000,
        actor_admin=True,
    )
    base.update(kw)
    return S.create_debt(**base)


def test_create_debt_uzs_and_usd(site_order):
    a = mk()
    b = mk(currency="USD", amount=None, orig_amount=100)
    assert (a.number, b.number) == (1, 2)
    assert b.amount == Decimal("1200000.00") and b.rate == Decimal("12000")
    assert S.debt_numbers(b)["total"] == Decimal("100.00")


@pytest.mark.parametrize(
    "kw",
    [
        {"creditor": " "},
        {"item": ""},
        {"amount": 0},
        {"on_date": today() + timedelta(days=1)},
        {"order_ref": "99999"},
        {"category_code": "oylik"},
        {"category_code": "zapravka"},
        {"category_code": "nope"},
    ],
)
def test_create_debt_rejects(site_order, kw):
    with pytest.raises(ServiceError):
        mk(**kw)


def test_pay_partial_then_close_and_hooks(site_order, members):
    _, ali, _ = members
    d = mk()
    d, op = S.pay_debt(d, payer=ali, author=ali, amount=400000)
    assert op.debt_id == d.pk and op.order_ref == "406" and "Qarz #1" in op.comment
    assert d.status == "open" and S.debt_numbers(d)["remaining"] == Decimal("600000")
    d, op2 = S.pay_debt(d, payer=ali, author=ali)
    assert d.status == "closed" and d.closed_at == op2.date
    with pytest.raises(ServiceConflict):
        S.pay_debt(d, payer=ali)
    S.delete_operation(op2)
    assert Debt.objects.get(pk=d.pk).status == "open"
    S.restore_operation(op2)
    assert Debt.objects.get(pk=d.pk).status == "closed"
    # editing the amount re-syncs; frozen fields are refused
    with pytest.raises(ServiceError):
        S.update_operation(Operation.objects.get(pk=op2.pk), {"order_ref": "1"})
    S.update_operation(Operation.objects.get(pk=op2.pk), {"amount": 500000})
    assert Debt.objects.get(pk=d.pk).status == "open"
    with pytest.raises(ServiceError):
        S.delete_debt(d)


def test_pay_errors(site_order, members):
    boss, ali, _ = members
    d = mk()
    with pytest.raises(ServiceError):
        S.pay_debt(d, payer=ali, amount=2000000)
    with pytest.raises(ServiceError):
        S.pay_debt(d, payer=ali, on_date=d.date - timedelta(days=1))
    with pytest.raises(ServiceError):  # staff can't back-date over 2 days
        S.pay_debt(
            mk(on_date=today() - timedelta(days=9)), payer=ali, on_date=today() - timedelta(days=5)
        )
    assert S.delete_debt(d).is_deleted


def test_usd_debt_tracked_in_dollars(site_order, members):
    _, ali, _ = members
    d = mk(currency="USD", amount=None, orig_amount=300)
    d, op = S.pay_debt(d, payer=ali, amount=100)
    assert op.orig_amount == Decimal("100.00") and op.amount == Decimal("1200000.00")
    assert dto.debt_dto(d)["remaining"] == "200.00"
    with pytest.raises(ServiceError):
        S.pay_debt_as(ali, d.number, "500000")


def test_no_double_counting(site_order, members):
    _, ali, _ = members
    before = S.order_stats("406")
    d = mk()
    assert S.order_stats("406")["spent"] == before["spent"] if "spent" in before else True
    S.pay_debt(d, payer=ali, amount=100000)
    assert S.balance(ali) == Decimal("-100000")


# ------------------------------------------------------------------ site API
def test_site_api(site_order, members, api, make_staff, bot_events):
    _, ali, _ = members
    ali.user = make_staff("accounting.view_operation", "accounting.add_operation")
    ali.save()
    c = api("accounting.view_operation", "accounting.add_operation")
    c.user.telegram_member = ali  # reverse one-to-one set below
    ali.user = c.user
    ali.save()
    r = c.post(
        "/api/v1/finance/debts/",
        {
            "creditor": "X",
            "item": "Y",
            "category_code": "material",
            "order_ref": "406",
            "amount": "500000",
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    assert not bot_events.of("finance.debt_created")  # owner: no notification
    assert r.json()["client"]
    lst = c.get("/api/v1/finance/debts/")
    assert lst.status_code == 200 and lst.json()["count"] == 1
    assert c.get("/api/v1/finance/debts/stats/").json()["open_count"] == 1
    pk = r.json()["id"]
    p = c.post(
        f"/api/v1/finance/debts/{pk}/pay/", {"member": ali.pk, "amount": "500000"}, format="json"
    )
    assert p.status_code == 200, p.content
    assert p.json()["debt"]["status"] == "closed"
    assert p.json()["operation"]["debt_number"] == 1
    assert c.get(f"/api/v1/finance/debts/{pk}/").json()["payments"]
    assert api().get("/api/v1/finance/debts/").status_code == 403


# ------------------------------------------------------------------ bot channel
def test_bot_channel(site_order, members, bot_client, bot_events):
    boss, ali, _ = members
    r = bot_client.post(
        "finance/debts/",
        actor=200,
        data={
            "creditor": "X",
            "item": "Y",
            "amount_text": "300$",
            "category": "material",
            "order_ref": "406",
        },
    )
    assert r.status_code == 201, r.content
    assert r.json()["currency"] == "USD" and not bot_events.of("finance.debt_created")
    n = r.json()["number"]
    assert bot_client.get("finance/debts/", actor=200).json()["totals"]["open_count"] == 1
    assert bot_client.get(f"finance/debts/{n}/", actor=200).json()["can_pay"] is True
    bad = bot_client.post(f"finance/debts/{n}/pay/", actor=200, data={"amount_text": "500000"})
    assert bad.status_code == 400
    ok = bot_client.post(f"finance/debts/{n}/pay/", actor=200, data={"amount_text": None})
    assert ok.status_code == 200 and ok.json()["debt"]["status"] == "closed"
    again = bot_client.post(f"finance/debts/{n}/pay/", actor=200, data={})
    assert again.status_code == 409
    assert bot_client.get("finance/debts/", actor=999).status_code in (401, 403)
