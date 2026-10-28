from datetime import date, datetime, timedelta

import pytest
from djmoney.money import Money

pytestmark = pytest.mark.django_db


def _invoice(client, created):
    from call_center.models import Invoice

    inv = Invoice.objects.create(client=client)
    Invoice.objects.filter(pk=inv.pk).update(create_date=created)  # auto_now_add
    return inv


def test_date_range_filters_lists_inclusively(admin_api, db_client):
    _invoice(db_client, datetime(2026, 10, 1, 9))
    _invoice(db_client, datetime(2026, 10, 10, 18))
    _invoice(db_client, datetime(2026, 10, 20, 12))
    resp = admin_api.get("/api/v1/invoices/?date_from=2026-10-01&date_to=2026-10-10")
    assert resp.data["count"] == 2
    stats = admin_api.get("/api/v1/invoices/stats/?date_from=2026-10-10&date_to=2026-10-20").data
    assert stats["total"] == 2
    assert [p["date"] for p in stats["timeline"]] == ["2026-10-10", "2026-10-20"]  # daily


def test_date_range_validation(admin_api):
    assert (
        admin_api.get("/api/v1/orders/?date_from=2026-10-10&date_to=2026-10-01").status_code == 400
    )
    assert admin_api.get("/api/v1/orders/?date_from=10.10.2026").status_code == 400


def test_long_range_groups_by_month(admin_api, db_client):
    _invoice(db_client, datetime(2026, 1, 5, 9))
    _invoice(db_client, datetime(2026, 1, 25, 9))
    _invoice(db_client, datetime(2026, 6, 1, 9))
    stats = admin_api.get("/api/v1/invoices/stats/?date_from=2026-01-01&date_to=2026-12-31").data
    assert [p["value"] for p in stats["timeline"]] == [2.0, 1.0]


def test_overview_funnel_follows_one_metering_cohort(admin_api, db_client, default_factory):
    from metering.constants import MeteringStatus
    from metering.design.models import Design
    from metering.models import Metering
    from order.models import Order

    t = date.today()
    _invoice(db_client, datetime.now())
    m1 = Metering.objects.create(client=db_client, date_time=datetime.now() + timedelta(days=1))
    m2 = Metering.objects.create(client=db_client, date_time=datetime.now() - timedelta(days=1))
    Metering.objects.filter(pk=m1.pk).update(status=MeteringStatus.metering_done)
    Design.objects.create(metering=m1)
    Design.objects.filter(metering=m1).update(done=True)
    Order.objects.create(
        client=db_client,
        reception_date=t,
        end_date=t - timedelta(days=2),
        address="x",
        metering=m1,
        factory=default_factory,
        price=Money(1000, "USD"),
        lost_money=Money(400, "USD"),
    )
    data = admin_api.get(f"/api/v1/dashboard/overview/?date_from={t}&date_to={t}").data

    steps = {s["key"]: s["count"] for s in data["funnel"]["steps"]}
    assert steps == {
        "invoices": 1,
        "meterings": 2,
        "measured": 1,
        "design": 1,
        "price": 0,
        "sold": 1,
    }
    assert data["orders"]["overdue"] == 1
    assert data["orders"]["new"] == 1
    assert data["orders"]["deadlines"][0]["deadline"]["level"] == "danger"
    assert data["money"]["debt"] == [{"amount": 600.0, "currency": "USD"}]
    assert data["meterings"]["missed"] == 1  # m2: date passed, still "created"
    assert len(data["meterings"]["upcoming"]) == 0  # m1 is measured already
    assert {"invoices", "meterings", "orders"} == set(data["timeline"]["series"])
    assert m2  # cohort member counted in "meterings"


def test_overview_hides_blocks_without_permission(api):
    data = api("order.view_order").get("/api/v1/dashboard/overview/").data
    assert data["orders"] is not None
    for block in ("money", "funnel", "accounting", "meterings", "call_center", "production"):
        assert data[block] is None, block
    assert data["timeline"]["series"] == ["orders"]


def test_money_needs_order_view_too(api, order_factory):
    order_factory(price=Money(100, "USD"))
    only_price = api("order.view_order_price").get("/api/v1/dashboard/overview/").data
    assert only_price["money"] is None
    both = api("order.view_order", "order.view_order_price").get("/api/v1/dashboard/overview/").data
    assert both["money"]["contracts"] == [{"amount": 100.0, "currency": "USD"}]


def test_funnel_design_and_price_steps_need_their_permissions(api):
    keys = [
        s["key"]
        for s in api("metering.view_metering")
        .get("/api/v1/dashboard/overview/")
        .data["funnel"]["steps"]
    ]
    assert keys == ["meterings", "measured", "sold"]


def test_overdue_card_matches_danger_list(admin_api, order_factory):
    t = date.today()
    order_factory(end_date=t - timedelta(days=3))  # CREATED + overdue
    data = admin_api.get("/api/v1/dashboard/overview/").data
    listed = admin_api.get("/api/v1/orders/?warning=danger").data["count"]
    assert data["orders"]["overdue"] == listed == 1


def test_board_order_card_has_total_for_left_percent(admin_api, order_factory):
    order_factory(price=Money(1000, "USD"), end_date=date.today())
    from order.models import Order

    Order.objects.update(lost_money=Money(400, "USD"))
    boards = admin_api.get("/api/v1/dashboard/boards/").data["boards"]
    cards = [c for col in boards[0]["columns"] for c in col["cards"]]
    assert cards[0]["total"] == {"amount": 1000.0, "currency": "USD"}
    assert cards[0]["left"] == {"amount": 600.0, "currency": "USD"}  # 60% left


def test_overview_warehouse_hr_wallets_blocks(admin_api):
    from hr.models import Employee
    from oauth.models import TelegramMember, TelegramRole
    from warehouse.models import Product

    Product.objects.create(name="Plita", unit="dona", min_quantity=5)
    Employee.objects.create(telegram_id=1001, number=1, name="Ali")
    TelegramMember.objects.create(telegram_id=2001, name="Vali", role=TelegramRole.STAFF)

    data = admin_api.get("/api/v1/dashboard/overview/").data
    assert data["warehouse"]["products"] == 1
    assert data["warehouse"]["low_count"] == 1  # 0 left, minimum 5
    assert data["warehouse"]["low_stock"][0]["name"] == "Plita"
    assert "expected" in data["hr"] and "attention" in data["hr"]
    assert data["wallets"]["count"] == 1
    assert data["wallets"]["rows"][0]["balance"] == 0


def test_overview_new_blocks_need_their_permissions(api):
    data = api("order.view_order").get("/api/v1/dashboard/overview/").data
    assert data["warehouse"] is None
    assert data["hr"] is None
    assert data["wallets"] is None
