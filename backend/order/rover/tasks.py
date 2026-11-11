"""Celery tasks of the Rover flow."""

from celery import shared_task


@shared_task
def notify_painting_ready_task(rover_id):
    """Tell the painter side that milling is done. Once per rover (redelivery-safe)."""
    from accounting.services import once

    from .models import Rover
    from .services import notify_painting_ready

    rover = Rover.objects.select_related("order").filter(pk=rover_id, done=True).first()
    if rover is None or not once(f"rover:{rover_id}:painting_ready"):
        return False
    notify_painting_ready(rover.order)
    return True


@shared_task
def rover_reminders():
    """Every minute: auto deadlines, «1 day left» and daily overdue reminders."""
    from accounting.text import now

    from . import services

    return services.due_rover_reminders(now())


@shared_task
def rover_task_sms(rover_id):
    """SMS about a new rover job to the workers who have no Telegram. Once per worker."""
    from accounting.services import once
    from core.notifications import SMS_ROVER_TASK
    from core.sms import absolute_url, format_phone, send_bulk_sms

    from .models import Rover
    from .services import rover_workers

    rover = Rover.objects.select_related("order").filter(pk=rover_id).first()
    if rover is None or rover.done:
        return 0
    batch = []
    for user in rover_workers():
        if user.telegram_id:
            continue
        phone = format_phone(user.phone)
        if not phone or not once(f"rover:{rover_id}:task_sms:{user.pk}"):
            continue
        text = SMS_ROVER_TASK.format(
            xodim_ism=user.name or "",
            buyurtma_raqami=rover.order.order_number,
            maydon=rover.square,
            url=absolute_url(f"/production/rover?open={rover_id}"),
        )
        batch.append({"phone": phone, "text": text})
    if batch:
        send_bulk_sms(batch)
    return len(batch)
