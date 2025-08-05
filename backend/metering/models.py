from django.db import models

from core.constants import Currency

from .constants import MeteringStatus, METERING_CHANGE_STATUS_PERMISSION


class Metering(models.Model):
    client = models.ForeignKey("client.Client", models.PROTECT, verbose_name='Мижоз')
    status = models.CharField(verbose_name='Статус', max_length=255, choices=MeteringStatus.choices, default=MeteringStatus.created)
    address = models.TextField(blank=True, null=True, verbose_name='Адрес')
    address_link = models.URLField(max_length=1000, blank=True, null=True, verbose_name='Адрес ссылка')
    create_date = models.DateTimeField(auto_now_add=True, verbose_name='Дата создание')
    currency = models.CharField(max_length=255, choices=Currency.choices, default=Currency.dollar, verbose_name='Курс')
    price = models.FloatField(editable=False, null=True, verbose_name='Цена')
    
    invoice = models.OneToOneField('call_center.Invoice', models.PROTECT, blank=True, null=True, verbose_name='Call-center инвойс')

    def __str__(self):
        return str(self.client)
    
    class Meta:
        verbose_name = 'Замер'
        verbose_name_plural = 'Замери'
        
        permissions = [
            (METERING_CHANGE_STATUS_PERMISSION ,'Metring change status'),
        ]
        
{
    "product": "product_id",
    "value": "120",
    "unit": "p.meter" # kv.meter, dona, meter,
}