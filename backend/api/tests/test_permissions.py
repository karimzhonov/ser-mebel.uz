import pytest
from djmoney.money import Money

from order.constants import OrderStatus

pytestmark = pytest.mark.django_db


def test_list_needs_view_permission(api):
    assert api().get("/api/v1/orders/").status_code == 403
    assert api("order.view_order").get("/api/v1/orders/").status_code == 200


def test_price_hidden_without_view_order_price(api, order_factory):
    order = order_factory(price=Money(500, "USD"))
    plain = api("order.view_order").get(f"/api/v1/orders/{order.pk}/").data
    assert "price" not in plain and "money_left" not in plain
    full = api("order.view_order", "order.view_order_price").get(f"/api/v1/orders/{order.pk}/")
    assert full.data["price"] == {"amount": 500.0, "currency": "USD"}


def test_price_edit_refused_without_price_permission(api, order_factory):
    order = order_factory(price=Money(500, "USD"))
    client = api("order.view_order", "order.change_order")
    resp = client.patch(f"/api/v1/orders/{order.pk}/", {"price": 1}, format="json")
    assert resp.status_code == 403
    resp = client.patch(f"/api/v1/orders/{order.pk}/", {"desc": "ok"}, format="json")
    assert resp.status_code == 200 and resp.data["desc"] == "ok"


def test_action_needs_the_admin_permission(api, order_factory, today):
    order = order_factory(end_date=today)
    assert order.status == OrderStatus.CREATED
    viewer = api("order.view_order")
    assert viewer.post(f"/api/v1/orders/{order.pk}/detailing/").status_code == 403
    allowed = api("order.view_order", "detailing.add_detailing")
    assert allowed.post(f"/api/v1/orders/{order.pk}/detailing/").status_code == 200


def test_assembler_sees_only_own_jobs(api, make_staff, order_factory):
    from order.assembly.models import Assembly
    from order.models import Order

    mine = api("assembly.view_assembly")
    other = make_staff()
    Assembly.objects.create(order=order_factory(), square=1, user=mine.user)
    Assembly.objects.create(order=order_factory(), square=1, user=other)
    Order.objects.update(status="working")  # assembly work starts after detailing
    resp = mine.get("/api/v1/assemblies/")
    assert resp.data["count"] == 1


def test_old_income_expense_api_is_gone(admin_api):
    """Kirim/chiqim moved to Moliya (/finance/); the old ledger stays in the DB only."""
    for url in ("/api/v1/incomes/", "/api/v1/expenses/", "/api/v1/expense-categories/"):
        assert admin_api.get(url).status_code == 404


def test_closed_invoice_is_read_only(api):
    from call_center.constants import SolutionChoice
    from call_center.models import Invoice
    from client.models import Client

    client = Client.objects.create(phone="+998901110000", fio="X")
    invoice = Invoice.objects.create(client=client, solution=SolutionChoice.declined)
    user = api("call_center.view_invoice", "call_center.change_invoice")
    resp = user.patch(f"/api/v1/invoices/{invoice.pk}/", {"desc": "y"}, format="json")
    assert resp.status_code == 403


def test_users_endpoint_superuser_only(api, admin_api):
    assert api("oauth.view_user").get("/api/v1/users/").status_code == 403
    resp = admin_api.post(
        "/api/v1/users/",
        {"phone": "+998935551122", "name": "Usta", "password": "secret123", "is_staff": True},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert "password" not in resp.data
