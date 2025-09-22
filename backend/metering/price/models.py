from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from filer.models.foldermodels import Folder
from djmoney.models.fields import MoneyField
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords
from core.djmoney import ConvertedCostManager


class Price(models.Model):
    metering = models.OneToOneField('metering.Metering', models.CASCADE)
    price = MoneyField(max_digits=12, blank=True, null=True)
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='price_folder', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    done = models.BooleanField(default=False)
    
    desc =  models.TextField(blank=True, null=True)

    history = HistoricalRecords()

    def __str__(self):
        return str(self.metering)


@receiver(post_save, sender=Price)
def create_price_folders(sender: Type[Price], instance: Price, created, **kwargs):
    if not created: return
    
    created_history = instance.history.order_by('history_date').first()
    created_user = created_history.history_user if created_history else None

    price_folder, _ = Folder.objects.get_or_create(
        name='Нарх чикариш',
        parent=instance.metering.folder,
        defaults={
            "owner": created_user
        }
    )

    instance.folder=price_folder
    instance.save()


class ObjectType(models.Model):
    """Kuxnya, shkaf"""
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name


class Calculate(models.Model):
    name = models.CharField(max_length=255)
    price = models.ForeignKey(Price, models.CASCADE)
    amount = MoneyField(max_digits=12, blank=True, null=True)
    objects = ConvertedCostManager(['amount'])
    obj = models.ForeignKey(ObjectType, models.PROTECT)
    history = HistoricalRecords()

    def __str__(self):
        return self.name


class InventoryType(models.Model):
    """Mexanizm, Tosh"""
    name = models.CharField(max_length=255, unique=True)
    obj = models.ForeignKey(ObjectType, models.CASCADE, null=True)

    def __str__(self):
        return ' '.join([self.name, f"({self.obj})"])


class Inventory(models.Model):
    """BLUM, GTV, Tosh xitoy"""
    name = models.CharField(max_length=255)
    type = models.ForeignKey(InventoryType, models.CASCADE)
    price = MoneyField(max_digits=12, blank=True, null=True)

    history = HistoricalRecords()

    objects = ConvertedCostManager(['price'], 'USD')

    def __str__(self):
        return self.name


class InventoryInCalculate(models.Model):
    inventory = models.ForeignKey(Inventory, models.PROTECT)
    calculate = models.ForeignKey(Calculate, models.PROTECT)
    count = models.IntegerField(default=1)
    price = MoneyField(max_digits=12, blank=True, null=True)

    objects = ConvertedCostManager(['price'])

    def __str__(self):
        return f"{self.inventory} * {self.count}"
