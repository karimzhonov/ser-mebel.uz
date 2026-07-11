import datetime

import pytest
from django.contrib import admin
from django.urls import resolve, reverse

from order.admin import OrderAdmin
from order.constants import OrderStatus
from order.models import Order


@pytest.mark.django_db
def test_order_has_add_permission_denied_on_changelist(rf, superuser):
    """has_add_permission must actually *call* not_add_permission_in_admin(request)
    (regression: it used to return the bare function object, which is always
    truthy regardless of what the request/view actually is).
    """
    url = reverse("admin:order_order_changelist")
    request = rf.get(url)
    request.user = superuser
    request.resolver_match = resolve(url)

    order_admin = OrderAdmin(Order, admin.site)

    result = order_admin.has_add_permission(request)

    assert result is False, (
        "has_add_permission() must be False on the changelist view — if this is "
        "True, has_add_permission is returning the not_add_permission_in_admin "
        "function object itself (always truthy) instead of calling it."
    )


@pytest.mark.django_db
def test_order_has_add_permission_true_off_changelist(rf, superuser):
    """Sanity check the other branch of the same function: on a view whose name
    doesn't end with changelist/change (e.g. the add view itself), permission
    should be granted. This proves the function's return value actually varies
    with the request, i.e. it is really being invoked.
    """
    add_url = reverse("admin:order_order_add")
    request = rf.get(add_url)
    request.user = superuser
    request.resolver_match = resolve(add_url)

    order_admin = OrderAdmin(Order, admin.site)

    assert order_admin.has_add_permission(request) is True


@pytest.mark.django_db
def test_show_days_handles_null_end_date(order_factory):
    order = order_factory(end_date=None)
    order.refresh_from_db()
    # save() forces status to WAITING whenever end_date is None.
    assert order.status == OrderStatus.WAITING

    order_admin = OrderAdmin(Order, admin.site)
    # Refetch through the manager so the `days` annotation (used by show_days)
    # is present, exactly like the changelist/changeform would see it.
    annotated_order = Order.objects.get(pk=order.pk)

    result = order_admin.show_days(annotated_order)  # must not raise

    assert "Ожидание даты сдачи" in str(result)


@pytest.mark.django_db
def test_show_days_with_end_date_set_does_not_crash(order_factory, today):
    order = order_factory(end_date=today + datetime.timedelta(days=5))
    annotated_order = Order.objects.get(pk=order.pk)

    order_admin = OrderAdmin(Order, admin.site)
    result = order_admin.show_days(annotated_order)

    assert result is not None
