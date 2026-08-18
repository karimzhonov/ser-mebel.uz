from django.db import models
from django.urls import reverse_lazy

from core.sms import absolute_url, format_phone, send_bulk_sms


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
