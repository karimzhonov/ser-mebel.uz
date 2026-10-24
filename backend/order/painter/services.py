"""Write services for Painter (used by the REST API)."""

from django.db.models import Q

from core.exceptions import ServiceError

# Painting starts only after milling: an order whose rover (if it has one) is not done
# yet is not the painter's work. Orders without a rover go to the painter directly.
ROVER_FINISHED = Q(order__rover__isnull=True) | Q(order__rover__done=True)


def ready_for_painter(queryset):
    """Painter rows the painter may work on now (rover finished or not needed)."""
    return queryset.filter(ROVER_FINISHED)


def waiting_for_rover(painter) -> bool:
    rover = getattr(painter.order, "rover", None)
    return rover is not None and not rover.done


def _ensure_rover_finished(painter):
    if waiting_for_rover(painter):
        raise ServiceError("Rover hali tugamagan — molyar ishi roverdan keyin boshlanadi")


def assign_painter_type(painter, painter_type):
    """Saving with update_fields=["type"] is what makes the post_save signal notify the
    painter and recompute the price."""
    from django.db import transaction

    if painter.type_id == getattr(painter_type, "pk", None):
        return painter
    _ensure_rover_finished(painter)
    if painter_type is not None and painter_type.user_id is None:
        # The post_save signal notifies painter_type.user and would crash without one.
        raise ServiceError("Bu turga molyar biriktirilmagan — avval molyarni tanlang")
    painter.type = painter_type
    with transaction.atomic():
        painter.save(update_fields=["type"])
    painter.refresh_from_db()
    return painter


def mark_painter_done(painter):
    if painter.done:
        raise ServiceError("Molyar ishi allaqachon bajarilgan")
    _ensure_rover_finished(painter)
    painter.done = True
    painter.save()
    return painter
