# ruff: noqa: F811, F401  (pytest fixtures are imported and re-used by name)
import io

import pytest
from openpyxl import load_workbook
from rest_framework.test import APIClient

from accounting import services as S
from api.tests.botkit import bot_client, load_fixture, members, site_order  # noqa: F401
from api.tests.conftest import api, make_staff  # noqa: F401
from warehouse import services as W
from warehouse.tests.test_warehouse import (  # noqa: F401
    URL,
    admin,  # noqa: F401
    keeper,
)

pytestmark = pytest.mark.django_db
TG = 5550002


@pytest.fixture
def stocked(keeper):  # noqa: F811
    r = keeper.post(f"{URL}/products/", {"name": "Petlya", "unit": "dona"}, format="json")
    pid = r.data["id"]
    keeper.post(
        f"{URL}/movements/",
        {"product": pid, "kind": "in", "quantity": "50", "unit_price": "1000"},
        format="json",
    )
    return pid


def test_site_movement_allocations_filter_and_export(keeper, stocked, site_order):  # noqa: F811
    r = keeper.post(
        f"{URL}/movements/",
        {
            "product": stocked,
            "kind": "out",
            "unit_price": "1000",
            "allocations": [{"ref": "406", "quantity": "4"}],
        },
        format="json",
    )
    assert r.status_code == 201, r.data
    assert r.data["allocations"][0]["ref"] == "406" and "order_number" not in r.data
    assert keeper.post(
        f"{URL}/movements/", {"product": stocked, "kind": "out", "unit_price": "1"}, format="json"
    ).data["quantity"]
    lst = keeper.get(f"{URL}/movements/?order=406")
    assert [m["number"] for m in lst.data["results"]] == [r.data["number"]]
    assert keeper.get(f"{URL}/movements/?search=406").data["count"] == 1
    bad = keeper.post(
        f"{URL}/movements/",
        {
            "product": stocked,
            "kind": "out",
            "unit_price": "1",
            "allocations": [{"ref": "77777", "quantity": "1"}],
        },
        format="json",
    )
    assert bad.status_code == 400 and bad.data["field"] == "allocations"
    ws = load_workbook(io.BytesIO(keeper.get(f"{URL}/export/").content))["Harakatlar"]
    assert any("406×4" in str(c.value) for row in ws.iter_rows() for c in row)


def test_orders_options_permission(keeper, site_order, make_staff):  # noqa: F811
    r = keeper.get(f"{URL}/orders/")
    assert r.status_code == 200 and any(o["ref"] == "406" for o in r.data)
    nobody = APIClient()
    nobody.force_authenticate(make_staff())
    assert nobody.get(f"{URL}/orders/").status_code == 403


def test_finance_site_order_shows_warehouse(keeper, stocked, site_order, admin):  # noqa: F811
    keeper.post(
        f"{URL}/movements/",
        {
            "product": stocked,
            "kind": "out",
            "unit_price": "1000",
            "allocations": [{"ref": "406", "quantity": "4"}],
        },
        format="json",
    )
    lst = admin.get("/api/v1/finance/orders/?bucket=jarayonda")
    row = next(r for r in lst.data["results"] if r["ref"] == "406")
    assert row["warehouse_spent"] == 4000 and row["spent"] == 4000
    cat = next(c for c in row["by_category"] if c["code"] == "_ombor")
    assert cat["name"] == "Furnitura (ombor)" and cat["emoji"] == "📦"
    det = admin.get("/api/v1/finance/orders/406/").data
    assert det["warehouse"][0]["product"] == "Petlya" and det["warehouse"][0]["total"] == 4000


def test_tugadi_bucket_lists_warehouse_only_order(keeper, stocked, site_order, admin):  # noqa: F811
    from order.models import Order

    Order.objects.filter(pk=site_order.pk).update(status="done")
    keeper.post(
        f"{URL}/movements/",
        {
            "product": stocked,
            "kind": "out",
            "unit_price": "1",
            "allocations": [{"ref": "406", "quantity": "1"}],
        },
        format="json",
    )
    lst = admin.get("/api/v1/finance/orders/?bucket=tugadi,yakun")
    assert any(r["ref"] == "406" for r in lst.data["results"])


def bot_keeper(make_staff):  # noqa: F811
    u = make_staff()
    u.telegram_id = TG
    u.save(update_fields=["telegram_id"])
    W.assign_keeper(u)
    return u


def test_bot_orders_resolve_and_post(
    bot_client, make_staff, site_order, settings, tmp_path
):  # noqa: F811
    settings.MEDIA_ROOT = tmp_path
    k = bot_keeper(make_staff)
    p = W.save_product(k, {"name": "Vint", "unit": "dona"})
    W.add_movement(k, product=p, kind="in", quantity=20, unit_price=500)
    items = bot_client.get("warehouse/orders/?q=406", actor=TG).data["items"]
    assert set(items[0]) == set(load_fixture("dto.wh_order_ref.1.json"))
    res = bot_client.post("warehouse/orders/resolve/", actor=TG, data={"text": "406 999"})
    assert res.status_code == 200 and res.data["unknown"] == ["999"]
    assert set(res.data) == set(load_fixture("misc.wh_orders_resolve_response.json"))
    mv = bot_client.post(
        "warehouse/movements/",
        actor=TG,
        data={"product": p.pk, "kind": "out", "allocations": [{"ref": "406", "quantity": "3"}]},
    )
    assert mv.status_code == 201, mv.data
    assert set(mv.data["movement"]) == set(load_fixture("dto.wh_movement.1.json"))
    assert mv.data["movement"]["allocations"][0] == {
        "ref": "406",
        "client": mv.data["movement"]["allocations"][0]["client"],
        "quantity": "3.000",
        "total": "1500.00",
    }
    bad = bot_client.post(
        "warehouse/movements/",
        actor=TG,
        data={"product": p.pk, "kind": "out", "allocations": [{"ref": "1", "quantity": "1"}]},
    )
    assert bad.status_code == 400 and bad.data["field"] == "allocations"


def test_bot_orders_keeper_only(bot_client, make_staff):  # noqa: F811
    assert bot_client.get("warehouse/orders/", actor=991).status_code == 403
    assert (
        bot_client.post("warehouse/orders/resolve/", actor=991, data={"text": "1"}).status_code
        == 403
    )


def test_bot_finance_card_has_warehouse(
    bot_client, members, make_staff, site_order, settings, tmp_path
):  # noqa: F811
    settings.MEDIA_ROOT = tmp_path
    k = bot_keeper(make_staff)
    p = W.save_product(k, {"name": "Vint", "unit": "dona"})
    W.add_movement(k, product=p, kind="in", quantity=20, unit_price=500)
    W.add_movement(k, product=p, kind="out", allocations=[{"ref": "406", "quantity": "2"}])
    from api.tests.test_bot_finance_api import ALI

    card = bot_client.get("finance/orders/406/", actor=ALI).data
    assert card["stats"]["warehouse"] == "1000.00" and card["stats"]["spent"] == "1000.00"
    assert {"code": "_ombor", "name": "Furnitura (ombor)", "emoji": "📦", "sum": "1000.00"} in card[
        "stats"
    ]["cats"]
    assert S.order_stats("406")["warehouse"] == 1000
