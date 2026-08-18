from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission

from core.notifications import (
    SMS_ORDER_ASSEMBLY,
    SMS_ORDER_DETAILING,
    SMS_ORDER_INSTALLING,
    SMS_ORDER_WORKING,
)
from order.constants import OrderStatus
from order.services import send_order_status_sms


# ---------------------------------------------------------------------------
# send_order_status_sms — no-op statuses
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("status", [OrderStatus.WAITING, OrderStatus.CREATED, OrderStatus.DONE])
def test_send_order_status_sms_noop_for_non_triggering_statuses(order_factory, status):
    order = order_factory()
    order.status = status

    with patch("oauth.models.User.send_messages") as mock_send_messages:
        send_order_status_sms(order)

    mock_send_messages.assert_not_called()


# ---------------------------------------------------------------------------
# send_order_status_sms — triggering statuses select the right template
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status,expected_template",
    [
        (OrderStatus.DETAILING, SMS_ORDER_DETAILING),
        (OrderStatus.WORKING, SMS_ORDER_WORKING),
        (OrderStatus.ASSEMBLY, SMS_ORDER_ASSEMBLY),
        (OrderStatus.INSTALLING, SMS_ORDER_INSTALLING),
    ],
)
def test_send_order_status_sms_selects_correct_template(order_factory, status, expected_template):
    order = order_factory()
    order.status = status

    with patch("oauth.models.User.send_messages") as mock_send_messages:
        send_order_status_sms(order)

    mock_send_messages.assert_called_once()
    call_kwargs = mock_send_messages.call_args.kwargs
    assert call_kwargs["sms_template"] == expected_template
    assert call_kwargs["sms_context"]["buyurtma_raqami"] == order.order_number

    # The rendered text must actually contain the order number, proving the
    # context is wired correctly through to the template.
    rendered = expected_template.format(
        xodim_ism="Test",
        url="/x/",
        **call_kwargs["sms_context"],
    )
    assert str(order.order_number) in rendered


@pytest.mark.django_db
def test_send_order_status_sms_passes_correct_permission_per_status(order_factory):
    order = order_factory()
    order.status = OrderStatus.DETAILING

    with patch("oauth.models.User.send_messages") as mock_send_messages:
        send_order_status_sms(order)

    call_args = mock_send_messages.call_args.args
    assert call_args[0] == OrderStatus.permission(OrderStatus.DETAILING)
    assert call_args[1] == "admin:order_order_change"
    assert call_args[2] == {"object_id": order.pk}


# ---------------------------------------------------------------------------
# INSTALLING — extra context
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_send_order_status_sms_installing_includes_address_phone_and_date(
    order_factory, db_client, today
):
    order = order_factory(address="Tashkent, 1-uy", end_date=today)
    order.status = OrderStatus.INSTALLING

    with patch("oauth.models.User.send_messages") as mock_send_messages:
        send_order_status_sms(order)

    context = mock_send_messages.call_args.kwargs["sms_context"]
    assert context["manzil"] == "Tashkent, 1-uy"
    assert context["mijoz_tel"] == db_client.phone
    assert context["sana"] == today
    assert order.end_date == today


@pytest.mark.django_db
def test_send_order_status_sms_non_installing_statuses_omit_installing_context(order_factory):
    order = order_factory()
    order.status = OrderStatus.DETAILING

    with patch("oauth.models.User.send_messages") as mock_send_messages:
        send_order_status_sms(order)

    context = mock_send_messages.call_args.kwargs["sms_context"]
    assert "manzil" not in context
    assert "mijoz_tel" not in context
    assert "sana" not in context


# ---------------------------------------------------------------------------
# Integration: Order.change_status end-to-end (mocking only the network edges)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_change_status_to_detailing_notifies_matching_staff_end_to_end(order_factory):
    """Order.change_status(DETAILING) must actually reach notify_staff for the
    detailing.view_detailing permission group and fire both a Telegram and an
    SMS notification, without hitting real network — only
    core.sms.send_bulk_sms (HTTP) and User.send_message (HTTP) are mocked.
    """
    from oauth.models import User

    perm = Permission.objects.get(codename="view_detailing", content_type__app_label="detailing")
    staffer = User(phone="+998907776655", name="Detailer", is_staff=True)
    staffer.set_password("pass12345")
    staffer.save()
    staffer.user_permissions.add(perm)

    order = order_factory()

    with (
        patch("oauth.models.User.send_message") as mock_send_message,
        patch("oauth.services.send_bulk_sms") as mock_bulk,
    ):
        order.change_status(OrderStatus.DETAILING)

    order.refresh_from_db()
    assert order.status == OrderStatus.DETAILING

    mock_send_message.assert_called_once()
    mock_bulk.assert_called_once()
    batch = mock_bulk.call_args.args[0]
    assert len(batch) == 1
    assert batch[0]["phone"] == "998907776655"
    assert str(order.order_number) in batch[0]["text"]


@pytest.mark.django_db
def test_change_status_to_assembly_targets_assembly_permission_group_not_detailing(order_factory):
    """Contrast with test_change_status_to_detailing_notifies_matching_staff_end_to_end:
    ASSEMBLY uses a different permission group (assembly.view_assembly) than
    DETAILING/WORKING (detailing.view_detailing) — a detailing-only staffer
    must not be notified for an ASSEMBLY status change.
    """
    from oauth.models import User

    detailing_perm = Permission.objects.get(
        codename="view_detailing", content_type__app_label="detailing"
    )
    detailing_only_staffer = User(phone="+998907776657", name="DetailingOnly", is_staff=True)
    detailing_only_staffer.set_password("pass12345")
    detailing_only_staffer.save()
    detailing_only_staffer.user_permissions.add(detailing_perm)

    order = order_factory()

    with (
        patch("oauth.models.User.send_message"),
        patch("oauth.services.send_bulk_sms") as mock_bulk,
    ):
        order.change_status(OrderStatus.ASSEMBLY)

    order.refresh_from_db()
    assert order.status == OrderStatus.ASSEMBLY
    # No assembly.view_assembly holder exists in this test, so the batch is empty
    # (send_bulk_sms is still called once with an empty list — see notify_staff).
    mock_bulk.assert_called_once_with([])
