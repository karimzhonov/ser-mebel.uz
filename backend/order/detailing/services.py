"""Write services for Detailing (used by the REST API; mirror DetailingAdmin)."""

from datetime import datetime

from django.db import transaction
from django.utils import timezone

from core.exceptions import ServiceError

from ..constants import OrderStatus


def mark_detailing_done(detailing):
    """Mirrors DetailingAdmin.done_action: the order moves to "Заказ на сырье"."""
    if detailing.done:
        raise ServiceError("Detalirovka allaqachon bajarilgan")
    with transaction.atomic():
        detailing.done = True
        detailing.save(update_fields=["done"])
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
