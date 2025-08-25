from typing import Type
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver
from simple_history.models import HistoricalRecords
from filer.fields.folder import FilerFolderField
from filer.models.foldermodels import Folder
from djmoney.models.fields import MoneyField
from core.utils import create_folder
from accounting.constants import DefaultExpenseCategoryChoices

from .constants import OrderStatus, ORDER_CHANGE_STATUS_PERMISSION, ORDER_REVERSE_STATUS_PERMISSION, ORDER_VIEW_PRICE_PERMISSION
from .managers import OrderManager


class Order(models.Model):
    desc = models.TextField(_('Описание'), null=True, blank=True)
    price = MoneyField(max_digits=12, null=True)
    lost_money = MoneyField(max_digits=12, null=True)

    status = models.CharField(max_length=32, choices=OrderStatus.choices, default=OrderStatus.CREATED, verbose_name='Статус')
    client = models.ForeignKey('client.Client', models.PROTECT, null=True, verbose_name='Мижоз')
    metering = models.OneToOneField('metering.Metering', models.PROTECT, blank=True, null=True)

    reception_date = models.DateField(verbose_name='Дата получение')
    end_date = models.DateField(verbose_name='Дата сдачи')

    address = models.CharField(max_length=255, verbose_name='Адрес')
    address_link = models.URLField(max_length=1000, blank=True, null=True, verbose_name='Ссылка на яндекс карты')

    design_type = models.ForeignKey("design.DesignType", models.PROTECT, null=True)
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='order_folder', null=True, blank=True)
    
    history = HistoricalRecords(excluded_fields=["price", "lost_money"])
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
        self.save(update_fields=['status'])
        self.send_sms()

    def send_sms(self):
        pass


@receiver(post_save, sender=Order)
def replace_order_folders(sender: Type[Order], instance: Order, created, **kwargs):
    if not created: return
    DefaultExpenseCategoryChoices.update_or_create_expense(
        DefaultExpenseCategoryChoices.design, instance
    )
    folder = create_folder(instance, 'Заказ')
    instance.metering.folder.parent = folder
    instance.metering.folder.save()
    Folder.objects.filter(parent=instance.metering.folder).update(parent=folder)
    