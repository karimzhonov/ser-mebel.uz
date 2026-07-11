import datetime

import pytest
from django.db import IntegrityError, transaction

from order.constants import OrderStatus
from order.forms import OrderAddForm
from order.models import Order


def test_end_date_excluded_from_order_add_form_fields():
    assert "end_date" not in OrderAddForm().fields


def _make_design_type(db_client):
    """design_type is a required OrderAddForm field with no model default, so
    every add-form submission needs a real DesignType. Creating a Design
    auto-creates one via metering.design.models.create_design_type_folders.
    """
    from metering.design.models import Design, DesignType
    from metering.models import Metering

    metering = Metering.objects.create(client=db_client, date_time=datetime.datetime.now())
    design = Design.objects.create(metering=metering)
    design_type = DesignType.objects.get(design=design)
    return metering, design_type


@pytest.mark.django_db
def test_order_add_form_valid_without_count_days_leaves_end_date_unset(db_client, today):
    metering, design_type = _make_design_type(db_client)
    data = {
        "client": db_client.pk,
        "reception_date": today.isoformat(),
        "address": "addr",
        "price_0": "0",
        "price_1": "USD",
        "lost_money_0": "0",
        "lost_money_1": "USD",
        "discount": "0",
        "status": OrderStatus.CREATED,
        "metering": metering.pk,
        "design_type": design_type.pk,
        # count_days deliberately omitted — it's optional
    }
    form = OrderAddForm(data=data)

    assert form.is_valid(), form.errors

    order = form.save()

    assert order.end_date is None
    assert order.status == OrderStatus.WAITING


@pytest.mark.django_db
def test_order_add_form_with_count_days_computes_end_date(db_client, today):
    metering, design_type = _make_design_type(db_client)
    data = {
        "client": db_client.pk,
        "reception_date": today.isoformat(),
        "address": "addr",
        "price_0": "0",
        "price_1": "USD",
        "lost_money_0": "0",
        "lost_money_1": "USD",
        "discount": "0",
        "status": OrderStatus.CREATED,
        "metering": metering.pk,
        "design_type": design_type.pk,
        "count_days": "5",
    }
    form = OrderAddForm(data=data)

    assert form.is_valid(), form.errors

    order = form.save()

    assert order.end_date == today + datetime.timedelta(days=5)
    assert order.status != OrderStatus.WAITING
    assert order.status == OrderStatus.CREATED


@pytest.mark.django_db
def test_end_date_nullable_defaults_status_waiting(order_factory):
    order = order_factory(end_date=None)

    assert order.end_date is None
    assert order.status == OrderStatus.WAITING


@pytest.mark.django_db
def test_order_exits_waiting_when_end_date_set(order_factory, today):
    order = order_factory(end_date=None)
    assert order.status == OrderStatus.WAITING

    order.end_date = today + datetime.timedelta(days=10)
    order.save()
    order.refresh_from_db()

    assert order.status == OrderStatus.CREATED


@pytest.mark.django_db
def test_blanking_end_date_on_in_progress_order_does_not_reset_to_waiting(order_factory, today):
    """Blanking end_date on an order that already progressed past WAITING/CREATED
    must not silently reset its status back to WAITING and lose that progress.
    resolve_order_status_on_save only forces WAITING on creation.
    """
    order = order_factory(end_date=today)
    order.status = OrderStatus.DETAILING
    order.save(update_fields=["status"])
    order.refresh_from_db()
    assert order.status == OrderStatus.DETAILING

    order.end_date = None
    order.save()
    order.refresh_from_db()

    assert order.end_date is None
    assert order.status == OrderStatus.DETAILING


@pytest.mark.django_db
def test_order_end_date_set_does_not_touch_non_waiting_status(order_factory, today):
    """resolve_order_status_on_save only promotes WAITING -> CREATED; it must not
    clobber a status that has already progressed further once end_date is (re)set.
    """
    order = order_factory(end_date=today)
    order.status = OrderStatus.DETAILING
    order.save(update_fields=["status"])
    order.refresh_from_db()
    assert order.status == OrderStatus.DETAILING

    order.end_date = today + datetime.timedelta(days=3)
    order.save()
    order.refresh_from_db()

    assert order.status == OrderStatus.DETAILING


@pytest.mark.django_db
def test_order_number_backfilled_and_unique(order_factory, db_client, today):
    order = order_factory()
    order.refresh_from_db()

    assert order.order_number == order.id

    order2 = order_factory()
    order2.refresh_from_db()
    assert order2.order_number == order2.id
    assert order2.order_number != order.order_number

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Order.objects.filter(pk=order2.pk).update(order_number=order.order_number)
