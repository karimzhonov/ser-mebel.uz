from typing import Type

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField
from filer.fields.folder import FilerFolderField
from filer.models.foldermodels import Folder
from phonenumber_field.modelfields import PhoneNumberField
from simple_history.models import HistoricalRecords

from core.utils import create_folder

from .constants import (
    ORDER_CHANGE_STATUS_PERMISSION,
    ORDER_REVERSE_STATUS_PERMISSION,
    ORDER_VIEW_PRICE_PERMISSION,
    OrderStatus,
)
from .managers import OrderManager
from .services import resolve_order_status_on_save


class Factory(models.Model):
    """Производственная площадка, на которой делается заказ."""

    name = models.CharField(max_length=255, unique=True, verbose_name="Название")
    address = models.CharField(max_length=255, blank=True, default="", verbose_name="Адрес")
    # Same field type as oauth.User.phone / client.Client.phone.
    phone = PhoneNumberField(blank=True, region="UZ", verbose_name="Телефон")
    ordering = models.IntegerField(default=0, verbose_name="Порядковый номер")

    class Meta:
        verbose_name = "Завод"
        verbose_name_plural = "Заводы"
        ordering = ["ordering", "name"]

    def __str__(self):
        return self.name


class Order(models.Model):
    id = models.BigAutoField(primary_key=True)
    # null=True only to bootstrap new rows (see save()) before a number is assigned;
    # always populated after the first save — see save() below.
    order_number = models.PositiveIntegerField(
        unique=True, db_index=True, null=True, blank=False, verbose_name=_("Номер заказа")
    )
    desc = models.TextField(_("Описание"), null=True, blank=True)
    price = MoneyField(max_digits=12, null=True, verbose_name="Вся сумма")
    lost_money = MoneyField(max_digits=12, null=True, verbose_name="Полученная сумма")
    discount = models.FloatField(default=0, verbose_name="Скидка")

    status = models.CharField(
        max_length=32,
        choices=OrderStatus.choices,
        default=OrderStatus.CREATED,
        verbose_name="Статус",
        db_index=True,
    )
    client = models.ForeignKey("client.Client", models.CASCADE, null=True, verbose_name="Клиент")
    metering = models.OneToOneField(
        "metering.Metering", models.CASCADE, blank=True, null=True, verbose_name="Замеры"
    )

    reception_date = models.DateField(verbose_name="Дата получение")
    end_date = models.DateField(verbose_name="Дата сдачи", null=True, blank=True)

    address = models.CharField(max_length=255, verbose_name="Адрес")
    address_link = models.URLField(
        max_length=1000, blank=True, null=True, verbose_name="Ссылка на яндекс карты"
    )

    design_type = models.ForeignKey(
        "design.DesignType", models.CASCADE, null=True, verbose_name="Дизайн"
    )
    # PROTECT: a factory that still has orders must not be deletable out from under
    # them. Back-filled to DEFAULT_FACTORY_NAME for pre-existing rows (migration 0023).
    factory = models.ForeignKey(Factory, models.PROTECT, verbose_name="Завод")
    folder = FilerFolderField(
        on_delete=models.SET_NULL, related_name="order_folder", null=True, blank=True
    )

    history = HistoricalRecords(excluded_fields=["price", "lost_money"])
    objects = OrderManager()

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"

        permissions = [
            (ORDER_CHANGE_STATUS_PERMISSION, "Order change status"),
            (ORDER_REVERSE_STATUS_PERMISSION, "Order reverse status"),
            (ORDER_VIEW_PRICE_PERMISSION, "Order price view"),
        ]

    def client_phone(self):
        return self.client.phone if self.client else None

    def __str__(self):
        return str(self.client)

    @property
    def total_price(self):
        return self.price * (1 - self.discount / 100)

    @property
    def other_money(self):
        """Ostatks — how much of the order is still unpaid.

        Delegates to the one implementation in order/admin_display.py, which returns
        "-" instead of raising when price/lost_money is missing or the two are in
        different currencies."""
        from .admin_display import order_money_left_display

        return order_money_left_display(self)

    def change_status(self, status):
        self.status = status
        self.save(update_fields=["status"])
        self.send_sms()

    def send_sms(self):
        from .services import send_order_status_sms

        send_order_status_sms(self)

    def save(self, *args, **kwargs):
        resolve_order_status_on_save(self)
        if self.pk is None and not self.order_number:
            # Auto-number = last assigned order_number + 1, not the pk (pk can have
            # gaps from deleted orders). Manual entry is blocked on the add form
            # (order_number isn't in OrderAdmin's add_fieldsets); editable afterwards
            # from the change form.
            last_number = Order.objects.aggregate(models.Max("order_number"))["order_number__max"]
            self.order_number = (last_number or 0) + 1
        super().save(*args, **kwargs)


@receiver(post_save, sender=Order)
def replace_order_folders(sender: Type[Order], instance: Order, created, **kwargs):
    from metering.constants import MeteringStatus

    if instance.metering is None:
        return
    instance.metering.design.confirm = True
    instance.metering.design.save(update_fields=["confirm"])
    if not created:
        return
    folder = create_folder(instance, "Заказ")
    instance.metering.folder.name = "Замеры"
    instance.metering.folder.parent = folder
    instance.metering.folder.save()
    instance.metering.status = MeteringStatus.sold_out
    instance.metering.save(update_fields=["status"])
    Folder.objects.filter(parent=instance.metering.folder).update(parent=folder)
