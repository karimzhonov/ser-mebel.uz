from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords
from core.utils import create_folder
from .constants import (
    MeteringStatus,
    METERING_CHANGE_STATUS_PERMISSION,
    METERING_MANAGE_PERMISSION,
    METERING_PRESENT_PERMISSION,
    ClientResult,
    NextStep,
)


class Metering(models.Model):
    client = models.ForeignKey("client.Client", models.CASCADE, verbose_name="Мижоз")
    status = models.CharField(
        verbose_name="Статус",
        max_length=255,
        choices=MeteringStatus.choices,
        default=MeteringStatus.created,
        db_index=True,
    )
    address = models.TextField(blank=True, null=True, verbose_name="Адрес")
    address_link = models.URLField(
        max_length=1000, blank=True, null=True, verbose_name="Адрес ссылка"
    )
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    create_date = models.DateTimeField(auto_now_add=True, verbose_name="Дата создание")
    desc = models.TextField(blank=True, null=True, verbose_name="Описание")

    date_time = models.DateTimeField(
        verbose_name="Дата замера",
        null=True,
    )
    invoice = models.OneToOneField(
        "call_center.Invoice",
        models.CASCADE,
        blank=True,
        null=True,
        verbose_name="Call-center инвойс",
    )
    folder = FilerFolderField(
        on_delete=models.SET_NULL, related_name="metering_folder", null=True, blank=True
    )

    # Zamer stage 1: who measures, and what happened (docs/BOT_CONTRACT.md "Zamer").
    measurer = models.ForeignKey(
        "oauth.User",
        models.PROTECT,
        null=True,
        blank=True,
        related_name="measured_meterings",
        verbose_name="Zamerchi",
    )
    created_by = models.ForeignKey(
        "oauth.User",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    scheduled_at = models.DateTimeField(
        null=True, blank=True, help_text="When the measurer was told"
    )
    measured_at = models.DateTimeField(null=True, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        "oauth.User",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    result_note = models.TextField(blank=True, default="")
    next_step = models.CharField(max_length=20, blank=True, default="", choices=NextStep.choices)
    cancel_reason = models.TextField(blank=True, default="")
    # Stage 2: the «menejer» who shows the design / price to the client and records the
    # answer (one per metering, for both), and the client's final result.
    manager = models.ForeignKey(
        "oauth.User",
        models.PROTECT,
        null=True,
        blank=True,
        related_name="presented_meterings",
        verbose_name="Menejer",
    )
    client_result = models.CharField(
        max_length=20, blank=True, default="", choices=ClientResult.choices
    )
    # Bumped on every status / date_time / measurer change: versions the reminders and the
    # bot's stale-message check.
    rev = models.PositiveIntegerField(default=0)

    history = HistoricalRecords()

    def __str__(self):
        return str(self.client)

    class Meta:
        verbose_name = "Замер"
        verbose_name_plural = "Замери"

        permissions = [
            (METERING_CHANGE_STATUS_PERMISSION, "Metring change status"),
            (
                METERING_MANAGE_PERMISSION,
                "Zamerlar rahbari: barcha zamerlar, zamerchini almashtirish",
            ),
            (METERING_PRESENT_PERMISSION, "Menejer: dizayn/narxni mijozga ko'rsatadi"),
        ]
        indexes = [
            models.Index(fields=["measurer", "status", "date_time"]),
            models.Index(
                fields=["date_time"],
                condition=models.Q(status__in=["created", "other_day"]),
                name="met_open_due",
            ),
        ]


@receiver(post_save, sender=Metering)
def create_metering_folders(sender: Type[Metering], instance: Metering, created, **kwargs):
    if not created:
        return
    create_folder(instance, "Замер")


class OfferAnswer(models.Model):
    """The manager's answer about the design / price, as told by the client."""

    metering = models.ForeignKey(Metering, models.CASCADE, related_name="offer_answers")
    kind = models.CharField(max_length=10)  # design | price
    round = models.PositiveSmallIntegerField(default=1)
    answer = models.CharField(max_length=10)  # OfferAnswerKind
    comment = models.TextField(blank=True, default="")
    due_at = models.DateTimeField(null=True, blank=True)
    by = models.ForeignKey("oauth.User", models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["metering", "kind"])]
