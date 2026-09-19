"""Item 3: the Metering changelist shows how much of the linked order is still
unpaid ("Остаток денег")."""

import datetime

import pytest
from django.contrib import admin
from djmoney.money import Money

from metering.admin import MeteringAdmin
from metering.models import Metering
from order.admin_display import order_money_left_display
from order.constants import DEFAULT_FACTORY_NAME
from order.models import Factory, Order


def _order_for(db_client, metering, price=None, lost_money=None):
    return Order.objects.create(
        client=db_client,
        reception_date=datetime.date.today(),
        address="addr",
        metering=metering,
        price=price,
        lost_money=lost_money,
        factory=Factory.objects.get_or_create(name=DEFAULT_FACTORY_NAME)[0],
    )


@pytest.mark.django_db
def test_money_left_is_total_minus_paid(db_client):
    metering = Metering.objects.create(client=db_client, date_time=datetime.datetime.now())
    order = _order_for(db_client, metering, price=Money(100, "USD"), lost_money=Money(30, "USD"))

    assert order_money_left_display(order) == Money(70, "USD")


@pytest.mark.django_db
def test_money_left_treats_missing_payment_as_zero(db_client):
    metering = Metering.objects.create(client=db_client, date_time=datetime.datetime.now())
    order = _order_for(db_client, metering, price=Money(100, "USD"), lost_money=None)

    assert order_money_left_display(order) == Money(100, "USD")


@pytest.mark.django_db
def test_money_left_applies_the_discount(db_client):
    metering = Metering.objects.create(client=db_client, date_time=datetime.datetime.now())
    order = _order_for(db_client, metering, price=Money(100, "USD"), lost_money=Money(0, "USD"))
    order.discount = 10
    order.save(update_fields=["discount"])

    assert order_money_left_display(order) == Money(90, "USD")


def test_money_left_without_an_order_is_a_dash():
    assert order_money_left_display(None) == "-"


@pytest.mark.django_db
def test_money_left_with_mismatched_currencies_is_a_dash(db_client):
    """price and lost_money are independent MoneyFields with their own currency
    columns. Subtracting across currencies raises, and as a list_display callable
    that would 500 the whole changelist, so the mismatch degrades to "-"."""
    metering = Metering.objects.create(client=db_client, date_time=datetime.datetime.now())
    order = _order_for(db_client, metering, price=Money(100, "USD"), lost_money=Money(30, "UZS"))

    assert order_money_left_display(order) == "-"


@pytest.mark.django_db
def test_money_left_without_a_price_is_a_dash(db_client):
    metering = Metering.objects.create(client=db_client, date_time=datetime.datetime.now())
    order = _order_for(db_client, metering, price=None)

    assert order_money_left_display(order) == "-"


@pytest.mark.django_db
def test_money_and_order_number_columns_are_always_shown(rf, django_user_model):
    """Per decision: the balance is visible to anyone who can see the metering list,
    with no view_order_price gate, and it sits alongside the order number."""
    staff = django_user_model.objects.create_user(phone="+998900000009", password="pass12345")
    staff.is_staff = True
    staff.save()

    request = rf.get("/admin/metering/metering/")
    request.user = staff

    list_display = MeteringAdmin(Metering, admin.site).get_list_display(request)

    assert "order_money_left" in list_display
    assert "order_number" in list_display


@pytest.mark.django_db
def test_order_number_column_links_to_the_order(db_client):
    metering = Metering.objects.create(client=db_client, date_time=datetime.datetime.now())
    order = _order_for(db_client, metering, price=Money(100, "USD"))

    result = str(MeteringAdmin(Metering, admin.site).order_number(metering))

    assert str(order.order_number) in result
    assert f"/order/order/{order.pk}/" in result


@pytest.mark.django_db
def test_order_number_column_without_an_order_is_a_dash(db_client):
    metering = Metering.objects.create(client=db_client, date_time=datetime.datetime.now())

    assert MeteringAdmin(Metering, admin.site).order_number(metering) == "-"
