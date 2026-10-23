"""Write services for Painter (used by the REST API; mirror PainterAdmin)."""

from core.exceptions import ServiceError


def assign_painter_type(painter, painter_type):
    """Mirrors PainterAdmin.save_model: saving with update_fields=["type"] is what makes
    the post_save signal notify the painter and recompute the price."""
    from django.db import transaction

    if painter.type_id == getattr(painter_type, "pk", None):
        return painter
    if painter_type is not None and painter_type.user_id is None:
        # The post_save signal notifies painter_type.user and would crash without one.
        raise ServiceError("Бу турга маляр бириктирилмаган — аввал маляр танланг")
    painter.type = painter_type
    with transaction.atomic():
        painter.save(update_fields=["type"])
    painter.refresh_from_db()
    return painter


def mark_painter_done(painter):
    if painter.done:
        raise ServiceError("Моляр иши аллақачон бажарилган")
    painter.done = True
    painter.save()
    return painter
