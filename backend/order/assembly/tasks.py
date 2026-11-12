"""Celery tasks of the Assembly (Yig'ish/O'rnatish) flow."""

from celery import shared_task


@shared_task
def assembly_task_sms(assembly_id, user_id):
    """SMS about a started assembly job to an assembler without Telegram. Once per job/user."""
    from accounting.services import once
    from core.notifications import SMS_ASSEMBLY_TASK
    from core.sms import absolute_url, format_phone, send_bulk_sms

    from .models import Assembly

    a = Assembly.objects.select_related("order", "user").filter(pk=assembly_id).first()
    if a is None or a.installing_done or a.finished_at is not None or a.user is None:
        return 0
    user = a.user
    if user.pk != user_id or user.telegram_id:
        return 0
    phone = format_phone(user.phone)
    if not phone or not once(f"assembly:{assembly_id}:task_sms:{user_id}"):
        return 0
    text = SMS_ASSEMBLY_TASK.format(
        xodim_ism=user.name or "",
        buyurtma_raqami=a.order.order_number,
        maydon=a.square,
        manzil=a.order.address or "",
        url=absolute_url(f"/production/assembly?open={assembly_id}"),
    )
    send_bulk_sms([{"phone": phone, "text": text}])
    return 1


@shared_task
def assembly_reminders():
    """Every minute: auto deadlines, «1 day left» and daily overdue reminders."""
    from accounting.text import now

    from . import services

    return services.due_assembly_reminders(now())
