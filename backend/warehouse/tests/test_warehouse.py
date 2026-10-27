from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from accounting.tests.conftest import site_order  # noqa: F401
from api.tests.conftest import api, make_staff  # noqa: F401
from warehouse.models import Movement, Product

pytestmark = pytest.mark.django_db
URL = "/api/v1/warehouse"


@pytest.fixture
def admin(api):  # noqa: F811
    return api(superuser=True)


@pytest.fixture
def keeper(admin, make_staff):  # noqa: F811
    """A regular staff member with other access, made the omborchi by the owner."""
    other = Group.objects.create(name="Sotuv")
    user = make_staff("order.view_order")
    user.groups.add(other)
    r = admin.put(f"{URL}/keeper/", {"user": user.id}, format="json")
    assert r.status_code == 200 and r.data["keeper"]["id"] == user.id
    c = APIClient()
    from oauth.models import User

    c.force_authenticate(User.objects.get(pk=user.pk))
    c.user = user
    return c


def product(client, **kw):
    r = client.post(
        f"{URL}/products/",
        {"name": "LDSP oq 16mm", "unit": "list", "min_quantity": "5", **kw},
        format="json",
    )
    assert r.status_code == 201, r.data
    return r.data


def move(client, pid, kind, qty, price, **kw):
    return client.post(
        f"{URL}/movements/",
        {"product": pid, "kind": kind, "quantity": qty, "unit_price": price, **kw},
        format="json",
    )


def test_keeper_sees_only_the_warehouse(keeper):
    me = keeper.get("/api/v1/auth/me/").data
    assert me["is_warehouse_keeper"] is True
    assert all(p.startswith("warehouse.") for p in me["permissions"])  # other access removed
    assert keeper.get("/api/v1/orders/").status_code == 403
    assert keeper.get(f"{URL}/products/").status_code == 200


def test_stock_in_out_and_average_cost(keeper):
    p = product(keeper)
    assert move(keeper, p["id"], "in", "10", "100000", counterparty="Kronospan").status_code == 201
    assert move(keeper, p["id"], "in", "10", "120000").status_code == 201
    prod = Product.objects.get(pk=p["id"])
    assert prod.quantity == 20 and prod.avg_cost == Decimal("110000.00")
    r = move(keeper, p["id"], "out", "15", "110000", counterparty="Sex", comment="406 uchun")
    assert r.status_code == 201 and Decimal(r.data["balance_after"]) == 5
    r = move(keeper, p["id"], "out", "6", "110000")
    assert r.status_code == 400 and "yetarli emas" in str(r.data)
    s = keeper.get(f"{URL}/summary/").data
    assert Decimal(s["stock_value"]) == Decimal("550000.00") and s["is_keeper"] is True
    assert s["low_stock"][0]["name"] == "LDSP oq 16mm"  # 5 <= min 5


def test_cancel_recomputes_and_refuses_negative(keeper):
    p = product(keeper)
    m_in = move(keeper, p["id"], "in", "10", "100").data
    move(keeper, p["id"], "out", "8", "100")
    r = keeper.post(f"{URL}/movements/{m_in['id']}/cancel/")
    assert r.status_code == 400  # the chiqim would have nothing to take from
    out = Movement.objects.get(kind="out")
    assert keeper.post(f"{URL}/movements/{out.id}/cancel/").status_code == 200
    assert Product.objects.get(pk=p["id"]).quantity == 10
    assert keeper.post(f"{URL}/movements/{out.id}/cancel/").status_code == 400


def test_only_the_keeper_writes(admin, keeper, api):  # noqa: F811
    p = product(keeper)
    # the owner (superuser) looks but doesn't book
    assert admin.get(f"{URL}/products/").status_code == 200
    assert move(admin, p["id"], "in", "1", "1").status_code == 400
    assert (
        admin.post(f"{URL}/products/", {"name": "X", "unit": "dona"}, format="json").status_code
        == 400
    )
    # someone with warehouse permissions who is not THE keeper
    other = api("warehouse.view_product", "warehouse.add_movement", "warehouse.view_movement")
    assert move(other, p["id"], "in", "1", "1").status_code == 400
    assert api().get(f"{URL}/products/").status_code == 403


def test_reassign_keeper_moves_access(admin, keeper, make_staff):  # noqa: F811
    new = make_staff()
    admin.put(f"{URL}/keeper/", {"user": new.id}, format="json")
    from oauth.models import User

    old = User.objects.get(pk=keeper.user.pk)
    assert not old.groups.filter(name="Omborchi").exists()
    assert User.objects.get(pk=new.pk).groups.filter(name="Omborchi").exists()
    assert (
        admin.put(f"{URL}/keeper/", {"user": admin.user.id}, format="json").status_code == 400
    )  # not a superuser


def test_keeper_cannot_be_set_by_non_superuser(keeper):
    assert keeper.put(f"{URL}/keeper/", {"user": keeper.user.id}, format="json").status_code == 403


def test_product_rules(keeper):
    p = product(keeper, code="L16")
    r = keeper.post(
        f"{URL}/products/", {"name": "Boshqa", "code": "l16", "unit": "dona"}, format="json"
    )
    assert r.status_code == 400
    move(keeper, p["id"], "in", "1", "1")
    assert keeper.delete(f"{URL}/products/{p['id']}/").status_code == 400  # has history
    r = keeper.patch(f"{URL}/products/{p['id']}/", {"is_active": False}, format="json")
    assert r.status_code == 200 and move(keeper, p["id"], "in", "1", "1").status_code == 400


def test_order_link_and_export(keeper, site_order):  # noqa: F811
    p = product(keeper)
    move(keeper, p["id"], "in", "5", "1000")
    r = move(keeper, p["id"], "out", "2", "1000", order_number=406)
    assert r.data["order_number"] == 406
    assert move(keeper, p["id"], "out", "1", "1000", order_number=99999).status_code == 400
    x = keeper.get(f"{URL}/export/")
    assert x.status_code == 200 and x.content[:2] == b"PK"


# ---------------------------------------------------------------- review fixes
def test_product_edit_never_restores_old_stock(keeper):
    from warehouse import services as W

    p = product(keeper)
    move(keeper, p["id"], "in", "10", "100")
    stale = Product.objects.get(pk=p["id"])  # the edit form was opened here (qty 10)
    move(keeper, p["id"], "out", "5", "100")
    W.save_product(keeper.user, {"name": "LDSP oq 16 mm (yangi)"}, stale)
    fresh = Product.objects.get(pk=p["id"])
    assert fresh.quantity == 5 and fresh.name == "LDSP oq 16 mm (yangi)"


def test_cancel_rewrites_later_balances(keeper):
    p = product(keeper)
    move(keeper, p["id"], "in", "10", "100")
    second = move(keeper, p["id"], "in", "5", "100").data
    out = move(keeper, p["id"], "out", "3", "100").data
    assert Decimal(out["balance_after"]) == 12
    keeper.post(f"{URL}/movements/{second['id']}/cancel/")
    assert Movement.objects.get(pk=out["id"]).balance_after == 7


def test_keeper_groups_only_from_warehouse_page(admin, keeper):
    other = Group.objects.create(name="Boshqa")
    r = admin.patch(f"/api/v1/users/{keeper.user.id}/", {"groups": [other.id]}, format="json")
    assert r.status_code == 400


def test_old_keeper_loses_login_when_warehouse_was_all(admin, keeper, make_staff):  # noqa: F811
    from oauth.models import User

    keeper_id = keeper.user.id
    admin.put(f"{URL}/keeper/", {"user": make_staff().id}, format="json")
    assert User.objects.get(pk=keeper_id).is_staff is False


def test_bad_inputs_are_400_not_500(admin, keeper):
    assert admin.put(f"{URL}/keeper/", {"user": "abc"}, format="json").status_code == 400
    p = product(keeper)
    assert move(keeper, p["id"], "in", "99999999999", "99999999999").status_code == 400


# ---------------------------------------------------------------- dollars
def test_dollar_and_som_purchases_average_together(keeper):
    from constance import config

    config.FIN_USD_RATE = 12000.0
    p = product(keeper)
    r = keeper.post(
        f"{URL}/movements/",
        {"product": p["id"], "kind": "in", "quantity": "10", "currency": "USD", "orig_price": "10"},
        format="json",
    )
    assert r.status_code == 201, r.data
    assert (r.data["currency"], Decimal(r.data["rate"]), Decimal(r.data["unit_price"])) == (
        "USD",
        Decimal("12000"),
        Decimal("120000.00"),
    )
    move(keeper, p["id"], "in", "10", "100000")  # so'm
    prod = keeper.get(f"{URL}/products/{p['id']}/").data
    assert Decimal(prod["avg_cost"]) == Decimal("110000.00")
    assert prod["avg_cost_usd"] == round(110000 / 12000, 2)
    # a dollar chiqim at a rate typed by the keeper
    r = keeper.post(
        f"{URL}/movements/",
        {
            "product": p["id"],
            "kind": "out",
            "quantity": "2",
            "currency": "USD",
            "orig_price": "11",
            "rate": "12500",
        },
        format="json",
    )
    assert Decimal(r.data["total"]) == Decimal("275000.00") and Decimal(r.data["rate"]) == Decimal(
        "12500"
    )
    s = keeper.get(f"{URL}/summary/").data
    assert s["stock_value_usd"] == round(18 * 110000 / 12000, 2)


def test_dollar_price_is_required(keeper):
    p = product(keeper)
    r = keeper.post(
        f"{URL}/movements/",
        {"product": p["id"], "kind": "in", "quantity": "1", "currency": "USD"},
        format="json",
    )
    assert r.status_code == 400 and "orig_price" in r.data
    r = keeper.post(
        f"{URL}/movements/", {"product": p["id"], "kind": "in", "quantity": "1"}, format="json"
    )
    assert r.status_code == 400 and "unit_price" in r.data


def test_zero_rate_is_refused_not_replaced(keeper):
    from warehouse import services as W

    p = product(keeper)
    r = keeper.post(
        f"{URL}/movements/",
        {
            "product": p["id"],
            "kind": "in",
            "quantity": "1",
            "currency": "USD",
            "orig_price": "10",
            "rate": "0",
        },
        format="json",
    )
    assert r.status_code == 400 and "rate" in r.data
    with pytest.raises(W.ServiceError):
        W.add_movement(
            keeper.user,
            product=Product.objects.get(pk=p["id"]),
            kind="in",
            quantity=1,
            currency="USD",
            orig_price=10,
            rate=0,
        )
    assert not Movement.objects.exists()
