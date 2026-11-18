"""Write services for Detailing (used by the REST API; mirror DetailingAdmin)."""

from datetime import datetime

from django.db import transaction
from django.utils import timezone

from core.exceptions import ServiceError

from ..constants import OrderStatus


def clean_service_out(service_out_at):
    """When the parts come out of the service: required, in the future (naive local)."""
    if not isinstance(service_out_at, datetime):
        raise ServiceError("Usluga'dan chiqish vaqtini kiriting", "service_out_at")
    if service_out_at.tzinfo is not None:
        service_out_at = timezone.make_naive(service_out_at)
    if service_out_at <= timezone.now():
        raise ServiceError(
            "O'tgan vaqt — kelajakdagi vaqtni kiriting", "service_out_at"
        )
    return service_out_at


def clean_service_place(service_place):
    from .models import ServicePlace

    if service_place not in ServicePlace.values:
        raise ServiceError("Usluga joyini tanlang (Timber / Eman)", "service_place")
    return service_place


def mark_detailing_done(detailing, *, service_out_at, service_place, service_note=""):
    """The order moves to "Заказ на сырье"; the detailer says when the parts come
    out of the service (`service_out_at`)."""
    if detailing.done:
        raise ServiceError("Detalirovka allaqachon bajarilgan")
    service_out_at = clean_service_out(service_out_at)
    service_place = clean_service_place(service_place)
    with transaction.atomic():
        detailing.done = True
        detailing.service_out_at = service_out_at
        detailing.service_place = service_place
        detailing.service_note = (service_note or "").strip()
        detailing.save(
            update_fields=["done", "service_out_at", "service_place", "service_note"]
        )
        detailing.order.status = OrderStatus.WORKING
        detailing.order.save(update_fields=["status"])
    return detailing


def clean_detailing_due(due_at):
    """The detailing deadline: required, in the future. USE_TZ is off -> naive local."""
    if not isinstance(due_at, datetime):
        raise ServiceError("Detalirovka muddatini kiriting", "due_at")
    if due_at.tzinfo is not None:
        due_at = timezone.make_naive(due_at)
    if due_at <= timezone.now():
        raise ServiceError("O'tgan vaqt — kelajakdagi muddatni kiriting", "due_at")
    return due_at


def set_detailing_due(detailing, *, due_at):
    """Move the deadline of a detailing that is not done yet."""
    if detailing.done:
        raise ServiceError("Detalirovka bajarilgan — muddatni o'zgartirib bo'lmaydi")
    detailing.due_at = clean_detailing_due(due_at)
    detailing.save(update_fields=["due_at"])
    return detailing


def set_service_out(detailing, *, service_out_at, service_place, service_note=""):
    """Move the service-out time of a done detailing while the order still waits
    for raw materials («Заказ на сырье»)."""
    if not detailing.done:
        raise ServiceError("Avval detalirovkani bajaring")
    if detailing.order.status != OrderStatus.WORKING:
        raise ServiceError("Buyurtma «Заказ на сырье» bosqichida emas")
    detailing.service_out_at = clean_service_out(service_out_at)
    detailing.service_place = clean_service_place(service_place)
    detailing.service_note = (service_note or "").strip()
    detailing.save(update_fields=["service_out_at", "service_place", "service_note"])
    return detailing


def service_out_queue():
    """Orders waiting for their parts from the service («Заказ на сырье», detailing
    done), soonest first — the production head's home widget."""
    from .models import Detailing

    return (
        Detailing.objects.filter(done=True, order__status=OrderStatus.WORKING)
        .select_related("order", "order__client", "order__factory")
        .order_by("service_out_at", "pk")
    )
