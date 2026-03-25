from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField
from filer.models import Folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords
from accounting.constants import DefaultExpenseCategoryChoices
from django.urls import reverse_lazy


class PainterType(models.Model):
    name = models.CharField(max_length=255, verbose_name='Название')
    price = MoneyField(max_digits=12, verbose_name='Нарх')
    user = models.ForeignKey('oauth.User', verbose_name='Пользователь', on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return self.name


class Painter(models.Model):
    order = models.OneToOneField('order.Order', models.CASCADE, verbose_name='Заказ')
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='painter_files', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')
    done = models.BooleanField(default=False, verbose_name='Выполнено')
    type = models.ForeignKey(PainterType, models.CASCADE, verbose_name='Тип', null=True)
    
    square = models.FloatField(verbose_name='Площадь')
    price = MoneyField(max_digits=12, blank=True, null=True, verbose_name='Нарх')

    history = HistoricalRecords()

    def __str__(self):
        return str(self.order)


@receiver(post_save, sender=Painter)
def create_painter_folders(sender: Type[Painter], instance: Painter, created, update_fields, **kwargs):
    DefaultExpenseCategoryChoices.update_or_create_expense(
        DefaultExpenseCategoryChoices.painter, instance.order, instance.price
    )

    if "type" in update_fields:
        instance.type.user.send_message(reverse_lazy('admin:painter_painter_change', kwargs={'object_id': instance.pk}))
    
    if not created: return
    
    folder, _ = Folder.objects.get_or_create(
        name='Моляр',
        parent=instance.order.folder,
        owner=instance.order.folder.owner,
    )

    instance.folder = folder
    instance.save(update_fields=['folder'])
