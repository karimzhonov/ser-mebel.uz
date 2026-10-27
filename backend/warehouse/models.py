"""Ombor (warehouse): what is in stock, how much, at what cost — and who may change it.

Stock is the sum of movements (kirim − chiqim). Product.quantity and avg_cost are a
cache kept by warehouse/services.py under a row lock, so lists stay fast.
"""

from django.conf import settings
from django.db import models

UNITS = [
    ("dona", "dona"),
    ("m", "metr"),
    ("m2", "m²"),
    ("m3", "m³"),
    ("kg", "kg"),
    ("l", "litr"),
    ("list", "list"),
    ("pachka", "pachka"),
    ("rulon", "rulon"),
    ("komplekt", "komplekt"),
]


class Product(models.Model):
    name = models.CharField(max_length=255, verbose_name="Nomi")
    code = models.CharField(max_length=64, blank=True, default="", verbose_name="Kod / artikul")
    category = models.CharField(max_length=128, blank=True, default="", verbose_name="Turi")
    unit = models.CharField(
        max_length=16, choices=UNITS, default="dona", verbose_name="O'lchov birligi"
    )
    min_quantity = models.DecimalField(
        max_digits=14, decimal_places=3, default=0, verbose_name="Minimal qoldiq"
    )
    quantity = models.DecimalField(
        max_digits=14, decimal_places=3, default=0, verbose_name="Qoldiq"
    )
    avg_cost = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, verbose_name="O'rtacha tannarx (so'm)"
    )
    is_active = models.BooleanField(default=True, verbose_name="Faol")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Mahsulot (ombor)"
        verbose_name_plural = "Mahsulotlar (ombor)"
        constraints = [
            models.UniqueConstraint(
                fields=["code"], condition=~models.Q(code=""), name="uniq_warehouse_product_code"
            )
        ]

    def __str__(self):
        return self.name


class Movement(models.Model):
    """One kirim (into the warehouse) or chiqim (out of it), with prices."""

    KIND = [("in", "Kirim"), ("out", "Chiqim")]

    number = models.PositiveIntegerField(unique=True, verbose_name="№")
    product = models.ForeignKey(
        Product, models.PROTECT, related_name="movements", verbose_name="Mahsulot"
    )
    kind = models.CharField(max_length=3, choices=KIND, db_index=True, verbose_name="Turi")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, verbose_name="Miqdor")
    unit_price = models.DecimalField(max_digits=16, decimal_places=2, verbose_name="Narxi (so'm)")
    total = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Summa (so'm)")
    date = models.DateField(db_index=True, verbose_name="Sana")
    # kirim: supplier; chiqim: who took it / where it went
    counterparty = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Kimdan / kimga"
    )
    order = models.ForeignKey(
        "order.Order",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="warehouse_movements",
        verbose_name="Buyurtma",
    )
    comment = models.TextField(blank=True, default="", verbose_name="Izoh")
    balance_after = models.DecimalField(
        max_digits=14, decimal_places=3, default=0, verbose_name="Qoldiq (keyin)"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,
        null=True,
        related_name="+",
        verbose_name="Kiritdi",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_cancelled = models.BooleanField(default=False, db_index=True, verbose_name="Bekor qilingan")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-date", "-number"]
        verbose_name = "Ombor harakati"
        verbose_name_plural = "Ombor harakatlari"

    def __str__(self):
        return f"#{self.number} {self.get_kind_display()} {self.product} {self.quantity}"


class WarehouseConfig(models.Model):
    """Singleton (pk=1): the one employee responsible for the warehouse (omborchi).
    Only they book kirim/chiqim and edit products."""

    keeper = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Omborga mas'ul xodim",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Omborchi: {self.keeper or '—'}"

    @classmethod
    def get(cls) -> "WarehouseConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
