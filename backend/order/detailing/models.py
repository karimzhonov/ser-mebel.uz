from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.money import Money
from constance import config
from filer.models import Folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords
from ..assembly.models import Assembly
from ..rover.models import Rover
from ..painter.models import Painter


class Detailing(models.Model):
    order = models.OneToOneField('order.Order', models.CASCADE)
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='detailing_files', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    done = models.BooleanField(default=False)
    working_done = models.BooleanField(default=False)
    
    square = models.FloatField(default=0)
    painter_square = models.FloatField(default=0)
    rover_square = models.FloatField(default=0)
    
    history = HistoricalRecords()

    def __str__(self):
        return str(self.order)


@receiver(post_save, sender=Detailing)
def create_detailing_folders(sender: Type[Detailing], instance: Detailing, created, **kwargs):
    if instance.square:
        Assembly.objects.update_or_create(
            order=instance.order,
            defaults={
                'square': instance.square,
                'price': Money(amount=float(config.ASSEMBLY_PRICE_PER_SQUARE.amount) * instance.square, currency=config.ASSEMBLY_PRICE_PER_SQUARE.currency)
            }
        )

    if instance.painter_square:
        Painter.objects.update_or_create(
            order=instance.order,
            defaults={
                'square': instance.painter_square,
                'price': Money(amount=float(config.PAINTER_PRICE_PER_SQUARE.amount) * instance.painter_square, currency=config.PAINTER_PRICE_PER_SQUARE.currency)
            }
        )

    if instance.rover_square:
        Rover.objects.update_or_create(
            order=instance.order,
            defaults={
                'square': instance.rover_square,
                'price': Money(amount=float(config.ROVER_PRICE_PER_SQUARE.amount) * instance.rover_square, currency=config.ROVER_PRICE_PER_SQUARE.currency)
            }
        )

    if not created: return
    
    folder = Folder.objects.create(
        name='Деталировка / Производстьво',
        parent=instance.order.folder,
        owner=instance.order.folder.owner,
    )

    instance.folder = folder
    instance.save(update_fields=['folder'])