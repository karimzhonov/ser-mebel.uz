from core.notifications import (
    SMS_ORDER_ASSEMBLY,
    SMS_ORDER_DETAILING,
    SMS_ORDER_INSTALLING,
    SMS_ORDER_WORKING,
)

from .constants import OrderStatus

_STATUS_SMS_TEMPLATES = {
    OrderStatus.DETAILING: SMS_ORDER_DETAILING,
    OrderStatus.WORKING: SMS_ORDER_WORKING,
    OrderStatus.ASSEMBLY: SMS_ORDER_ASSEMBLY,
    OrderStatus.INSTALLING: SMS_ORDER_INSTALLING,
}


def send_order_status_sms(order) -> None:
    template = _STATUS_SMS_TEMPLATES.get(order.status)
    if template is None:
        return
    from oauth.models import User

    context = {"buyurtma_raqami": order.order_number}
    if order.status == OrderStatus.INSTALLING:
        context.update(
            manzil=order.address or "",
            mijoz_tel=order.client_phone() or "",
            sana=order.end_date or "",
            vaqt="",
        )
    User.send_messages(
        OrderStatus.permission(order.status),
        "admin:order_order_change",
        {"object_id": order.pk},
        sms_template=template,
        sms_context=context,
    )


def resolve_order_status_on_save(order) -> None:
    """Derive an Order's status from whether end_date is set.

    A newly created order without an end_date starts out WAITING. It leaves
    WAITING once end_date is set (here, on save) — never via the "Изменить
    статус" button (see OrderStatus.progression_statuses(), which excludes
    WAITING).

    Only demote to WAITING on creation (order._state.adding is True). Blanking
    end_date on an order that already progressed past WAITING/CREATED must not
    silently reset its status and lose that progress — so on saves of an
    already-existing order, a missing end_date is left alone.
    """
    if order.end_date is None:
        if order._state.adding:
            order.status = OrderStatus.WAITING
    elif order.status == OrderStatus.WAITING:
        order.status = OrderStatus.CREATED
