"""Write services for Detailing (used by the REST API; mirror DetailingAdmin)."""

from django.db import transaction

from core.exceptions import ServiceError

from ..constants import OrderStatus


def mark_detailing_done(detailing):
    """Mirrors DetailingAdmin.done_action: the order moves to "Заказ на сырье"."""
    if detailing.done:
        raise ServiceError("Деталировка аллақачон бажарилган")
    with transaction.atomic():
        detailing.done = True
        detailing.save(update_fields=["done"])
        detailing.order.status = OrderStatus.WORKING
        detailing.order.save(update_fields=["status"])
    return detailing
