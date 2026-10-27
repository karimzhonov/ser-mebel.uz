"""The whole pipeline through the API, the way staff walk it in the admin:
call-centre → замер → дизайн → нарх → заказ → деталировка → сборка → готов."""

import pytest
from djmoney.money import Money

from call_center.constants import SolutionChoice
from metering.constants import MeteringStatus
from metering.price.models import Inventory, InventoryType, ObjectType
from order.constants import DEFAULT_FACTORY_NAME, OrderStatus
from order.models import Factory, Order

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog(db):
    kitchen = ObjectType.objects.create(name="Кухня", count_name="kv")
    facade = InventoryType.objects.create(name="Фасад", obj=kitchen, type=InventoryType.TYPE_KV)
    hinges = InventoryType.objects.create(name="Петли", obj=kitchen, type=InventoryType.TYPE_COUNT)
    mdf = Inventory.objects.create(name="МДФ", type=facade, price=Money(20, "USD"))
    blum = Inventory.objects.create(name="BLUM", type=hinges, price=Money(3, "USD"))
    return {"kitchen": kitchen, "facade": facade, "hinges": hinges, "mdf": mdf, "blum": blum}


def test_full_pipeline(admin_api, catalog):
    Factory.objects.get_or_create(name=DEFAULT_FACTORY_NAME)

    # Call-centre: a new lead creates the client on the fly.
    resp = admin_api.post(
        "/api/v1/invoices/",
        {"fio": "Ali Valiyev", "phone": "+998901112244", "desc": "Кухня"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    invoice_id = resp.data["id"]

    resp = admin_api.post(
        f"/api/v1/invoices/{invoice_id}/solution/",
        {"solution": SolutionChoice.re_phone},
        format="json",
    )
    assert resp.status_code == 200 and resp.data["solution"] == SolutionChoice.re_phone

    # "Замерга борилади" is only reachable by creating the metering.
    resp = admin_api.post(
        f"/api/v1/invoices/{invoice_id}/solution/",
        {"solution": SolutionChoice.go_for_measured},
        format="json",
    )
    assert resp.status_code == 400

    resp = admin_api.post(
        "/api/v1/meterings/",
        {
            "client_phone": "+998901112244",
            "date_time": "2026-10-25T10:00:00",
            "address": "Chilonzor",
            "invoice": invoice_id,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    metering_id = resp.data["id"]
    assert resp.data["folder"] is not None
    assert admin_api.get(f"/api/v1/invoices/{invoice_id}/").data["solution"] == (
        SolutionChoice.go_for_measured
    )

    resp = admin_api.post(f"/api/v1/meterings/{metering_id}/metering-done/")
    assert resp.status_code == 200 and resp.data["status"] == MeteringStatus.metering_done
    assert resp.data["actions"]["create_design"] is True

    resp = admin_api.post(f"/api/v1/meterings/{metering_id}/create-design/")
    design_id = resp.data["design"]["id"]
    resp = admin_api.post(f"/api/v1/meterings/{metering_id}/create-design/")
    assert resp.status_code == 400  # only one design per metering

    resp = admin_api.get(f"/api/v1/designs/{design_id}/")
    design_type_id = resp.data["types"][0]["id"]
    assert resp.data["actions"]["create_order"] is False  # not done yet
    resp = admin_api.post(f"/api/v1/designs/{design_id}/done/")
    assert resp.data["done"] is True and resp.data["actions"]["create_order"] is True

    # Price: 10 m² of МДФ at $20 + 4 BLUM hinges at $3 = $212.
    resp = admin_api.post(f"/api/v1/meterings/{metering_id}/create-price/")
    price_id = resp.data["price"]["id"]
    resp = admin_api.post(
        f"/api/v1/prices/{price_id}/calculations/",
        {
            "name": "Кухня 1",
            "count": 10,
            "object_type": catalog["kitchen"].pk,
            "items": [
                {"inventory_type": catalog["facade"].pk, "inventory": catalog["mdf"].pk},
                {
                    "inventory_type": catalog["hinges"].pk,
                    "inventory": catalog["blum"].pk,
                    "count": 4,
                },
            ],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.content
    assert resp.data["price"] == {"amount": 212.0, "currency": "USD"}
    calc = resp.data["calculations"][0]
    assert calc["amount"]["amount"] == 212.0 and len(calc["items"]) == 2

    # Changing the hinge count re-prices the calculation and the Price.
    resp = admin_api.patch(
        f"/api/v1/prices/{price_id}/calculations/{calc['id']}/",
        {
            "name": "Кухня 1",
            "count": 10,
            "object_type": catalog["kitchen"].pk,
            "items": [
                {"inventory_type": catalog["facade"].pk, "inventory": catalog["mdf"].pk},
                {
                    "inventory_type": catalog["hinges"].pk,
                    "inventory": catalog["blum"].pk,
                    "count": 10,
                },
            ],
        },
        format="json",
    )
    assert resp.data["price"]["amount"] == 230.0

    excel = admin_api.get(f"/api/v1/prices/{price_id}/excel/")
    assert excel.status_code == 200
    assert excel["Content-Type"].startswith("application/vnd.openxmlformats")

    # Order from the design.
    resp = admin_api.post(
        "/api/v1/orders/",
        {
            "metering": metering_id,
            "design_type": design_type_id,
            "address": "Chilonzor",
            "count_days": 30,
            "price": {"amount": 230, "currency": "USD"},
            "lost_money": {"amount": 100, "currency": "USD"},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    order_id = resp.data["id"]
    assert resp.data["status"] == OrderStatus.CREATED
    assert resp.data["money_left"] == {"amount": 130.0, "currency": "USD"}
    assert resp.data["factory"]["name"] == DEFAULT_FACTORY_NAME
    metering = admin_api.get(f"/api/v1/meterings/{metering_id}/").data
    assert metering["status"] == MeteringStatus.sold_out
    assert metering["order"]["id"] == order_id
    assert admin_api.get(f"/api/v1/invoices/{invoice_id}/").data["solution"] == (
        SolutionChoice.sold_out
    )

    # A second order for the same metering is refused.
    resp = admin_api.post(
        "/api/v1/orders/",
        {"metering": metering_id, "design_type": design_type_id, "address": "x"},
        format="json",
    )
    assert resp.status_code == 400

    # Production.
    resp = admin_api.post(f"/api/v1/orders/{order_id}/detailing/")
    assert resp.data["status"] == OrderStatus.DETAILING
    detailing_id = resp.data["production"]["detailing"]["id"]

    resp = admin_api.patch(
        f"/api/v1/detailings/{detailing_id}/", {"square": 12, "rover_square": 3}, format="json"
    )
    assert resp.status_code == 200, resp.content
    production = admin_api.get(f"/api/v1/orders/{order_id}/").data["production"]
    assert production["assembly"]["square"] == 12
    assert production["rover"]["square"] == 3

    resp = admin_api.post(f"/api/v1/detailings/{detailing_id}/done/")
    assert resp.data["done"] is True
    assert Order.objects.get(pk=order_id).status == OrderStatus.WORKING

    resp = admin_api.post(f"/api/v1/orders/{order_id}/go-to-assembly/")
    assert resp.status_code == 200 and resp.data["status"] == OrderStatus.ASSEMBLY
    assembly_id = resp.data["assembly_id"]

    resp = admin_api.post(f"/api/v1/assemblies/{assembly_id}/installing-done/")
    assert resp.status_code == 400  # assembly first
    admin_api.post(f"/api/v1/assemblies/{assembly_id}/done/")
    assert Order.objects.get(pk=order_id).status == OrderStatus.INSTALLING
    admin_api.post(f"/api/v1/assemblies/{assembly_id}/installing-done/")
    assert Order.objects.get(pk=order_id).status == OrderStatus.DONE

    history = admin_api.get(f"/api/v1/orders/{order_id}/history/")
    assert history.status_code == 200 and len(history.data) >= 2


def test_read_endpoints_respond(admin_api, catalog, order_factory):
    order_factory()
    for url in [
        "/api/v1/meta/",
        "/api/v1/dashboard/boards/",
        "/api/v1/orders/?status=created,waiting&period=month",
        "/api/v1/orders/stats/",
        "/api/v1/orders/?warning=danger",
        "/api/v1/meterings/stats/",
        "/api/v1/invoices/stats/?period=year",
        "/api/v1/invoices/?solution=new,1",
        "/api/v1/clients/",
        "/api/v1/clients/stats/",
        "/api/v1/designs/?done=false",
        "/api/v1/prices/?done=false",
        "/api/v1/inventory-types/?obj=%d" % catalog["kitchen"].pk,
        "/api/v1/detailings/stats/",
        "/api/v1/assemblies/assemblers/",
        "/api/v1/finance/summary/",
        "/api/v1/users/",
        "/api/schema/",
    ]:
        resp = admin_api.get(url)
        assert resp.status_code == 200, (url, resp.status_code, getattr(resp, "data", None))
    boards = admin_api.get("/api/v1/dashboard/boards/").data["boards"]
    assert [b["id"] for b in boards] == ["orders", "meterings", "callcenter"]


def test_client_detail_by_phone(admin_api, db_client):
    resp = admin_api.get("/api/v1/clients/+998901234567/related/")
    assert resp.status_code == 200
    assert set(resp.data) == {"invoices", "meterings", "orders"}
