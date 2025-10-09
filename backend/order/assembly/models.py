from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField
from filer.models.foldermodels import Folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords
from accounting.constants import DefaultExpenseCategoryChoices
from oauth.models import ASSEMBLY_PERMISSION, User
from .constants import ASSEMBLY_MANAGER_PERMISSION


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
    
    class Meta:
        permissions = [
            (ASSEMBLY_MANAGER_PERMISSION, 'Assembly manager')
        ]


@receiver(post_save, sender=Assembly)
def create_assembly_folders(sender: Type[Assembly], instance: Assembly, created, **kwargs):
    DefaultExpenseCategoryChoices.update_or_create_expense(
        DefaultExpenseCategoryChoices.assembly, instance.order, instance.price
    )
    if not created: return
    User.send_messages(ASSEMBLY_PERMISSION, 'admin:assembly_assembly_change', {'object_id': instance.pk})
    folder, _ = Folder.objects.get_or_create(
        name='Сборка / Установка',
        parent=instance.order.folder,
        owner=instance.order.folder.owner,
    )
    instance.folder = folder
    instance.save(update_fields=['folder'])
