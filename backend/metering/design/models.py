from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField

from core.utils import create_folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords


class Design(models.Model):
    metering = models.OneToOneField('metering.Metering', models.PROTECT)
    price = MoneyField(blank=True, null=True)
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='design_files', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    done = models.BooleanField(default=False)

    history = HistoricalRecords()

    def __str__(self):
        return str(self.metering)


@receiver(post_save, sender=Design)
def create_design_folders(sender: Type[Design], instance: Design, created, **kwargs):
    if not created: return
    create_folder(instance, 'design')
