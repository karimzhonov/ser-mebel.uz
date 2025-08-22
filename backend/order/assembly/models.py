from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField
from filer.models.foldermodels import Folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords


class Assembly(models.Model):
    order = models.OneToOneField('order.Order', models.CASCADE)
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='assembly_files', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    done = models.BooleanField(default=False)
    installing_done = models.BooleanField(default=False)
    user = models.ForeignKey('oauth.User', models.PROTECT, blank=True, null=True)
    
    square = models.FloatField()
    price = MoneyField(max_digits=12, blank=True, null=True)
    
    history = HistoricalRecords()

    def __str__(self):
        return str(self.order)


@receiver(post_save, sender=Assembly)
def create_assembly_folders(sender: Type[Assembly], instance: Assembly, created, **kwargs):
    if not created: return
    
    folder, _ = Folder.objects.get_or_create(
        name='Сборка / Установка',
        parent=instance.order.folder,
        owner=instance.order.folder.owner,
    )
    instance.folder = folder
    instance.save(update_fields=['folder'])
