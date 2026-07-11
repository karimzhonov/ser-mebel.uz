import datetime

import pytest

from order.admin_display import (
    order_days_display,
    order_for_metering,
    order_ref_display,
    order_status_display,
)
from order.constants import OrderStatus


def test_order_ref_display_returns_dash_for_none():
    assert order_ref_display(None) == "-"


def test_order_status_display_returns_dash_for_none():
    assert order_status_display(None) == "-"


def test_order_days_display_returns_dash_for_none():
    assert order_days_display(None) == "-"


@pytest.mark.django_db
def test_order_ref_display_links_to_order_number(order_factory, today):
    order = order_factory(end_date=today + datetime.timedelta(days=3))

    result = str(order_ref_display(order))

    assert f"/admin/order/order/{order.pk}/change/" in result
    assert str(order.order_number) in result


@pytest.mark.django_db
def test_order_status_display_mirrors_order_admin(order_factory, today):
    order = order_factory(end_date=today + datetime.timedelta(days=3))

    result = str(order_status_display(order))

    assert str(OrderStatus(order.status).label) in result


@pytest.mark.django_db
def test_order_days_display_waiting_when_end_date_missing(order_factory):
    order = order_factory(end_date=None)
    order.refresh_from_db()

    assert order.status == OrderStatus.WAITING
    assert "Ожидание даты сдачи" in str(order_days_display(order))


@pytest.mark.django_db
def test_order_days_display_done_status(order_factory, today):
    order = order_factory(end_date=today + datetime.timedelta(days=3))
    order.status = OrderStatus.DONE
    order.save(update_fields=["status"])

    assert "Заказ готов" in str(order_days_display(order))


@pytest.mark.django_db
def test_order_days_display_computes_from_end_date_directly(order_factory, today):
    """order_days_display must not touch obj.days (the OrderManager annotation) —
    it must work even on an Order instance that was never fetched through
    Order.objects (e.g. reached via select_related() from another model)."""
    order = order_factory(end_date=today + datetime.timedelta(days=5))
    order.refresh_from_db()

    # Sanity: a plain refresh_from_db() does not go through OrderManager's
    # custom get_queryset(), so `days` is genuinely absent here.
    assert not hasattr(order, "days")

    result = str(order_days_display(order))

    assert "До сдачи заказа 5 дней" in result


@pytest.mark.django_db
def test_order_days_display_overdue(order_factory, today):
    order = order_factory(end_date=today - datetime.timedelta(days=2))
    order.refresh_from_db()

    result = str(order_days_display(order))

    assert "просрочен" in result


@pytest.mark.django_db
def test_order_for_metering_returns_none_for_none_metering():
    assert order_for_metering(None) is None


@pytest.mark.django_db
def test_order_for_metering_guards_metering_without_order(db_client):
    import datetime as dt

    from metering.models import Metering

    metering = Metering.objects.create(client=db_client, date_time=dt.datetime.now())

    # Must not raise Order.DoesNotExist.
    assert order_for_metering(metering) is None


@pytest.mark.django_db
def test_order_for_metering_returns_linked_order(db_client, today):
    import datetime as dt

    from metering.design.models import Design
    from metering.models import Metering
    from order.models import Order

    metering = Metering.objects.create(client=db_client, date_time=dt.datetime.now())
    Design.objects.create(metering=metering)
    order = Order.objects.create(
        client=db_client,
        reception_date=today,
        address="addr",
        metering=metering,
    )

    assert order_for_metering(metering) == order
