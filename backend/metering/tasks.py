"""Celery tasks of the zamer flow. Schedule: accounting/schedule.py."""

import logging

from celery import shared_task

from accounting.text import now

from . import services

log = logging.getLogger("metering")


@shared_task
def metering_reminders():
    """Every minute: remind measurers (soon / late / evening digest), once per revision."""
    return services.due_metering_reminders(now())


@shared_task
def assignment_sms(metering_id, rev):
    """SMS to a measurer who has no Telegram linked. Once per metering revision; skipped
    when the zamer has changed since (a newer revision sends its own)."""
    from accounting.services import once
    from core.notifications import SMS_METERING_ASSIGNED
    from core.sms import absolute_url, format_phone, send_bulk_sms

    from .models import Metering

    m = (
        Metering.objects.select_related("client", "measurer")
        .filter(pk=metering_id, rev=rev)
        .first()
    )
    if m is None or m.measurer is None or m.measurer.telegram_id or not m.measurer.is_active:
        return False
    phone = format_phone(m.measurer.phone)
    if not phone or not once(f"met:{metering_id}:r{rev}:sms"):
        return False
    text = SMS_METERING_ASSIGNED.format(
        xodim_ism=m.measurer.name or "",
        mijoz_ism=str(m.client),
        mijoz_tel=format_phone(m.client.phone) or "",
        manzil=m.address or "",
        sana=m.date_time.date() if m.date_time else "",
        vaqt=m.date_time.time() if m.date_time else "",
        url=absolute_url(f"/meterings/{m.pk}"),
    )
    send_bulk_sms([{"phone": phone, "text": text}])
    return True
