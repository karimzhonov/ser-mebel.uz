import json
import requests
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField

from core.settings import TELEGRAM_BOT_SERVER

from .constants import *


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError(_('The phone number must be set'))
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(phone, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    phone = PhoneNumberField(unique=True, region='UZ')  # Указывается регион по умолчанию (UZ = Узбекистан)
    name = models.CharField(max_length=255, blank=True, null=True)
    telegram_id = models.BigIntegerField(blank=True, null=True)
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Designates whether the user can log into this admin site."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )

    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return str(self.phone) if not self.name else f'{self.name} ({self.phone})'

    def send_message(self, url = None, text = 'Оповещение о заказе'):
        url = str(url or '')
        if not self.telegram_id: return
        # timeout: this runs synchronously inside admin requests and post_save signals.
        # Without it an unreachable bot server hangs the whole request indefinitely.
        from core.bot_signing import signed_headers

        path = f'/user/{self.telegram_id}/message'
        body = json.dumps({'text': text, 'url': url}).encode()
        requests.post(f'{TELEGRAM_BOT_SERVER}{path}', data=body, timeout=10, headers={
            'Content-Type': 'application/json',
            **signed_headers('POST', path, body=body),
        })

    @classmethod
    def send_messages(cls, permission, path_name, kwargs, text='Оповещение о заказе', sms_template=None, sms_context=None):
        from .services import notify_staff
        notify_staff(
            permission=permission,
            path_name=path_name,
            kwargs=kwargs,
            telegram_text=text,
            sms_template=sms_template,
            sms_context=sms_context,
        )

    class Meta:
        permissions = [
            (CALL_CENTER_PERMISSION, 'Call center'),
            (METERING_PERMISSION, 'Metering'),
            (DESIGN_PERMISSION, 'Design'),
            (DETAILING_PERMISSION, 'Detailing'),
            (ROVER_PERMISSION, 'Rover'),
            (PAINTER_PERMISSION, 'Painter'),
            (ASSEMBLY_PERMISSION, 'Assembly'),
        ]


class TelegramRole(models.TextChoices):
    ADMIN = "admin", "Rahbar"
    STAFF = "staff", "Xodim"
    PENDING = "pending", "Tasdiq kutmoqda"
    BLOCKED = "blocked", "Bloklangan"


class TelegramMember(models.Model):
    """Who may use the finance Telegram bot, and as what.

    Deliberately a separate table, not columns on oauth_user: the bot mirrors
    oauth_user by hand (bot/db/models/oauth.py), and most finance staff (workers,
    drivers) have no site account at all. `user` links the two when they do.
    """

    telegram_id = models.BigIntegerField(unique=True, verbose_name="Telegram ID")
    user = models.OneToOneField(
        User,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="telegram_member",
        verbose_name="Sayt foydalanuvchisi",
    )
    name = models.CharField(max_length=255, verbose_name="Ism")
    username = models.CharField(max_length=255, blank=True, default="", verbose_name="Username")
    role = models.CharField(
        max_length=16,
        choices=TelegramRole.choices,
        default=TelegramRole.PENDING,
        db_index=True,
        verbose_name="Rol",
    )
    # Duties (the Apps Script picked these people by name or by a config key).
    is_site_entry = models.BooleanField(default=False, verbose_name="Saytga kirituvchi")
    is_feedback = models.BooleanField(default=False, verbose_name="Mijoz fikri menejeri")
    is_bonus_receiver = models.BooleanField(
        default=False, verbose_name="«Готов» varaqasi va bonus oluvchi"
    )
    is_deadline_receiver = models.BooleanField(
        default=False, verbose_name="Srok eslatmalari oluvchi"
    )
    is_accountant = models.BooleanField(
        default=False, verbose_name="Bugalter (oylik eslatmalari)"
    )
    joined_at = models.DateTimeField(auto_now_add=True, verbose_name="Qo'shilgan")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram a'zo"
        verbose_name_plural = "Telegram a'zolar"
        ordering = ["name"]

    def __str__(self):
        return self.name or str(self.telegram_id)

    @property
    def is_admin(self) -> bool:
        return self.role == TelegramRole.ADMIN

    @property
    def is_active_member(self) -> bool:
        return self.role in (TelegramRole.ADMIN, TelegramRole.STAFF)

    @property
    def is_task_only(self) -> bool:
        """Site-entry / feedback managers don't book money and aren't asked for
        reports — unless they are also an admin (taskOnly_ in code.txt)."""
        return (self.is_site_entry or self.is_feedback) and self.role != TelegramRole.ADMIN

    @property
    def has_wallet(self) -> bool:
        return self.is_active_member and not self.is_task_only
