from typing import Type

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField
from filer.fields.folder import FilerFolderField
from filer.models.foldermodels import Folder
from simple_history.models import HistoricalRecords

from .constants import ASSEMBLY_MANAGER_PERMISSION


class AssemblyState(models.TextChoices):
    NEW = "new", "Ishda"
    ASSEMBLED = "assembled", "Yig'ildi"
    DONE = "done", "O'rnatildi"


class Assembly(models.Model):
    order = models.OneToOneField("order.Order", models.CASCADE, verbose_name="Заказ")
    folder = FilerFolderField(
        on_delete=models.SET_NULL, related_name="assembly_files", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    done = models.BooleanField(default=False, verbose_name="Выполнено сборка")
    installing_done = models.BooleanField(default=False, verbose_name="Выполнено установка")
    user = models.ForeignKey(
        "oauth.User", models.CASCADE, blank=True, null=True, verbose_name="Сборщик"
    )

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
    # `done` already means «yig'ildi»; finished_* is the installation (installing_done)
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="O'rnatilgan")
    finished_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+"
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Сборка/Установка"
        verbose_name_plural = "Сборки/Установки"
        permissions = [(ASSEMBLY_MANAGER_PERMISSION, "Assembly manager")]

    def __str__(self):
        return str(self.order)

    @property
    def state(self) -> str:
        if self.installing_done:
            return AssemblyState.DONE
        return AssemblyState.ASSEMBLED if self.done else AssemblyState.NEW

    @property
    def state_label(self) -> str:
        return AssemblyState(self.state).label

    @property
    def overdue(self) -> bool:
        from accounting.text import today

        return not self.installing_done and self.due_date is not None and today() > self.due_date

    @property
    def days_late(self) -> int:
        if not self.overdue:
            return 0
        from accounting.text import today

        return (today() - self.due_date).days


@receiver(post_save, sender=Assembly)
def create_assembly_folders(sender: Type[Assembly], instance: Assembly, created, **kwargs):
    if not created:
        return
    if instance.order.folder is None:
        return

    folder, _ = Folder.objects.get_or_create(
        name="Сборка / Установка",
        parent=instance.order.folder,
        owner=instance.order.folder.owner,
    )
    instance.folder = folder
    instance.save(update_fields=["folder"])
