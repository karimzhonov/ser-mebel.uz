from unittest.mock import patch

import pytest
from django.contrib import admin, messages
from django.contrib.messages.storage.fallback import FallbackStorage

from order.admin import OrderAdmin
from order.assembly.models import Assembly
from order.constants import OrderStatus
from order.models import Order


def _admin_request(rf, superuser, order_pk):
    """The unfold @action decorator's permission check needs request.user
    (has_go_to_assembly_action_permission calls request.user.has_perm) and
    reads object_id from kwargs, so object_id must be passed as a keyword
    when calling the decorated method too."""
    request = rf.post(f"/admin/order/order/{order_pk}/go-to-assembly/")
    request.user = superuser
    return request


@pytest.mark.django_db
def test_go_to_assembly_action_goes_through_change_status(order_factory, today, rf, superuser):
    """Regression test: go_to_assembly_action used to set obj.status + obj.save()
    directly, bypassing the SMS/Telegram notification entirely. It must now go
    through Order.change_status (which also calls send_sms())."""
    order = order_factory(end_date=today)
    order.status = OrderStatus.WORKING
    order.save(update_fields=["status"])
    Assembly.objects.create(order=order, square=5)

    order_admin = OrderAdmin(Order, admin.site)
    request = _admin_request(rf, superuser, order.pk)

    with patch("order.models.Order.send_sms") as mock_send_sms:
        order_admin.go_to_assembly_action(request, object_id=order.pk)

    order.refresh_from_db()
    assert order.status == OrderStatus.ASSEMBLY
    mock_send_sms.assert_called_once()


@pytest.mark.django_db
def test_go_to_assembly_action_notifies_assembly_permission_holders(
    order_factory, today, rf, superuser
):
    from django.contrib.auth.models import Permission

    from oauth.models import User

    perm = Permission.objects.get(codename="view_assembly", content_type__app_label="assembly")
    staffer = User(phone="+998907776658", name="Assembler", is_staff=True)
    staffer.set_password("pass12345")
    staffer.save()
    staffer.user_permissions.add(perm)

    order = order_factory(end_date=today)
    order.status = OrderStatus.WORKING
    order.save(update_fields=["status"])
    Assembly.objects.create(order=order, square=5)

    order_admin = OrderAdmin(Order, admin.site)
    request = _admin_request(rf, superuser, order.pk)

    with (
        patch("oauth.models.User.send_message") as mock_send_message,
        patch("oauth.services.send_bulk_sms") as mock_bulk,
    ):
        order_admin.go_to_assembly_action(request, object_id=order.pk)

    order.refresh_from_db()
    assert order.status == OrderStatus.ASSEMBLY
    mock_send_message.assert_called_once()
    batch = mock_bulk.call_args.args[0]
    assert len(batch) == 1
    assert batch[0]["phone"] == "998907776658"


@pytest.mark.django_db
def test_go_to_assembly_action_without_an_assembly_does_not_500(
    order_factory, today, rf, superuser
):
    """Repro for the production crash:

        RelatedObjectDoesNotExist at /admin/order/order/40/go-to-assembly/
        Order has no assembly.

    Detailing only creates the Assembly row when its `square` is non-zero
    (order/detailing/models.py), so an order detailed with square=0 reaches the
    "Отправить в сборку" button with no Assembly at all. `obj.assembly` on a
    reverse OneToOne raises instead of returning None, so the `if obj.assembly`
    guard in go_to_assembly_action never ran.

    The action must refuse cleanly — and, crucially, must NOT have moved the
    order into ASSEMBLY on the way, which is what left order 40 stranded in a
    status whose button is no longer offered.
    """
    order = order_factory(end_date=today)
    order.status = OrderStatus.WORKING
    order.save(update_fields=["status"])
    assert not hasattr(order, "assembly")

    order_admin = OrderAdmin(Order, admin.site)
    request = _admin_request(rf, superuser, order.pk)
    # message_user() needs a message store; RequestFactory doesn't run middleware.
    request.session = {}
    request._messages = FallbackStorage(request)

    with patch("order.models.Order.send_sms"):
        response = order_admin.go_to_assembly_action(request, object_id=order.pk)

    warnings = [m for m in request._messages if m.level == messages.WARNING]
    assert len(warnings) == 1
    assert "деталировке" in str(warnings[0])

    order.refresh_from_db()
    assert order.status == OrderStatus.WORKING
    assert response.status_code == 302
    assert f"/order/order/{order.pk}/" in response.url
