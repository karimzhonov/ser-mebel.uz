from typing import Type

from constance import config
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.money import Money
from filer.fields.folder import FilerFolderField
from filer.models import Folder
from simple_history.models import HistoricalRecords

from ..assembly.models import Assembly
from ..painter.models import Painter
from ..rover.models import Rover


class Detailing(models.Model):
    order = models.OneToOneField("order.Order", models.CASCADE, verbose_name="Заказ")
    folder = FilerFolderField(
        on_delete=models.SET_NULL, related_name="detailing_files", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    done = models.BooleanField(default=False, verbose_name="Выполнено деталировка")
    working_done = models.BooleanField(default=False, verbose_name="Выполнено заказ на сырье")

    square = models.FloatField(default=0, verbose_name="Площадь")
    painter_square = models.FloatField(default=0, blank=True, verbose_name="Площадь покраски")
    rover_square = models.FloatField(default=0, blank=True, verbose_name="Площадь роверов")

    history = HistoricalRecords()

    def __str__(self):
        return str(self.order)


@receiver(post_save, sender=Detailing)
def create_detailing_folders(sender: Type[Detailing], instance: Detailing, created, **kwargs):
    # Every detailed order gets an Assembly, square=0 included: "Отправить в сборку"
    # (order/actions.py) has no target without one, and an order pushed into the
    # ASSEMBLY status with no Assembly row is invisible to assembly staff.
    if instance.square:
        Assembly.objects.update_or_create(
            order=instance.order,
            defaults={
                "square": instance.square,
                "price": Money(
                    amount=float(config.ASSEMBLY_PRICE_PER_SQUARE.amount) * instance.square,
                    currency=config.ASSEMBLY_PRICE_PER_SQUARE.currency,
                ),
            },
        )
    else:
        # get_or_create, not update_or_create: a zero square must not wipe out a
        # square/price someone entered on the Assembly by hand.
        Assembly.objects.get_or_create(
            order=instance.order,
            defaults={
                "square": 0,
                "price": Money(
                    amount=0,
                    currency=config.ASSEMBLY_PRICE_PER_SQUARE.currency,
                ),
            },
        )

    if instance.painter_square:
        Painter.objects.update_or_create(
            order=instance.order,
            defaults={
                "square": instance.painter_square,
            },
        )

    if instance.rover_square:
        Rover.objects.update_or_create(
            order=instance.order,
            defaults={
                "square": instance.rover_square,
                "price": Money(
                    amount=float(config.ROVER_PRICE_PER_SQUARE.amount) * instance.rover_square,
                    currency=config.ROVER_PRICE_PER_SQUARE.currency,
                ),
            },
        )

    if not created:
        return

    if instance.order.folder is None:
        return

    folder = Folder.objects.create(
        name="Деталировка / Производстьво",
        parent=instance.order.folder,
        owner=instance.order.folder.owner,
    )

    instance.folder = folder
    instance.save(update_fields=["folder"])
