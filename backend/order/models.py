from typing import Type
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver
from simple_history.models import HistoricalRecords
from filer.models.foldermodels import Folder
from filer.fields.folder import FilerFolderField

from core.constants import Currency

from .constants import OrderStatus, ORDER_CHANGE_STATUS_PERMISSION, ORDER_REVERSE_STATUS_PERMISSION, ORDER_VIEW_PRICE_PERMISSION
from .managers import OrderManager


class Order(models.Model):
    desc = models.TextField(_('Описание'), null=True, blank=True)
    currency = models.CharField(max_length=10, choices=Currency.choices, default=Currency.dollar, verbose_name='Валюта')
    price = models.FloatField(verbose_name='Цена')
    advance = models.FloatField(verbose_name='Аванс')
    status = models.CharField(max_length=32, choices=OrderStatus.choices, default=OrderStatus.CREATED, verbose_name='Статус')
    client = models.ForeignKey('client.Client', models.PROTECT, null=True, verbose_name='Мижоз')
    metering = models.OneToOneField('metering.Metering', models.PROTECT, blank=True, null=True)

    reception_date = models.DateField(verbose_name='Дата получение')
    end_date = models.DateField(verbose_name='Дата сдачи')

    address = models.CharField(max_length=255, verbose_name='Адрес')
    address_link = models.URLField(max_length=1000, blank=True, null=True, verbose_name='Ссылка на яндекс карты')

    folder_documents = FilerFolderField(on_delete=models.SET_NULL, related_name='orders_document', null=True, blank=True)
    folder_images = FilerFolderField(on_delete=models.SET_NULL, related_name='orders_image', null=True, blank=True)
    folder_schemas = FilerFolderField(on_delete=models.SET_NULL, related_name='orders_schema', null=True, blank=True)

    history = HistoricalRecords()
    objects = OrderManager()

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'
        
        permissions = [
            (ORDER_CHANGE_STATUS_PERMISSION ,'Order change status'),
            (ORDER_REVERSE_STATUS_PERMISSION ,'Order reverse status'),
            (ORDER_VIEW_PRICE_PERMISSION, 'Order price view')
        ]
    
    def __str__(self):
        return str(self.client)
    
    def change_status(self, status):
        self.status = status
        self.save()
        self.send_sms()

    def send_sms(self):
        pass


@receiver(post_save, sender=Order)
def create_folders(sender: Type[Order], instance: Order, created, **kwargs):
    if not created: return
    
    created_history = instance.history.order_by('history_date').first()
    created_user = created_history.history_user if created_history else None

    parent_folder, _ = Folder.objects.get_or_create(
        name='orders',
        defaults={'owner': created_user}
    )

    order = Folder.objects.create(
        name=f'order-{instance.pk}',
        parent=parent_folder,
        owner=created_user
    )

    def _create_folder(name):
        return Folder.objects.create(
            name=name,
            parent=order,
            owner=created_user
        )

    folder_images = _create_folder('image')
    folder_documents = _create_folder('document')
    folder_schemas = _create_folder('schema')

    sender.objects.filter(pk=instance.pk).update(
        folder_images=folder_images, 
        folder_documents=folder_documents, 
        folder_schemas=folder_schemas
    )
