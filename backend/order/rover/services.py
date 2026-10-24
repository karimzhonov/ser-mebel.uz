"""Write services for Rover (used by the REST API)."""

import logging

from core.exceptions import ServiceError

logger = logging.getLogger(__name__)


def mark_rover_done(rover):
    if rover.done:
        raise ServiceError("Ровер аллақачон бажарилган")
    rover.done = True
    rover.save()
    notify_painting_ready(rover.order)
    return rover


def notify_painting_ready(order):
    """Milling is finished, so the order now shows up in the Моляр list: tell the
    people who assign painters (assembly managers) and the assigned painter, if any.
    A failed notification must not undo the rover being done."""
    from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION
    from order.painter.models import Painter

    painter = Painter.objects.filter(order=order, done=False).select_related("type__user").first()
    if painter is None:
        return
    text = f"Заказ №{order.order_number}: ровер тайёр — моляр ишини бошлаш мумкин"
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
