"""«Qarzlar» bot channel: roles, parsing, pay semantics, contract fixtures."""

import pytest

from accounting import services as S
from accounting.models import Debt
from api.tests.botkit import load_fixture
from api.tests.test_bot_contract import keys, shape
from oauth.models import TelegramMember

pytestmark = pytest.mark.django_db

DATA = {
    "creditor": "X",
    "item": "Y",
    "amount_text": "1.5 mln",
    "category": "material",
    "order_ref": "406",
}


@pytest.fixture
def odd_members(db):
    return {
        "pending": TelegramMember.objects.create(telegram_id=501, name="P", role="pending"),
        "blocked": TelegramMember.objects.create(telegram_id=502, name="B", role="blocked"),
        "nowallet": TelegramMember.objects.create(
            telegram_id=503, name="NW", role="staff", wallet_mode="off"
        ),
    }


def test_list_for_active_and_refused_for_others(site_order, members, odd_members, bot_client):
    assert bot_client.get("finance/debts/", actor=200).status_code == 200
    assert bot_client.get("finance/debts/", actor=100).status_code == 200
    for tg in (501, 502):
        assert bot_client.get("finance/debts/", actor=tg).status_code == 403
    assert bot_client.get("finance/debts/", actor=999).status_code in (401, 403)
    assert bot_client.post("finance/debts/", actor=501, data=DATA).status_code == 403


def test_create_uzs_and_wallet_rules(site_order, members, odd_members, bot_client, bot_events):
    r = bot_client.post("finance/debts/", actor=200, data=DATA)
    assert r.status_code == 201, r.content
    j = r.json()
    assert j["currency"] == "UZS" and j["total"] == "1500000.00" and j["client"]
    assert not bot_events.of("finance.debt_created")  # owner: no notification
    assert Debt.objects.get().created_by.telegram_id == 200
    # a wallet-less non-admin may not add
    n = len(bot_events)
    assert bot_client.post("finance/debts/", actor=503, data=DATA).status_code == 403
    assert len(bot_events) == n
    # bad input -> 400
    assert (
        bot_client.post(
            "finance/debts/", actor=200, data={**DATA, "order_ref": "99999"}
        ).status_code
        == 400
    )
    assert (
        bot_client.post(
            "finance/debts/", actor=200, data={**DATA, "amount_text": "abc"}
        ).status_code
        == 400
    )
    assert (
        bot_client.post("finance/debts/", actor=200, data={**DATA, "creditor": ""}).status_code
        == 400
    )


def test_create_cannot_spoof_admin_category(site_order, members, bot_client):
    from accounting.models import FinanceCategory

    FinanceCategory.objects.filter(code="material").update(admin_only=True)
    assert bot_client.post("finance/debts/", actor=200, data=DATA).status_code == 400
    assert bot_client.post("finance/debts/", actor=100, data=DATA).status_code == 201


def test_pay_flow_statuses_and_balance(site_order, members, odd_members, bot_client, bot_events):
    boss, ali, _ = members
    d = S.create_debt(
        creditor="A",
        item="B",
        category_code="material",
        order_ref="406",
        amount=1000000,
        created_by=ali,
        actor_admin=True,
    )
    n = d.number
    assert bot_client.post(f"finance/debts/{n}/pay/", actor=503, data={}).status_code == 403
    assert bot_client.post(f"finance/debts/{n}/pay/", actor=501, data={}).status_code == 403
    assert bot_client.post("finance/debts/999/pay/", actor=200, data={}).status_code == 404
    part = bot_client.post(f"finance/debts/{n}/pay/", actor=200, data={"amount_text": "400000"})
    assert part.status_code == 200, part.content
    j = part.json()
    assert j["debt"]["status"] == "open" and j["debt"]["remaining"] == "600000.00"
    assert j["balance"] == "-400000.00" and j["operation"]["member"]["telegram_id"] == 200
    assert len(bot_events.of("finance.operation_created")) == 1
    over = bot_client.post(f"finance/debts/{n}/pay/", actor=200, data={"amount_text": "9 mln"})
    assert over.status_code == 400
    full = bot_client.post(f"finance/debts/{n}/pay/", actor=100, data={"amount_text": ""})
    assert full.status_code == 200 and full.json()["debt"]["status"] == "closed"
    assert full.json()["operation"]["member"]["telegram_id"] == 100  # the presser's own wallet
    assert bot_client.post(f"finance/debts/{n}/pay/", actor=200, data={}).status_code == 409


def test_usd_currency_mismatch_both_ways(site_order, members, bot_client):
    r = bot_client.post("finance/debts/", actor=200, data={**DATA, "amount_text": "300$"})
    n = r.json()["number"]
    assert r.json()["currency"] == "USD" and r.json()["total"] == "300.00"
    assert (
        bot_client.post(
            f"finance/debts/{n}/pay/", actor=200, data={"amount_text": "500000"}
        ).status_code
        == 400
    )
    ok = bot_client.post(f"finance/debts/{n}/pay/", actor=200, data={"amount_text": "100$"})
    assert ok.status_code == 200 and ok.json()["debt"]["remaining"] == "200.00"
    uz = S.create_debt(
        creditor="A",
        item="B",
        category_code="material",
        order_ref="406",
        amount=1000,
        created_by=members[1],
        actor_admin=True,
    )
    assert (
        bot_client.post(
            f"finance/debts/{uz.number}/pay/", actor=200, data={"amount_text": "10$"}
        ).status_code
        == 400
    )


def test_card_payments_and_can_pay(site_order, members, odd_members, bot_client):
    _, ali, _ = members
    d = S.create_debt(
        creditor="A",
        item="B",
        category_code="material",
        order_ref="406",
        amount=1000,
        created_by=ali,
        actor_admin=True,
    )
    j = bot_client.get(f"finance/debts/{d.number}/", actor=200).json()
    assert j["can_pay"] is True and j["payments"] == []
    assert bot_client.get(f"finance/debts/{d.number}/", actor=503).status_code == 403
    S.pay_debt(d, payer=ali, amount=400)
    j = bot_client.get(f"finance/debts/{d.number}/", actor=200).json()
    assert len(j["payments"]) == 1
    S.pay_debt(d, payer=ali)
    assert bot_client.get(f"finance/debts/{d.number}/", actor=200).json()["can_pay"] is False
    assert bot_client.get("finance/debts/777/", actor=200).status_code == 404
    assert bot_client.get(f"finance/debts/{d.number}/", actor=501).status_code == 403


def test_list_open_oldest_first_closed_and_totals(site_order, members, bot_client):
    from datetime import timedelta

    from accounting.text import today

    _, ali, _ = members
    new = S.create_debt(
        creditor="N",
        item="i",
        category_code="material",
        order_ref="406",
        amount=100,
        created_by=ali,
        actor_admin=True,
    )
    old = S.create_debt(
        creditor="O",
        item="i",
        category_code="material",
        order_ref="406",
        amount=200,
        created_by=ali,
        on_date=today() - timedelta(days=9),
        actor_admin=True,
    )
    done = S.create_debt(
        creditor="D",
        item="i",
        category_code="material",
        order_ref="406",
        amount=50,
        created_by=ali,
        actor_admin=True,
    )
    S.pay_debt(done, payer=ali)
    j = bot_client.get("finance/debts/", actor=200).json()
    assert [r["number"] for r in j["rows"]] == [old.number, new.number]
    assert j["totals"]["open_count"] == 2 and j["totals"]["open_uzs"] == "300.00"
    c = bot_client.get("finance/debts/?status=closed", actor=200).json()
    assert [r["number"] for r in c["rows"]] == [done.number]


# ------------------------------------------------------------------ fixtures parity
def test_pay_fixtures_match_real_responses(site_order, members, bot_client):
    created = bot_client.post("finance/debts/", actor=200, data={**DATA, "amount_text": "6 mln"})
    assert keys(load_fixture("misc.debt_create_request.json")) == set(DATA) | {"comment"}
    assert shape(created.json()) == shape(load_fixture("dto.debt.1.json"))
    n = created.json()["number"]
    req = load_fixture("misc.debt_pay_request.json")
    assert keys(req) == {"amount_text"}
    real = bot_client.post(f"finance/debts/{n}/pay/", actor=200, data=req)
    assert real.status_code == 200, real.content
    fx = load_fixture("misc.debt_pay_response.json")
    assert shape(real.json()) == shape(fx)
    assert shape(real.json()["debt"]) == shape(load_fixture("dto.debt.1.json"))
    one = bot_client.get(f"finance/debts/{n}/", actor=200).json()
    assert set(one) == set(load_fixture("dto.debt.1.json")) | {"payments", "can_pay"}


# ------------------------------------------------------------------ owner scoping
def _debt(by, amount=1000):
    return S.create_debt(
        creditor="A",
        item="B",
        category_code="material",
        order_ref="406",
        amount=amount,
        created_by=by,
        actor_admin=True,
    )


def test_staff_sees_and_pays_only_own_debts(site_order, members, bot_client, bot_events):
    boss, ali, vali = members
    mine = _debt(ali, 100)
    theirs = _debt(vali, 7000)
    j = bot_client.get("finance/debts/", actor=200).json()
    assert [r["number"] for r in j["rows"]] == [mine.number]
    assert j["totals"]["open_count"] == 1 and j["totals"]["open_uzs"] == "100.00"
    j = bot_client.get("finance/debts/?status=all", actor=200).json()
    assert [r["number"] for r in j["rows"]] == [mine.number]
    assert bot_client.get(f"finance/debts/{theirs.number}/", actor=200).status_code == 404
    n = len(bot_events)
    r = bot_client.post(f"finance/debts/{theirs.number}/pay/", actor=200, data={})
    assert r.status_code == 404
    assert len(bot_events) == n and S.balance(ali) == 0
    assert Debt.objects.get(pk=theirs.pk).status == "open"
    assert bot_client.get(f"finance/debts/{mine.number}/", actor=200).status_code == 200
    # the other staff member sees the mirror image
    j = bot_client.get("finance/debts/", actor=300).json()
    assert [r["number"] for r in j["rows"]] == [theirs.number]
    assert j["totals"]["open_uzs"] == "7000.00"


def test_boss_sees_and_pays_all_debts(site_order, members, bot_client):
    boss, ali, vali = members
    a = _debt(ali, 100)
    b = _debt(vali, 7000)
    j = bot_client.get("finance/debts/", actor=100).json()
    assert {r["number"] for r in j["rows"]} == {a.number, b.number}
    assert j["totals"]["open_count"] == 2 and j["totals"]["open_uzs"] == "7100.00"
    assert bot_client.get(f"finance/debts/{b.number}/", actor=100).status_code == 200
    for d in (a, b):
        r = bot_client.post(f"finance/debts/{d.number}/pay/", actor=100, data={})
        assert r.status_code == 200 and r.json()["debt"]["status"] == "closed"

