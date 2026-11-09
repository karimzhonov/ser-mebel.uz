from decimal import Decimal

import pytest

from accounting import services as S
from accounting.constants import WAREHOUSE_CAT
from api.tests.botkit import site_order  # noqa: F401
from api.tests.conftest import make_staff  # noqa: F401
from core.exceptions import ServiceError
from warehouse import services as W
from warehouse.models import Movement, MovementAllocation
from warehouse.tests.test_photos import keeper  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def stock(keeper):  # noqa: F811
    p = W.save_product(keeper, {"name": "Petlya", "unit": "dona"})
    W.add_movement(keeper, product=p, kind="in", quantity=100, unit_price=1000)
    return p


@pytest.fixture
def manual(db):
    from accounting.models import ManualOrder

    return ManualOrder.objects.create(ref="SM-003", client="Qo'lda mijoz", price=Decimal("5000000"))


def out(keeper, p, lines, **kw):  # noqa: F811
    return W.add_movement(keeper, product=p, kind="out", allocations=lines, **kw)


def test_two_clients_one_movement(keeper, stock, site_order, manual):  # noqa: F811
    m = out(keeper, stock, [{"ref": "406", "quantity": "4"}, {"ref": "sm-003", "quantity": "2"}])
    stock.refresh_from_db()
    assert stock.quantity == 94 and m.quantity == 6 and m.total == 6000
    assert Movement.objects.filter(kind="out").count() == 1
    lines = list(m.allocations.all())
    assert [(a.order_ref, a.quantity, a.total) for a in lines] == [
        ("406", Decimal("4"), Decimal("4000")),
        ("SM-003", Decimal("2"), Decimal("2000")),
    ]
    assert lines[0].order_id == site_order.id and lines[1].order_id is None
    assert lines[1].client == "Qo'lda mijoz" and lines[0].client


@pytest.mark.parametrize(
    "lines,field",
    [
        ([{"ref": "999999", "quantity": "1"}], "allocations"),
        ([{"ref": "406", "quantity": "1"}, {"ref": "#406", "quantity": "1"}], "allocations"),
        ([{"ref": "406", "quantity": "0"}], "allocations"),
        ([{"ref": "406", "quantity": "500"}], "quantity"),
    ],
)
def test_allocation_errors_write_nothing(keeper, stock, site_order, lines, field):  # noqa: F811
    with pytest.raises(ServiceError) as e:
        out(keeper, stock, lines)
    assert e.value.field == field
    stock.refresh_from_db()
    assert stock.quantity == 100 and not MovementAllocation.objects.exists()


def test_kirim_quantity_mismatch_and_limit(keeper, stock, site_order):  # noqa: F811
    with pytest.raises(ServiceError) as e:
        W.add_movement(
            keeper,
            product=stock,
            kind="in",
            unit_price=1,
            allocations=[{"ref": "406", "quantity": "1"}],
        )
    assert e.value.field == "allocations"
    with pytest.raises(ServiceError) as e:
        out(keeper, stock, [{"ref": "406", "quantity": "1"}], quantity=2)
    assert e.value.field == "quantity"
    with pytest.raises(ServiceError) as e:
        out(keeper, stock, [{"ref": "406", "quantity": "1"}] * 21)
    assert e.value.field == "allocations"


def test_no_client_and_single_client_paths(keeper, stock, site_order):  # noqa: F811
    m = W.add_movement(keeper, product=stock, kind="out", quantity=3)
    assert m.allocations.count() == 0
    m2 = out(keeper, stock, [{"ref": "406", "quantity": "1.5"}])
    assert m2.quantity == Decimal("1.5") and m2.allocations.count() == 1


def test_spending_cancel_and_stats(keeper, stock, site_order):  # noqa: F811
    m = out(keeper, stock, [{"ref": "406", "quantity": "4"}])
    W.add_movement(keeper, product=stock, kind="in", quantity=1, unit_price=1)
    assert W.order_spending(["406", "x"]) == {"406": Decimal("4000")}
    assert W.allocation_refs() == {"406"}
    lines = W.order_spending_lines("406")
    assert lines[0]["number"] == m.number and lines[0]["total"] == 4000
    st = S.order_stats("406")
    assert st["spent"] == 4000 and st["warehouse"] == 4000 and st["cats"][WAREHOUSE_CAT] == 4000
    assert len(st["warehouse_rows"]) == 1
    bulk = S.order_stats_bulk(["406"])
    assert bulk["406"]["spent"] == 4000 and bulk["406"]["warehouse"] == 4000
    W.cancel_movement(keeper, m)
    assert W.order_spending(["406"]) == {} and W.allocation_refs() == set()
    assert S.order_stats("406")["spent"] == 0


def test_order_choices_and_resolve(keeper, site_order, manual):  # noqa: F811
    refs = [o["ref"] for o in W.order_choices()]
    assert "406" in refs and "SM-003" in refs
    assert [o["ref"] for o in W.order_choices("qo'lda")] == ["SM-003"]
    res = W.resolve_refs("406, sm-003 999")
    assert [o["ref"] for o in res["items"]] == ["406", "SM-003"] and res["unknown"] == ["999"]


def test_checks_warns_on_warehouse_only_order(keeper, stock, site_order):  # noqa: F811
    from djmoney.money import Money

    site_order.price = Money(1, "USD")
    site_order.save()
    out(keeper, stock, [{"ref": "406", "quantity": "50"}])
    assert any("406" in c["title"] for c in S.checks())


def test_data_migration_function(keeper, stock, site_order):  # noqa: F811
    import importlib

    from django.apps import apps

    m = W.add_movement(keeper, product=stock, kind="out", quantity=2)
    Movement.objects.filter(pk=m.pk).update(order=site_order)
    mod = importlib.import_module("warehouse.migrations.0005_movement_order_to_allocation")
    mod.forwards(apps, None)
    a = MovementAllocation.objects.get()
    assert a.order_ref == "406" and a.quantity == 2 and a.total == m.total
    mod.backwards(apps, None)
    assert not MovementAllocation.objects.exists()


def test_bonus_ignores_warehouse_spending(keeper, stock, site_order):  # noqa: F811
    """The bonus is contract x percent: a chiqim given to the order must not change it."""
    from accounting.text import today

    def finish():
        info = S.order_info("406")
        b, _ = S.bonus_start(info, today())
        return S.bonus_finish(b, "test")

    before = finish()
    expected = (before.bonus, before.percent, before.total)
    type(before).objects.all().delete()
    out(keeper, stock, [{"ref": "406", "quantity": "50"}])
    after = finish()
    assert (after.bonus, after.percent, after.total) == expected
