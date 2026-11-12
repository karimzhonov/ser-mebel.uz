from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField
from filer.models import Folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords
from django.conf import settings


class RoverState(models.TextChoices):
    """new -> (worker hands in) checking -> (checker confirms) done."""

    NEW = "new", "Ishda"
    CHECKING = "checking", "Tekshiruvda"
    DONE = "done", "Bajarildi"


class Rover(models.Model):
    order = models.OneToOneField("order.Order", models.CASCADE, verbose_name="Заказ")
    folder = FilerFolderField(
        on_delete=models.SET_NULL, related_name="rover_files", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    done = models.BooleanField(default=False, verbose_name="Выполнено")

    square = models.FloatField(verbose_name="Площадь")
    price = MoneyField(max_digits=12, blank=True, null=True, verbose_name="Нарх")

    submitted_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Tekshiruvga yuborilgan"
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )
    checked_at = models.DateTimeField(null=True, blank=True, verbose_name="Tasdiqlangan")
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )

    due_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="Muddat")
    due_auto = models.BooleanField(default=False, verbose_name="Muddat avtomatik qo'yilgan")
    due_set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )
    due_set_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="", verbose_name="Izoh")
    rev = models.PositiveIntegerField(default=0)

    history = HistoricalRecords()

    def __str__(self):
        return str(self.order)

    @property
    def state(self) -> str:
        if self.done:
            return RoverState.DONE
        return RoverState.CHECKING if self.submitted_at else RoverState.NEW

    @property
    def state_label(self) -> str:
        return RoverState(self.state).label

    @property
    def overdue(self) -> bool:
        from accounting.text import today

        return (
            self.state == RoverState.NEW and self.due_date is not None and today() > self.due_date
        )

    @property
    def days_late(self) -> int:
        if not self.overdue:
            return 0
        from accounting.text import today

        return (today() - self.due_date).days

    class Meta:
        verbose_name = "Ровер"
        verbose_name_plural = "Роверы"


@receiver(post_save, sender=Rover)
def create_rover_folders(sender: Type[Rover], instance: Rover, created, **kwargs):
    if not created:
        return
    from . import services

    services.announce_new_rover(instance)

    if instance.order.folder is None:
        return

    folder, _ = Folder.objects.get_or_create(
        name="Ровер",
        parent=instance.order.folder,
        owner=instance.order.folder.owner,
    )
    instance.folder = folder
    instance.save(update_fields=["folder"])
