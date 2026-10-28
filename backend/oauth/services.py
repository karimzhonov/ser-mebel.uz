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


def verify_telegram_init_data(init_data: str, bot_token: str, max_age: int | None = None):
    """Validate Telegram WebApp `initData` and return its `user` dict, or None.

    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    secret = HMAC_SHA256(key="WebAppData", msg=bot_token); the payload's `hash` must
    equal HMAC_SHA256(key=secret, msg=data_check_string), where data_check_string is
    every other field as "key=value", sorted by key, joined by "\\n".

    This proves who the Telegram user is (unlike oauth.views.telegram_admin_login's bare
    ?telegram_id=). It does NOT prove that this Telegram account belongs to the staff
    user it is linked to — that depends on the bot's /start linking.
    """
    import hashlib
    import hmac
    import json
    import time
    from urllib.parse import parse_qsl

    if not init_data or not bot_token:
        return None
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received_hash = fields.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None

    if max_age:
        try:
            auth_date = int(fields.get("auth_date", "0"))
        except ValueError:
            return None
        if time.time() - auth_date > max_age:
            return None

    try:
        user = json.loads(fields.get("user", ""))
    except ValueError:
        return None
    if not isinstance(user, dict) or "id" not in user:
        return None
    return user


def users_with_perm(app_label: str, codename: str):
    """Active users holding app_label.codename directly or through a group, plus
    superusers (they hold every permission)."""
    from .models import User

    perm = models.Q(
        user_permissions__codename=codename,
        user_permissions__content_type__app_label=app_label,
    ) | models.Q(
        groups__permissions__codename=codename,
        groups__permissions__content_type__app_label=app_label,
    )
    return User.objects.filter(is_active=True).filter(perm | models.Q(is_superuser=True)).distinct()


def notify_user(user, *, url, telegram_text, sms_template=None, sms_context=None) -> None:
    """Telegram + SMS to ONE person (the assigned executor), not to a whole role.
    A failed send is logged, never raised: the task itself is already saved."""
    try:
        user.send_message(url, text=telegram_text)
    except Exception:
        logger.exception("Telegram notification failed for user %s", user.pk)
    if sms_template:
        phone = format_phone(user.phone)
        if phone:
            text = sms_template.format(
                xodim_ism=user.name or "", url=absolute_url(url), **(sms_context or {})
            )
            send_bulk_sms([{"phone": phone, "text": text}])


def link_telegram(token, telegram_id: int):
    """Link a Telegram account to the site user named by a `/start` link payload.

    `token` is the signed payload built by core.telegram.link_token (`u{pk}_{hmac10}`);
    plain digits (the old unsigned format) are still accepted for one release and
    logged as deprecated. Returns the User, or None for a bad signature, an unknown or
    inactive user. The Telegram id is moved here if another user still had it (login by
    telegram_id must stay unambiguous). Called by POST /api/v1/bot/link/ - the bot no
    longer writes oauth_user itself.
    """
    from django.db import transaction

    from core.telegram import parse_link_token

    from .models import User

    pk = parse_link_token(token)
    if pk is None:
        return None
    signed = not str(token or "").strip().isdigit()
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=pk, is_active=True).first()
        if user is None:
            return None
        if not signed and (
            user.is_staff or user.is_superuser or user.telegram_id not in (None, int(telegram_id))
        ):
            return None  # the unsigned format may only fill an empty slot, never take over
        User.objects.filter(telegram_id=int(telegram_id)).exclude(pk=pk).update(telegram_id=None)
        if user.telegram_id != int(telegram_id):
            user.telegram_id = int(telegram_id)
            user.save(update_fields=["telegram_id"])
    return user


# Deleting a staff account must not silently take work history with it. These are
# the only rows that may disappear (or be unlinked) together with the user.
_USER_DELETE_OK = {
    "oauth.user",
    "admin.logentry",
    "token_blacklist.outstandingtoken",
    "token_blacklist.blacklistedtoken",
}
_USER_HAS_HISTORY = (
    "Bu xodimning ish tarixi bor (yig'ish, izohlar …) — "
    "o'chirish o'rniga «Faol» belgisini olib qo'ying."
)


def delete_user(actor, user) -> None:
    """Admin removes a staff account (e.g. added by mistake).

    Refused for yourself, for the last active superuser, and when the user owns work
    records that would be deleted with them (assembly jobs, discussion messages …) —
    then the account should be switched off («Faol» unticked) instead.
    """
    from django.db import transaction
    from django.db.models.deletion import Collector, ProtectedError, RestrictedError

    from core.exceptions import ServiceError

    from .models import User

    if actor.pk == user.pk:
        raise ServiceError("O'zingizni o'chira olmaysiz.")
    if (
        user.is_superuser
        and not User.objects.filter(is_superuser=True, is_active=True).exclude(pk=user.pk).exists()
    ):
        raise ServiceError("Oxirgi administratorni o'chirib bo'lmaydi.")

    collector = Collector(using="default")
    try:
        collector.collect([user])
    except (ProtectedError, RestrictedError):
        raise ServiceError(_USER_HAS_HISTORY)
    # Rows deleted with the user: `data` (loaded objects) + `fast_deletes` (querysets).
    doomed = [(m, bool(objs)) for m, objs in collector.data.items()]
    doomed += [(qs.model, qs.exists()) for qs in collector.fast_deletes]
    for model, has_rows in doomed:
        if not has_rows or model._meta.auto_created:  # groups / permissions link rows
            continue
        if model._meta.label_lower not in _USER_DELETE_OK:
            raise ServiceError(_USER_HAS_HISTORY)

    with transaction.atomic():
        user.delete()
