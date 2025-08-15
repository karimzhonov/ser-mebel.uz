from django.db import models
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords
from filer.fields.folder import FilerFolderField
from djmoney.models.fields import MoneyField
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

    design_folder = FilerFolderField(on_delete=models.SET_NULL, related_name='orders_design_folder', null=True)

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
