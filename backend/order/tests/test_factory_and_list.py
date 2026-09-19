"""Items 1, 2, 4 and 6: the Описание column, today's reception_date on add,
the two-level deadline row colouring, and the Factory FK / filter.
"""

import datetime

import pytest
from django.contrib import admin
from django.urls import resolve, reverse

from order.admin import OrderAdmin
from order.constants import DEFAULT_FACTORY_NAME, OrderStatus
from order.models import Factory, Order


def _admin():
    return OrderAdmin(Order, admin.site)


# --- Item 6: Factory -------------------------------------------------------


@pytest.mark.django_db
def test_order_requires_a_factory(db_client, today):
    """factory is a required FK — creating an order without one must fail rather
    than silently writing NULL."""
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        Order.objects.create(
            client=db_client,
            reception_date=today,
            address="addr",
        )


@pytest.mark.django_db
def test_order_factory_filter_is_on_the_changelist(rf, superuser, order_factory, db_client):
    other = Factory.objects.create(name="Boshqa zavod")
    default = Factory.objects.get_or_create(name=DEFAULT_FACTORY_NAME)[0]

    order_factory()  # default factory
    Order.objects.create(
        client=db_client,
        reception_date=datetime.date.today(),
        address="addr",
        factory=other,
    )

    url = reverse("admin:order_order_changelist")
    request = rf.get(url, {"factory__id__exact": default.pk})
    request.user = superuser
    # House style (see test_admin.py): admin code paths reach for resolver_match.
    request.resolver_match = resolve(url)

    changelist = _admin().get_changelist_instance(request)
    queryset = changelist.get_queryset(request)

    assert list(queryset.values_list("factory__name", flat=True)) == [DEFAULT_FACTORY_NAME]


# --- Item 2: reception_date defaults to today ------------------------------


@pytest.mark.django_db
def test_add_form_initial_reception_date_is_today_even_with_querystring(rf, superuser):
    """The design tab used to hand the add form the *metering* date; the order is
    received today regardless of what the referring page passes."""
    url = reverse("admin:order_order_add")
    request = rf.get(url, {"reception_date": "08.07.2026"})
    request.user = superuser
    request.resolver_match = resolve(url)

    initial = _admin().get_changeform_initial_data(request)

    assert initial["reception_date"] == datetime.date.today()


@pytest.mark.django_db
def test_add_form_initial_factory_is_the_default_factory(rf, superuser, default_factory):
    url = reverse("admin:order_order_add")
    request = rf.get(url)
    request.user = superuser
    request.resolver_match = resolve(url)

    initial = _admin().get_changeform_initial_data(request)

    assert initial["factory"] == default_factory.pk


@pytest.mark.django_db
def test_design_create_order_redirect_does_not_pass_reception_date(db_client):
    """DesignAdmin.create_order builds the add-form query string; it must no
    longer pin reception_date to the metering date."""
    from djmoney.money import Money

    from metering.design.admin import DesignAdmin
    from metering.design.models import Design
    from metering.models import Metering
    from metering.price.models import Price

    metering = Metering.objects.create(client=db_client, date_time=datetime.datetime.now())
    design = Design.objects.create(metering=metering)
    # create_order dereferences metering.price unconditionally.
    Price.objects.create(metering=metering, price=Money(100, "USD"))

    response = DesignAdmin(Design, admin.site).create_order(None, design.pk)

    assert "reception_date" not in response.url


# --- Item 4: deadline row colouring ----------------------------------------


def _annotated(order):
    """Refetch through OrderManager so the `days` annotation show_days reads exists."""
    return Order.objects.get(pk=order.pk)


@pytest.mark.django_db
def test_show_days_overdue_marks_the_row_danger(order_factory, today):
    order = order_factory(end_date=today - datetime.timedelta(days=3))
    order.status = OrderStatus.CREATED
    order.save(update_fields=["status"])

    result = str(_admin().show_days(_annotated(order)))

    assert "order-row-danger" in result
    assert "order-row-warning" not in result


@pytest.mark.django_db
def test_show_days_within_warning_window_marks_the_row_warning(order_factory, today):
    from constance import config

    order = order_factory(
        end_date=today + datetime.timedelta(days=max(config.WARNING_ORDER_DAYS - 1, 0))
    )

    result = str(_admin().show_days(_annotated(order)))

    assert "order-row-warning" in result
    assert "order-row-danger" not in result


@pytest.mark.django_db
def test_show_days_far_from_deadline_marks_the_row_in_progress(order_factory, today):
    from constance import config

    order = order_factory(end_date=today + datetime.timedelta(days=config.WARNING_ORDER_DAYS + 10))

    result = str(_admin().show_days(_annotated(order)))

    assert "order-row-progress" in result
    assert "order-row-warning" not in result
    assert "order-row-danger" not in result


@pytest.mark.django_db
def test_show_days_done_marks_the_row_done(order_factory, today):
    order = order_factory(end_date=today + datetime.timedelta(days=3))
    order.status = OrderStatus.DONE
    order.save(update_fields=["status"])

    result = str(_admin().show_days(_annotated(order)))

    # Green wins over the orange deadline window: the order is finished.
    assert "order-row-done" in result
    assert "order-row-warning" not in result


@pytest.mark.django_db
def test_show_days_waiting_has_no_row_marker(order_factory):
    order = order_factory(end_date=None)

    result = str(_admin().show_days(_annotated(order)))

    assert "order-row" not in result


# --- Item 1: Описание column -----------------------------------------------


@pytest.mark.django_db
def test_show_desc_renders_short_text_as_is(order_factory):
    order = order_factory()
    order.desc = "Kichik izoh"
    order.save(update_fields=["desc"])

    assert _admin().show_desc(order) == "Kichik izoh"


@pytest.mark.django_db
def test_show_desc_truncates_long_text_and_keeps_the_full_text_in_a_tooltip(order_factory):
    order = order_factory()
    order.desc = "x" * 200
    order.save(update_fields=["desc"])

    result = str(_admin().show_desc(order))

    # Full text preserved in the tooltip, shortened in the cell body.
    assert 'title="' + "x" * 200 + '"' in result
    assert ">" + "x" * 200 + "<" not in result


@pytest.mark.django_db
def test_show_desc_handles_empty_desc(order_factory):
    order = order_factory()

    assert _admin().show_desc(order) == "-"
