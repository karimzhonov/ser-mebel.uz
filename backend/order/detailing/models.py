from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField
from core.utils import create_folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords


class Detailing(models.Model):
    order = models.OneToOneField('order.Order', models.CASCADE)
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='detailing_files', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    done = models.BooleanField(default=False)
    
    square = models.FloatField()
    painter_square = models.FloatField(default=0)
    rover_square = models.FloatField(default=0)
    
    price = MoneyField(max_digits=12, blank=True, null=True)
    painter_price = MoneyField(max_digits=12, blank=True, null=True)
    rover_price = MoneyField(max_digits=12, blank=True, null=True)

    history = HistoricalRecords()

    def __str__(self):
        return str(self.order)


@receiver(post_save, sender=Detailing)
def create_detailing_folders(sender: Type[Detailing], instance: Detailing, created, **kwargs):
    if not created: return
    create_folder(instance, 'detailing')