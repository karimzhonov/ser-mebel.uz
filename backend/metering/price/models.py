from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from filer.models.foldermodels import Folder
from djmoney.models.fields import MoneyField
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords


class Price(models.Model):
    metering = models.OneToOneField('metering.Metering', models.PROTECT)
    price = MoneyField(max_digits=12, blank=True, null=True)
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='price_folder', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    done = models.BooleanField(default=False)
    
    desc =  models.TextField(blank=True, null=True)

    history = HistoricalRecords()

    def __str__(self):
        return str(self.metering)


@receiver(post_save, sender=Price)
def create_price_folders(sender: Type[Price], instance: Price, created, **kwargs):
    if not created: return
    
    created_history = instance.history.order_by('history_date').first()
    created_user = created_history.history_user if created_history else None

    parent_folder, _ = Folder.objects.get_or_create(
        name='price',
        defaults={'owner': created_user}
    )

    price_folder = Folder.objects.create(
        name=f'price-{instance.pk}',
        parent=parent_folder,
        owner=created_user
    )

    sender.objects.filter(pk=instance.pk).update(folder=price_folder)
