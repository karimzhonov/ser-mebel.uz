from typing import Type

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords

from core.djmoney import ConvertedCostManager

from .services import notify_and_create_price_folder


class Price(models.Model):
    metering = models.OneToOneField(
        "metering.Metering", models.CASCADE, verbose_name="Замер", blank=True, null=True
    )
    price = MoneyField(max_digits=12, blank=True, null=True, verbose_name="Цена")
    folder = FilerFolderField(
        on_delete=models.SET_NULL, related_name="price_folder", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создание")
    done = models.BooleanField(default=False, verbose_name="Выполнено")

    desc = models.TextField(blank=True, null=True, verbose_name="Описание")

    history = HistoricalRecords()

    def __str__(self):
        return str(self.metering or self.pk)

    class Meta:
        verbose_name = "Расчёт цены"
        verbose_name_plural = "Расчёт цены"


@receiver(post_save, sender=Price)
def create_price_folders(sender: Type[Price], instance: Price, created, **kwargs):
    if not created:
        return
    notify_and_create_price_folder(instance)


class ObjectType(models.Model):
    """Kuxnya, shkaf"""

    COUNT_NAMES = (("kv", "Кв. м."), ("pog", "Пог. м."))

    name = models.CharField(max_length=255, unique=True, verbose_name="Название")
    count_name = models.CharField(
        max_length=255, choices=COUNT_NAMES, default="kv", verbose_name="Кол-во тип"
    )

    def __str__(self):
        return self.name


class Calculate(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название")
    price = models.ForeignKey(Price, models.CASCADE, verbose_name="Цена")
    amount = MoneyField(max_digits=12, blank=True, null=True, verbose_name="Сумма (Итого)")
    count = models.FloatField(null=True, verbose_name="Кв. м. / Пог м.")
    obj = models.ForeignKey(ObjectType, models.CASCADE, verbose_name="Объект")

    history = HistoricalRecords()
    objects = ConvertedCostManager(["amount"])

    def __str__(self):
        return self.name


class InventoryType(models.Model):
    """Mexanizm, Tosh"""

    TYPE_KV = 1
    TYPE_COUNT = 2
    TYPES = (
        (TYPE_KV, "Кв. / Пог м."),
        (TYPE_COUNT, "Кол-во"),
    )

    name = models.CharField(max_length=255, verbose_name="Название")
    obj = models.ForeignKey(ObjectType, models.CASCADE, null=True, verbose_name="Объект")
    type = models.IntegerField(default=TYPE_COUNT, choices=TYPES, verbose_name="Тип")
    ordering = models.IntegerField(default=0, verbose_name="Порядковый номер")

    def __str__(self):
        return " ".join([self.name, f"({self.obj})"])

    class Meta:
        verbose_name = "Тип инвентаря"
        verbose_name_plural = "Типы инвентаря"
        ordering = ["ordering"]


class Inventory(models.Model):
    """BLUM, GTV, Tosh xitoy"""

    name = models.CharField(max_length=255, verbose_name="Название")
    type = models.ForeignKey(InventoryType, models.CASCADE, verbose_name="Тип")
    price = MoneyField(max_digits=12, blank=True, null=True, verbose_name="Цена")

    history = HistoricalRecords()

    objects = ConvertedCostManager(["price"], "USD")

    def __str__(self):
        return f"{self.name} - {self.price}"


class InventoryInCalculate(models.Model):
    inventory = models.ForeignKey(Inventory, models.CASCADE, verbose_name="Инвентарь")
    calculate = models.ForeignKey(Calculate, models.CASCADE, verbose_name="Калькуляция")
    count = models.FloatField(default=1, verbose_name="Кол-во")
    price = MoneyField(max_digits=12, blank=True, null=True, verbose_name="Цена")

    objects = ConvertedCostManager(["price"])

    def __str__(self):
        return f"{self.inventory} * {self.count}"
