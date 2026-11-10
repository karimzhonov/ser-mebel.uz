"""Write services for Rover (used by the REST API and the bot API).

State: new (submitted_at empty) -> the worker hands the job in with the actual amount
(checking) -> a checker confirms (done=True, the painter is notified). `done` keeps its
old meaning, so the painter / assembly / dashboard rules read it as before."""

import logging

from constance import config
from django.db import transaction
from django.utils import timezone
from djmoney.money import Money

from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from oauth.constants import ROVER_CHECKER_PERMISSION

from . import events
from .models import Rover, RoverState

logger = logging.getLogger(__name__)

NO_PERM = "Bu amal uchun huquq yetarli emas."


def auto_rover_price(square) -> Money:
    per = config.ROVER_PRICE_PER_SQUARE
    return Money(amount=float(per.amount) * float(square), currency=per.currency)


def sync_rover_from_detailing(order, square) -> Rover:
    """Detailing set the rover square: create the rover with the automatic price, or
    update the square (and the price, while the job is still `new`)."""
    with transaction.atomic():
        existing = Rover.objects.select_for_update().filter(order=order).first()
        if existing is None:
            return Rover.objects.create(order=order, square=square, price=auto_rover_price(square))
        existing.square = square
        fields = ["square"]
        if existing.state == RoverState.NEW:
            existing.price = auto_rover_price(square)
            fields.append("price")
        existing.save(update_fields=fields)
        return existing


def rover_checkers():
    from oauth.services import staff_with_permission

    return staff_with_permission(ROVER_CHECKER_PERMISSION)


def submit_rover(rover, *, by, price) -> Rover:
    """The worker's «Bajarildi»: the actual amount replaces the price and the job
    waits for a checker."""
    if not by.has_perm("rover.change_rover"):
        raise ServiceForbidden(NO_PERM)
    if price is None or price.amount is None or price.amount <= 0:
        raise ServiceError("Summa 0 dan katta bo'lishi kerak", field="price")
    with transaction.atomic():
        locked = (
            Rover.objects.select_for_update(of=("self",))
            .select_related("order__client")
            .get(pk=rover.pk)
        )
        if locked.done:
            raise ServiceConflict("Rover allaqachon bajarilgan")
        if locked.submitted_at:
            raise ServiceConflict("Rover allaqachon tekshiruvga yuborilgan")
        locked.price = price
        locked.submitted_at = timezone.now()
        locked.submitted_by = by
        locked._history_user = by
        locked.save()
        events.rover_check(locked)
    return locked


def confirm_rover(rover, *, by) -> Rover:
    """The checker accepts the job: only now it is done and the painter hears of it."""
    if not by.has_perm(f"oauth.{ROVER_CHECKER_PERMISSION}"):
        raise ServiceForbidden(NO_PERM)
    with transaction.atomic():
        locked = (
            Rover.objects.select_for_update(of=("self",))
            .select_related("order__client")
            .get(pk=rover.pk)
        )
        if locked.done:
            raise ServiceConflict("Rover allaqachon tasdiqlangan")
        if locked.submitted_at is None:
            raise ServiceError("Rover hali tekshiruvga yuborilmagan")
        locked.done = True
        locked.checked_at = timezone.now()
        locked.checked_by = by
        locked._history_user = by
        locked.save()
        from .tasks import notify_painting_ready_task

        rover_id = locked.pk
        transaction.on_commit(lambda: notify_painting_ready_task.delay(rover_id))
        events.rover_checked(locked, by=by)
    return locked


def notify_painting_ready(order):
    """Milling is finished, so the order now shows up in the Моляр list: tell the
    people who assign painters (assembly managers) and the assigned painter, if any.
    A failed notification must not undo the rover being done."""
    from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION
    from order.painter.models import Painter

    painter = Painter.objects.filter(order=order, done=False).select_related("type__user").first()
    if painter is None:
        return
    text = f"Buyurtma №{order.order_number}: rover tayyor — molyar ishini boshlash mumkin"
    try:
        from oauth.models import User

        User.send_messages(
            f"assembly.{ASSEMBLY_MANAGER_PERMISSION}",
            "admin:painter_painter_change",
            {"object_id": painter.pk},
            text=text,
        )
        if painter.type and painter.type.user:
            painter.type.user.send_message(text=text)
    except Exception:
        logger.exception("Painter notification failed for order %s", order.pk)
