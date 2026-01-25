from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords
from oauth.models import User, METERING_PERMISSION
from core.utils import create_folder
from .constants import MeteringStatus, METERING_CHANGE_STATUS_PERMISSION


class Metering(models.Model):
    client = models.ForeignKey("client.Client", models.CASCADE, verbose_name='Мижоз')
    status = models.CharField(verbose_name='Статус', max_length=255, choices=MeteringStatus.choices, default=MeteringStatus.created)
    address = models.TextField(blank=True, null=True, verbose_name='Адрес')
    address_link = models.URLField(max_length=1000, blank=True, null=True, verbose_name='Адрес ссылка')
    create_date = models.DateTimeField(auto_now_add=True, verbose_name='Дата создание')
    desc = models.TextField(blank=True, null=True, verbose_name='Описание')
    
    date_time = models.DateTimeField(verbose_name='Дата замера', null=True, )
    invoice = models.OneToOneField('call_center.Invoice', models.CASCADE, blank=True, null=True, verbose_name='Call-center инвойс')
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='metering_folder', null=True, blank=True)

    history = HistoricalRecords()

    def __str__(self):
        return str(self.client)
    
    class Meta:
        verbose_name = 'Замер'
        verbose_name_plural = 'Замери'
        
        permissions = [
            (METERING_CHANGE_STATUS_PERMISSION ,'Metring change status'),
        ]
    

@receiver(post_save, sender=Metering)
def create_metering_folders(sender: Type[Metering], instance: Metering, created, **kwargs):
    if not created: return
    create_folder(instance, 'Замер')
    User.send_messages(METERING_PERMISSION, 'admin:metering_metering_change', {'object_id': instance.pk})
