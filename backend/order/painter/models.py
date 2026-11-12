from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField
from filer.models import Folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords
from django.conf import settings


class PainterType(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название")
    price = MoneyField(max_digits=12, verbose_name="Нарх")
    user = models.ForeignKey(
        "oauth.User", verbose_name="Пользователь", on_delete=models.SET_NULL, null=True
    )
    outsource = models.BooleanField(default=False, verbose_name="Autsors")

    def __str__(self):
        return self.name


class PainterState(models.TextChoices):
    NEW = "new", "Ishda"
    DONE = "done", "Bajarildi"


class Painter(models.Model):
    order = models.OneToOneField("order.Order", models.CASCADE, verbose_name="Заказ")
    folder = FilerFolderField(
        on_delete=models.SET_NULL, related_name="painter_files", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    done = models.BooleanField(default=False, verbose_name="Выполнено")
    # Deprecated: the teams of a job live in PainterPart (one row per team, with its m²).
    # Product code no longer reads this column; the frozen admin still writes it.
    type = models.ForeignKey(PainterType, models.SET_NULL, verbose_name="Тип", null=True)

    square = models.FloatField(verbose_name="Площадь")
    price = MoneyField(max_digits=12, blank=True, null=True, verbose_name="Нарх")

    started_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name="Ish boshlangan"
    )
    due_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="Muddat")
    due_auto = models.BooleanField(default=False, verbose_name="Muddat avtomatik qo'yilgan")
    due_set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )
    due_set_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="", verbose_name="Izoh")
    rev = models.PositiveIntegerField(default=0)
    done_at = models.DateTimeField(null=True, blank=True, verbose_name="Bajarilgan")
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )

    history = HistoricalRecords()

    def __str__(self):
        return str(self.order)

    @property
    def state(self) -> str:
        return PainterState.DONE if self.done else PainterState.NEW

    @property
    def state_label(self) -> str:
        return PainterState(self.state).label

    @property
    def overdue(self) -> bool:
        from accounting.text import today

        return not self.done and self.due_date is not None and today() > self.due_date

    @property
    def days_late(self) -> int:
        if not self.overdue:
            return 0
        from accounting.text import today

        return (today() - self.due_date).days

    class Meta:
        verbose_name = "Моляр"
        verbose_name_plural = "Моляры"


class PainterPart(models.Model):
    """One team's share of a Molyar job (m²). Every per-team action (task card, deadline,
    «Bajardim», reminders) is per part; `Painter.done` is the job flag (all m² covered and
    every part done)."""

    painter = models.ForeignKey(
        Painter, models.CASCADE, related_name="parts", verbose_name="Molyar ishi"
    )
    type = models.ForeignKey(
        PainterType, models.PROTECT, related_name="parts", verbose_name="Jamoa"
    )
    square = models.FloatField(verbose_name="Maydon")
    price = MoneyField(max_digits=12, blank=True, null=True, verbose_name="Нарх")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name="Ish boshlangan"
    )
    due_date = models.DateField(null=True, blank=True, verbose_name="Muddat")
    due_auto = models.BooleanField(default=False)
    due_set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )
    due_set_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="", verbose_name="Izoh")
    rev = models.PositiveIntegerField(default=0)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Моляр: qism"
        verbose_name_plural = "Моляр: qismlar"
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["painter", "type"], name="painterpart_unique_team")
        ]
        indexes = [models.Index(fields=["done", "due_date"], name="painterpart_open_due")]

    def __str__(self):
        return f"{self.type_id} {self.square}"

    @property
    def user(self):
        return self.type.user if self.type_id and self.type.user_id else None

    @property
    def state(self) -> str:
        return PainterState.DONE if self.done else PainterState.NEW

    @property
    def state_label(self) -> str:
        return PainterState(self.state).label

    @property
    def overdue(self) -> bool:
        from accounting.text import today

        return not self.done and self.due_date is not None and today() > self.due_date

    @property
    def days_late(self) -> int:
        if not self.overdue:
            return 0
        from accounting.text import today

        return (today() - self.due_date).days


@receiver(post_save, sender=Painter)
def create_painter_folders(
    sender: Type[Painter], instance: Painter, created, update_fields, **kwargs
):
    # The admin (frozen) saves with update_fields=["type"]; the service flags its own save.
    if (
        update_fields
        and "type" in update_fields
        and instance.type_id
        and not getattr(instance, "_via_service", False)
    ):
        from . import services

        services.legacy_type_saved(instance)

    if not created:
        return

    if instance.order.folder is None:
        return

    folder, _ = Folder.objects.get_or_create(
        name="Моляр",
        parent=instance.order.folder,
        owner=instance.order.folder.owner,
    )

    instance.folder = folder
    instance.save(update_fields=["folder"])
