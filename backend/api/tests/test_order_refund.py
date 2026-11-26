"""«↩️ Qaytim» with an order ID lowers that order's spent (it is not client money)."""

from decimal import Decimal

import pytest

from accounting import services as S
from accounting.models import ManualOrder

pytestmark = pytest.mark.django_db


def op(members, kind, cat, amount, ref="370"):
    return S.create_operation(
        member=members[0],
        kind=kind,
        amount=amount,
        category_code=cat,
        order_ref=ref,
        actor_admin=True,
    )


def test_refund_with_an_id_lowers_the_order_cost(members):
    ManualOrder.objects.create(ref="370", client="Ulug'bek", price=10_000_000)
    op(members, "expense", "material", 2_000_000)
    op(members, "income", "qaytim", 300_000)
    st = S.order_stats("370")
    assert st["spent"] == Decimal("1700000")
    assert st["cats"]["qaytim"] == Decimal("-300000")
    assert st["collected"] == 0  # not the client's money
    bulk = S.order_stats_bulk(["370"])["370"]
    assert bulk["spent"] == Decimal("1700000") and bulk["collected"] == 0
