"""Celery tasks of the Painter (molyar) flow."""

from celery import shared_task


@shared_task
def painter_task_sms(painter_id, user_id):
    """SMS about a started painter job to a painter without Telegram. Once per painter."""
    from accounting.services import once
    from core.notifications import SMS_PAINTER_TASK
    from core.sms import absolute_url, format_phone, send_bulk_sms

    from .models import Painter

    painter = Painter.objects.select_related("order", "type__user").filter(pk=painter_id).first()
    if painter is None or painter.done or painter.type is None:
        return 0
    user = painter.type.user
    if user is None or user.pk != user_id or user.telegram_id:
        return 0
    phone = format_phone(user.phone)
    if not phone or not once(f"painter:{painter_id}:task_sms:{user_id}"):
        return 0
    text = SMS_PAINTER_TASK.format(
        xodim_ism=user.name or "",
        buyurtma_raqami=painter.order.order_number,
        maydon=painter.square,
        url=absolute_url(f"/production/painter?open={painter_id}"),
    )
    send_bulk_sms([{"phone": phone, "text": text}])
    return 1


@shared_task
def painter_part_task_sms(part_id, user_id):
    """SMS about a started painter part to a molyar without Telegram. Once per part."""
    from accounting.services import once
    from core.notifications import SMS_PAINTER_TASK
    from core.sms import absolute_url, format_phone, send_bulk_sms

    from .models import PainterPart

    part = (
        PainterPart.objects.select_related("painter__order", "type__user")
        .filter(pk=part_id)
        .first()
    )
    if part is None or part.done:
        return 0
    user = part.type.user
    if user is None or user.pk != user_id or user.telegram_id:
        return 0
    phone = format_phone(user.phone)
    if not phone or not once(f"painter_part:{part_id}:task_sms:{user_id}"):
        return 0
    text = SMS_PAINTER_TASK.format(
        xodim_ism=user.name or "",
        buyurtma_raqami=part.painter.order.order_number,
        maydon=part.square,
        url=absolute_url(f"/production/painter?open={part.painter_id}"),
    )
    send_bulk_sms([{"phone": phone, "text": text}])
    return 1


@shared_task
def painter_reminders():
    """Every minute: auto deadlines, «1 day left» and daily overdue reminders."""
    from accounting.text import now

    from . import services

    return services.due_painter_reminders(now())
