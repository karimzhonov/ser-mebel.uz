"""Stage 3: umumiy xarajat shared over the orders by contract sum, fixed on the Готов
day, the company cars as overhead, and «Foyda yechish» only from paid orders."""

from datetime import date
from decimal import Decimal

import pytest
from constance import config

from accounting import overhead as OH
from accounting import services as S
from accounting.models import ManualOrder, Operation, OrderOverhead

pytestmark = pytest.mark.django_db

URL = "/api/v1/finance/overhead/"


@pytest.fixture(autouse=True)
def _setup(db, monkeypatch):
    config.FIN_USD_RATE = 12000.0
    config.FIN_OVERHEAD_SINCE = "2026-09-01"
    config.FIN_BOSS_SALARY = 2_000_000
    monkeypatch.setattr(OH, "today", lambda: date(2026, 12, 10))


def op(members, kind, cat, amount, on, ref="", worker="", pay_type=""):
    return S.create_operation(
        member=members[0],
        kind=kind,
        amount=amount,
        category_code=cat,
        order_ref=ref,
        worker=worker,
        pay_type=pay_type,
        on_date=on,
        actor_admin=True,
    )


def manual(ref, price, closed=None):
    return ManualOrder.objects.create(
        ref=ref, client=ref, price=price, is_closed=bool(closed), closed=closed
    )


@pytest.fixture
def october(members):
    """October 2026: 3 400 000 of overhead, and order 370 with 500 000 direct cost."""
    manual("370", 30_000_000)
    oct10 = date(2026, 10, 10)
    op(members, "expense", "material", 1_000_000, oct10)  # no ID: overhead
    op(members, "expense", "material", 500_000, oct10, ref="370")  # direct
    op(members, "expense", "mashina", 200_000, oct10, ref="370", worker="Elyor")  # company car
    op(members, "income", "qaytim", 100_000, oct10)  # refund without ID
    op(members, "expense", "oylik", 300_000, oct10, worker="Umid", pay_type="Avans")
    return oct10


def test_month_overhead_collects_what_belongs_to_no_client(october):
    m = OH.month_overhead("2026-10")
    parts = {p["key"]: p["amount"] for p in m["parts"]}
    assert parts == {
        "general": 1_000_000,
        "refunds": -100_000,
        "cars": 200_000,
        "wallet_salary": 300_000,
        "boss": 2_000_000,
    }
    assert m["total"] == Decimal("3400000")
    # the company car left the order even though it was typed with its ID
    assert S.order_stats("370")["spent"] == Decimal("500000")
    assert S.order_stats_bulk(["370"])["370"]["spent"] == Decimal("500000")


def test_share_is_contract_times_the_rate_of_the_3_months_before_and_frozen(october):
    config.FIN_BOSS_SALARY = 0  # October alone: 1 400 000 of overhead
    manual("M1", 10_000_000, closed=date(2026, 10, 20))  # Готов in the window
    manual("M2", 5_000_000, closed=date(2026, 12, 5))
    # window Sep–Nov: 1 400 000 overhead ÷ 10 000 000 sold = 0.14
    assert OH.assign_pending() == 2  # M1 (window Jul–Sep, rate 0) and M2
    share = OrderOverhead.objects.get(order_ref="M2")
    assert share.rate == Decimal("0.140000") and share.amount == Decimal("700000")
    assert (share.window_start, share.window_end) == (date(2026, 9, 1), date(2026, 11, 30))
    assert OrderOverhead.objects.get(order_ref="M1").amount == 0
    # frozen: more overhead later does not change it, and a rerun adds nothing
    config.FIN_BOSS_SALARY = 9_000_000
    assert OH.assign_pending() == 0
    share.refresh_from_db()
    assert share.amount == Decimal("700000")


def test_orders_before_the_start_get_no_share(october):
    manual("OLD", 1_000_000, closed=date(2026, 8, 20))
    OH.assign_pending()
    assert not OrderOverhead.objects.filter(order_ref="OLD").exists()


def test_order_card_shows_net_profit(admin_api, october):
    config.FIN_BOSS_SALARY = 0
    manual("M1", 10_000_000, closed=date(2026, 10, 20))
    manual("M2", 5_000_000, closed=date(2026, 12, 5))
    OH.assign_pending()
    r = admin_api.get("/api/v1/finance/orders/M2/")
    assert r.status_code == 200, r.data
    assert r.data["overhead"] == 700_000 and r.data["net_profit"] == 4_300_000


def test_profit_only_from_paid_orders_and_never_above_the_pool_or_wallet(
    api, admin_api, members, october
):
    config.FIN_BOSS_SALARY = 0
    manual("M1", 10_000_000, closed=date(2026, 10, 20))
    manual("M2", 5_000_000, closed=date(2026, 12, 5))  # closed by hand = paid in full
    OH.assign_pending()
    pool = OH.profit_pool()
    assert {r["ref"] for r in pool["paid_orders"]} == {"M1", "M2"}
    # cash-safe: what the paid orders brought over their direct cost (15 000 000) minus
    # ALL the real overhead since the start (Oct: 1 400 000), minus nothing taken yet
    assert pool["gross"] == Decimal("15000000") and pool["overhead"] == Decimal("1400000")
    assert pool["available"] == Decimal("13600000")
    boss = members[0]
    boss.user = admin_api.user  # the boss's own wallet is the only one he takes from
    boss.save()
    rep = admin_api.get(URL)
    assert rep.status_code == 200, rep.data
    assert rep.data["can_withdraw"] is True and rep.data["pool"]["available"] == 13_600_000
    assert [w["id"] for w in rep.data["wallets"]] == [boss.pk]
    other = admin_api.post(f"{URL}withdraw/", {"member": members[1].pk, "amount": "1000"}, format="json")
    assert other.status_code == 403
    op(members, "income", "rahbar", 50_000_000, date(2026, 12, 1))  # cash in the wallet
    too_much = admin_api.post(
        f"{URL}withdraw/", {"member": boss.pk, "amount": "13600001"}, format="json"
    )
    assert too_much.status_code == 400
    ok = admin_api.post(f"{URL}withdraw/", {"member": boss.pk, "amount": "1000000"}, format="json")
    assert ok.status_code == 201, ok.data
    w = Operation.objects.get(number=ok.data["number"])
    assert w.category.code == "foyda" and w.category.excluded and w.order_ref == ""
    assert OH.profit_pool()["available"] == Decimal("12600000")
    # «Foyda yechish» is booked only here, never as a plain operation
    from core.exceptions import ServiceError

    with pytest.raises(ServiceError):
        op(members, "expense", "foyda", 1000, date(2026, 12, 2))
    # not company overhead either
    assert "general" not in {p["key"] for p in OH.month_overhead("2026-12")["parts"]}
    nobody = api("accounting.view_finance_summary", "accounting.view_all_operations")
    assert nobody.get(URL).data["can_withdraw"] is False
    assert nobody.post(f"{URL}withdraw/", {"member": boss.pk, "amount": "1"}).status_code == 403


def test_an_unpaid_order_waits(members, october):
    config.FIN_BOSS_SALARY = 0
    manual("M1", 10_000_000, closed=date(2026, 10, 20))
    OH.assign_pending()
    ManualOrder.objects.filter(ref="M1").update(is_closed=False)
    pool = OH.profit_pool()
    assert [r["ref"] for r in pool["waiting"]] == ["M1"] and pool["gross"] == 0


def test_the_boss_salary_rows_are_not_overhead(members):
    from accounting.models import Worker

    Worker.objects.create(group="Rahbar", name="Mirmuxammad", is_boss=True)
    op(members, "expense", "oylik", 7_000_000, date(2026, 10, 3), worker="Mirmuxammad", pay_type="Oylik")
    parts = {p["key"]: p["amount"] for p in OH.month_overhead("2026-10")["parts"]}
    assert "wallet_salary" not in parts and parts["boss"] == 2_000_000


def test_a_month_waits_for_its_settle_day(monkeypatch, october):
    config.FIN_BOSS_SALARY = 0
    manual("M2", 5_000_000, closed=date(2026, 12, 3))
    monkeypatch.setattr(OH, "today", lambda: date(2026, 12, 5))  # before the 10th
    assert OH.assign_pending() == 0
    monkeypatch.setattr(OH, "today", lambda: date(2026, 12, 10))
    assert OH.assign_pending() == 1


def test_wages_already_on_the_orders_are_not_overhead_again(admin_api, members, october):
    """An approved sheet of a month before the start: its ID part is on the clients, so
    the wallet salary of that worker must not be counted as overhead as well."""
    from accounting.models import Worker

    config.FIN_OVERHEAD_SINCE = "2026-12-01"
    w = Worker.objects.create(group="Sborka", name="Dilmurod", position="usta")
    r = admin_api.post(
        "/api/v1/finance/salary-sheets/", {"worker": w.pk, "kind": "sborka", "month": "2026-10"}, format="json"
    )
    sid = r.data["id"]
    admin_api.patch(
        f"/api/v1/finance/salary-sheets/{sid}/",
        {"lines": [{"section": "job", "order_ref": "370", "amount": "4000000"}]},
        format="json",
    )
    assert admin_api.post(f"/api/v1/finance/salary-sheets/{sid}/approve/").status_code == 200
    op(members, "expense", "oylik", 4_000_000, date(2026, 11, 5), worker="Dilmurod", pay_type="Oylik")
    parts = {p["key"]: p["amount"] for p in OH.month_overhead("2026-11")["parts"]}
    assert "wallet_salary" not in parts  # paid against October's sheet


def test_the_boss_salary_above_the_fixed_one_is_a_withdrawal(members, october):
    from accounting.models import Worker

    config.FIN_BOSS_SALARY = 5_000_000
    Worker.objects.create(group="Rahbar", name="Mirmuxammad", is_boss=True)
    op(members, "expense", "oylik", 4_000_000, date(2026, 10, 3), worker="Mirmuxammad", pay_type="Oylik")
    op(members, "expense", "oylik", 3_000_000, date(2026, 10, 20), worker="Mirmuxammad", pay_type="Uy uchun")
    op(members, "expense", "oylik", 2_000_000, date(2026, 11, 3), worker="Mirmuxammad", pay_type="Oylik")
    # October 7 000 000 − 5 000 000 = 2 000 000 above; November 2 000 000 is within it
    assert OH.boss_over_salary() == Decimal("2000000")
    assert OH.withdrawn() == Decimal("2000000")


def test_stock_bought_for_the_warehouse_is_neither_overhead_nor_an_order_cost(members):
    manual("370", 30_000_000)
    o = op(members, "expense", "omborga", 3_000_000, date(2026, 10, 7), ref="370")
    assert o.order_ref == ""  # never on an order: it reaches one through the warehouse
    assert S.balance(members[0]) == -3_000_000  # the wallet paid it
    parts = {p["key"] for p in OH.month_overhead("2026-10")["parts"]}
    assert "general" not in parts
    assert S.order_stats("370")["spent"] == 0


def test_a_category_limited_to_some_wallets(admin_api, members):
    from accounting.models import FinanceCategory
    from core.exceptions import ServiceError

    boss, ali, vali = members
    cat = FinanceCategory.objects.get(code="omborga")
    r = admin_api.patch(f"/api/v1/finance/categories/{cat.pk}/", {"members": [ali.pk]}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["members"] == [ali.pk]
    S.create_operation(member=ali, kind="expense", amount=1000, category_code="omborga", actor_admin=True)
    with pytest.raises(ServiceError):
        S.create_operation(member=vali, kind="expense", amount=1000, category_code="omborga", actor_admin=True)
    # moving it to another wallet is refused too
    other = S.create_operation(member=vali, kind="expense", amount=1000, category_code="material", actor_admin=True)
    with pytest.raises(ServiceError):
        S.update_operation(other, {"category_code": "omborga"}, actor_admin=True)
    # the bot's list says who may use it
    from accounting import dto

    row = dto.category_dto(FinanceCategory.objects.get(code="omborga"), with_wallets=True)
    assert row["only_tg"] == [ali.telegram_id]
    # emptied again: everyone may
    admin_api.patch(f"/api/v1/finance/categories/{cat.pk}/", {"members": []}, format="json")
    S.create_operation(member=vali, kind="expense", amount=1000, category_code="omborga", actor_admin=True)
