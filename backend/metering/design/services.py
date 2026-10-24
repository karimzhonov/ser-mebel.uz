"""Write services for Design (used by the REST API; mirror DesignAdmin actions)."""

from core.exceptions import ServiceError
from core.notifications import SMS_DESIGN_ASSIGNED, SMS_DESIGN_READY
from oauth.constants import CALL_CENTER_PERMISSION, DESIGN_PERMISSION


def mark_design_done(design):
    """Mirrors DesignAdmin.done_action: mark done and tell call-centre staff."""
    from oauth.models import User

    if design.done:
        raise ServiceError("Дизайн аллақачон бажарилган")
    design.done = True
    design.save()
    User.send_messages(
        CALL_CENTER_PERMISSION,
        "admin:design_design_change",
        {"object_id": design.pk},
        text=f"{design.metering.client} dizayni tayyor",
        sms_template=SMS_DESIGN_READY,
        sms_context={"mijoz_ism": str(design.metering.client)},
    )
    return design


def add_design_type(design, name: str):
    """A new design variant; its Filer folder is created by the DesignType signal."""
    from .models import DesignType

    return DesignType.objects.create(design=design, name=name)


def can_create_order(design) -> bool:
    """DesignAdmin.has_create_order_permission minus the user permission check."""
    from order.models import Order

    return design.done and not Order.objects.filter(metering_id=design.metering_id).exists()


def notify_design_task(design) -> None:
    """Design task: only the assigned designer when there is one, otherwise (old admin
    flow) everybody with the design permission. Sent after the transaction commits, so
    a rolled-back change never notifies anyone."""
    from django.db import transaction

    # robust: a failing send is logged and never turns a saved change into a 500.
    transaction.on_commit(lambda: _send_design_task(design), robust=True)


def _send_design_task(design) -> None:
    import logging

    from oauth.models import User
    from oauth.services import notify_user

    text = f"{design.metering.client} mijozga dizayn qilish kerak"
    context = {"buyurtma_raqami": design.metering_id}
    if design.user_id:
        notify_user(
            design.user,
            url=f"/designs/{design.pk}",
            telegram_text=text,
            sms_template=SMS_DESIGN_ASSIGNED,
            sms_context=context,
        )
        return
    try:
        User.send_messages(
            DESIGN_PERMISSION,
            "admin:design_design_change",
            {"object_id": design.pk},
            text=text,
            sms_template=SMS_DESIGN_ASSIGNED,
            sms_context=context,
        )
    except Exception:
        logging.getLogger(__name__).exception("Design task broadcast failed (%s)", design.pk)
