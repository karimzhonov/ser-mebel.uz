from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField
from filer.models import Folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords
from accounting.constants import DefaultExpenseCategoryChoices


class Painter(models.Model):
    order = models.OneToOneField('order.Order', models.CASCADE)
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='painter_files', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    done = models.BooleanField(default=False)
    
    square = models.FloatField()
    price = MoneyField(max_digits=12, blank=True, null=True)

    history = HistoricalRecords()

    def __str__(self):
        return str(self.order)


@receiver(post_save, sender=Painter)
def create_painter_folders(sender: Type[Painter], instance: Painter, created, **kwargs):
    DefaultExpenseCategoryChoices.update_or_create_expense(
        DefaultExpenseCategoryChoices.painter, instance.order, instance.price
    )
    
    if not created: return
    
    folder, _ = Folder.objects.get_or_create(
        name='Моляр',
        parent=instance.order.folder,
        owner=instance.order.folder.owner,
    )

    instance.folder = folder
    instance.save(update_fields=['folder'])
