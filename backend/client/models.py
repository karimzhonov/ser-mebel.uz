from django.db import models
from phonenumber_field.modelfields import PhoneNumberField


class Client(models.Model):
    phone = PhoneNumberField(primary_key=True, region='UZ', verbose_name='Номер телефона')
    fio = models.CharField('ФИО', max_length=255)
    
    def __str__(self):
        return self.fio
    
    class Meta:
        verbose_name = 'Мижоз'
        verbose_name_plural = 'Мижозлар'