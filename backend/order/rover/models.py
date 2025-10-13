from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField
from filer.models import Folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords
from accounting.constants import DefaultExpenseCategoryChoices
from oauth.models import User, ROVER_PERMISSION


class Rover(models.Model):
    order = models.OneToOneField('order.Order', models.CASCADE, verbose_name='Заказ')
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='rover_files', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    done = models.BooleanField(default=False, verbose_name='Выполнено')
    
    square = models.FloatField(verbose_name='Площадь')
    price = MoneyField(max_digits=12, blank=True, null=True, verbose_name='Нарх')
    
    history = HistoricalRecords()

    def __str__(self):
        return str(self.order)


@receiver(post_save, sender=Rover)
def create_rover_folders(sender: Type[Rover], instance: Rover, created, **kwargs):
    DefaultExpenseCategoryChoices.update_or_create_expense(
        DefaultExpenseCategoryChoices.rover, instance.order, instance.price, 
    )

    if not created: return
    User.send_messages(ROVER_PERMISSION, 'admin:rover_rover_change', {'object_id': instance.pk})
    
    folder, _ = Folder.objects.get_or_create(
        name='Ровер',
        parent=instance.order.folder,
        owner=instance.order.folder.owner,
    )
    instance.folder = folder
    instance.save(update_fields=['folder'])
