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


def clean_services(services, *, keep=None):
    """The services the parts were given to: 1-3 rows {place, out_at, note}, each place
    once, each time in the future. `keep` = {place: out_at} already stored — an unchanged
    time may stay even if it has passed (those parts are already out)."""
    from .models import ServicePlace

    keep = keep or {}
    if not isinstance(services, (list, tuple)) or not services:
        raise ServiceError("Kamida bitta usluga kiriting (Timber / Eman)", "services")
    if len(services) > len(ServicePlace.values):
        raise ServiceError("Usluga'lar soni juda ko'p", "services")
    out, seen = [], set()
    for row in services:
        place = (row or {}).get("place")
        if place not in ServicePlace.values:
            raise ServiceError("Usluga joyini tanlang (Timber / Eman)", "services")
        if place in seen:
            raise ServiceError(f"{ServicePlace(place).label} ikki marta tanlangan", "services")
        seen.add(place)
        out_at = row.get("out_at")
        if not isinstance(out_at, datetime):
            raise ServiceError(
                f"{ServicePlace(place).label}: chiqish vaqtini kiriting", "services"
            )
        if out_at.tzinfo is not None:
            out_at = timezone.make_naive(out_at)
        if out_at <= timezone.now() and keep.get(place) != out_at:
            raise ServiceError(
                f"{ServicePlace(place).label}: o'tgan vaqt — kelajakdagi vaqtni kiriting",
                "services",
            )
        out.append({"place": place, "out_at": out_at, "note": (row.get("note") or "").strip()})
    return out


def _save_services(detailing, rows):
    """Replace the detailing's services and keep `service_out_at` = the last one."""
    from .models import DetailingService

    detailing.services.all().delete()
    DetailingService.objects.bulk_create(
        [DetailingService(detailing=detailing, **row) for row in rows]
    )
    detailing.service_out_at = max(row["out_at"] for row in rows)


def mark_detailing_done(detailing, *, services):
    """The order moves to "Заказ на сырье"; the detailer says which service(s) got the
    parts and when each one gives them back (half Timber, half Eman is fine)."""
    if detailing.done:
        raise ServiceError("Detalirovka allaqachon bajarilgan")
    rows = clean_services(services)
    with transaction.atomic():
        detailing.done = True
        _save_services(detailing, rows)
        detailing.save(update_fields=["done", "service_out_at"])
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
    from .events import detailing_task

    detailing_task(detailing, how="moved")
    return detailing


def on_order_detailing(order):
    """The order moved to «Деталировка»: the detailers get the task card in Telegram
    (deadline, client, «Bajardim» link to the site) instead of the bare message."""
    from .events import detailing_task
    from .models import Detailing

    detailing = Detailing.objects.select_related("order__client").filter(order=order).first()
    if detailing is None:
        return
    detailing_task(detailing, how="new")


def set_service_out(detailing, *, services):
    """Change the services / their times while the order still waits for raw materials
    («Заказ на сырье»)."""
    if not detailing.done:
        raise ServiceError("Avval detalirovkani bajaring")
    if detailing.order.status != OrderStatus.WORKING:
        raise ServiceError("Buyurtma «Заказ на сырье» bosqichida emas")
    keep = dict(detailing.services.values_list("place", "out_at"))
    rows = clean_services(services, keep=keep)
    with transaction.atomic():
        _save_services(detailing, rows)
        detailing.save(update_fields=["service_out_at"])
    return detailing


def service_out_queue():
    """The production head's home widget: every service row of the orders waiting for
    raw materials («Заказ на сырье»), soonest first, plus the done detailings that have
    no service row (done before services existed)."""
    from .models import Detailing, DetailingService

    waiting = dict(done=True, order__status=OrderStatus.WORKING)
    rows = (
        DetailingService.objects.filter(**{f"detailing__{k}": v for k, v in waiting.items()})
        .select_related(
            "detailing__order", "detailing__order__client", "detailing__order__factory"
        )
        .order_by("out_at", "pk")
    )
    bare = (
        Detailing.objects.filter(**waiting, services__isnull=True)
        .select_related("order", "order__client", "order__factory")
        .order_by("service_out_at", "pk")
    )
    return rows, bare
