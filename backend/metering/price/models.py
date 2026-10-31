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
    # Who calculates it; the task is sent to this person only when set.
    user = models.ForeignKey(
        "oauth.User",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="price_tasks",
        verbose_name="Ответственный за расчёт",
    )

    desc = models.TextField(blank=True, null=True, verbose_name="Описание")
    # Commercial offer (PDF): how the client is addressed («Хурматли …») and the
    # variant name on the total page («Премиум»). Empty = the client's name / nothing.
    client_title = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Murojaat (PDF)"
    )
    variant = models.CharField(max_length=64, blank=True, default="", verbose_name="Variant")

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
    # Decor is sold by the square metre and the client sees m²; other furniture is
    # priced by m² too, but the offer shows its size (height × width × depth) instead.
    show_area = models.BooleanField(default=False, verbose_name="PDF'da kv. m (dekor)")

    def __str__(self):
        return self.name


class RoomType(models.Model):
    """Oshxona, Yotoqxona, Sanuzel … — what a price calculation starts from.
    `object_types` = which furniture fits this room; empty = any."""

    name = models.CharField(max_length=255, unique=True, verbose_name="Nomi")
    icon = models.CharField(max_length=8, blank=True, default="", verbose_name="Belgi")
    ordering = models.IntegerField(default=0, verbose_name="Tartib")
    object_types = models.ManyToManyField(
        ObjectType, blank=True, related_name="room_types", verbose_name="Mos mebellar"
    )

    class Meta:
        ordering = ["ordering", "name"]
        verbose_name = "Xona turi"
        verbose_name_plural = "Xona turlari"

    def __str__(self):
        return self.name


class Room(models.Model):
    """One room of one calculation: «Yotoqxona 2». Its furniture are Calculate rows."""

    price = models.ForeignKey(
        Price, models.CASCADE, related_name="rooms", verbose_name="Hisob-kitob"
    )
    room_type = models.ForeignKey(
        RoomType, models.PROTECT, related_name="rooms", verbose_name="Xona turi"
    )
    name = models.CharField(max_length=255, verbose_name="Nomi")
    ordering = models.IntegerField(default=0, verbose_name="Tartib")

    class Meta:
        ordering = ["ordering", "id"]
        verbose_name = "Xona"
        verbose_name_plural = "Xonalar"

    def __str__(self):
        return self.name


class RoomImage(models.Model):
    """A render / drawing shown on the room's page of the offer PDF (a filer image
    stored in the calculation's folder)."""

    room = models.ForeignKey(Room, models.CASCADE, related_name="images", verbose_name="Xona")
    # set = a picture of this piece of furniture (its card in the offer shows it next
    # to the materials and price); empty = a render / drawing of the whole room
    calculate = models.ForeignKey(
        "Calculate",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="images",
        verbose_name="Mebel",
    )
    file = models.ForeignKey("filer.Image", models.CASCADE, related_name="+", verbose_name="Rasm")
    ordering = models.IntegerField(default=0, verbose_name="Tartib")

    class Meta:
        ordering = ["ordering", "id"]
        verbose_name = "Xona rasmi"
        verbose_name_plural = "Xona rasmlari"

    def __str__(self):
        return f"{self.room} — {self.file_id}"


class Calculate(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название")
    price = models.ForeignKey(Price, models.CASCADE, verbose_name="Цена")
    # null = made before rooms existed (shown as «Boshqa»)
    room = models.ForeignKey(
        Room,
        models.CASCADE,
        null=True,
        blank=True,
        related_name="calculations",
        verbose_name="Xona",
    )
    note = models.TextField(blank=True, default="", verbose_name="Qo'shimcha")
    color = models.CharField(max_length=255, blank=True, default="", verbose_name="Rang")
    # kv / pog chosen for this piece ("" = the object type's default) and its size in mm:
    # kv. m = height × width, pog. m = width; depth is only printed
    unit = models.CharField(
        max_length=8,
        blank=True,
        default="",
        choices=ObjectType.COUNT_NAMES,
        verbose_name="O'lchov birligi",
    )
    height = models.PositiveIntegerField(null=True, blank=True, verbose_name="Bo'yi (mm)")
    width = models.PositiveIntegerField(null=True, blank=True, verbose_name="Eni (mm)")
    depth = models.PositiveIntegerField(null=True, blank=True, verbose_name="Chuqurligi (mm)")
    # amount = manual_amount when set, else auto_amount (catalog lines + accessories)
    auto_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Avtomatik narx"
    )
    manual_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Yakuniy narx (qo'lda)"
    )
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


class CalcAccessory(models.Model):
    """An accessory on one piece of furniture: from the catalog or typed by hand,
    with an optional picture shown in the offer."""

    calculate = models.ForeignKey(
        Calculate, models.CASCADE, related_name="accessories", verbose_name="Mebel"
    )
    inventory = models.ForeignKey(
        Inventory,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Katalogdan",
    )
    name = models.CharField(max_length=255, verbose_name="Nomi")
    count = models.FloatField(default=1, verbose_name="Soni")
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Narxi ($)"
    )
    image = models.ForeignKey(
        "filer.Image",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Rasm",
    )
    ordering = models.IntegerField(default=0, verbose_name="Tartib")

    class Meta:
        ordering = ["ordering", "id"]
        verbose_name = "Aksessuar"
        verbose_name_plural = "Aksessuarlar"

    def __str__(self):
        return self.name

    @property
    def amount(self):
        return round(float(self.unit_price) * float(self.count or 0), 2)


class PriceVersion(models.Model):
    """A snapshot of the offer as it was given to the client (taxminiy → yakuniy)."""

    price = models.ForeignKey(
        Price, models.CASCADE, related_name="versions", verbose_name="Hisob-kitob"
    )
    number = models.PositiveIntegerField(verbose_name="№")
    label = models.CharField(max_length=255, blank=True, default="", verbose_name="Izoh")
    total = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Jami ($)")
    data = models.JSONField(verbose_name="Taklif")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "oauth.User", models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-number"]
        unique_together = [("price", "number")]
        verbose_name = "Taklif versiyasi"
        verbose_name_plural = "Taklif versiyalari"

    def __str__(self):
        return f"{self.price} v{self.number}"
