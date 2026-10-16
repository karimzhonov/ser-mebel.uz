import logging

from django.db import models
from django.urls import reverse_lazy

from core.sms import absolute_url, format_phone, send_bulk_sms

logger = logging.getLogger(__name__)

TEST_MESSAGE_TEXT = "Тестовое сообщение — Telegram уведомления работают."


def send_test_telegram_messages(users) -> tuple[int, int, int]:
    """Send a test Telegram message to each of `users`.

    Returns (sent, without_telegram, failed). One user's bot-server failure must not
    abort the rest of the batch, so every send is guarded — User.send_message() posts
    to the bot synchronously, and the admin request is blocked for the whole loop.
    """
    sent = without_telegram = failed = 0
    for user in users:
        if not user.telegram_id:
            without_telegram += 1
            continue
        try:
            user.send_message(text=TEST_MESSAGE_TEXT)
        except Exception:
            logger.exception("Test Telegram message failed for user %s", user.pk)
            failed += 1
        else:
            sent += 1
    return sent, without_telegram, failed


def staff_with_permission(codename: str):
    from .models import User

    return User.objects.filter(
        models.Q(user_permissions__codename=codename)
        | models.Q(groups__permissions__codename=codename)
    ).distinct()


def notify_staff(
    *,
    permission,
    path_name,
    kwargs,
    telegram_text="Оповещение о заказе",
    sms_template=None,
    sms_context=None,
    telegram=True,
) -> None:
    codename = permission.split(".")[-1]
    url = reverse_lazy(path_name, kwargs=kwargs)
    sms_batch = []
    for user in staff_with_permission(codename):
        if telegram:
            user.send_message(url, text=telegram_text)
        if sms_template:
            phone = format_phone(user.phone)
            if phone:
                text = sms_template.format(
                    xodim_ism=user.name or "", url=absolute_url(url), **(sms_context or {})
                )
                sms_batch.append({"phone": phone, "text": text})
    send_bulk_sms(sms_batch)
