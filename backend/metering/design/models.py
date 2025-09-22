from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from djmoney.models.fields import MoneyField
from filer.models.foldermodels import Folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords


class Design(models.Model):
    metering = models.OneToOneField('metering.Metering', models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    done = models.BooleanField(default=False)
    confirm = models.BooleanField(default=False)

    history = HistoricalRecords()

    def __str__(self):
        return str(self.metering)


class DesignType(models.Model):
    name = models.CharField(max_length=255, null=True)
    design = models.ForeignKey(Design, models.CASCADE)
    folder = FilerFolderField(on_delete=models.SET_NULL, related_name='design_files', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.design})'


@receiver(post_save, sender=Design)
def create_design_type_folders(sender: Type[Design], instance: Design, created, **kwargs):
    if not created: return
    DesignType.objects.create(design=instance, name='Дизайн-1')


@receiver(post_save, sender=DesignType)
def create_design_type_folders(sender: Type[DesignType], instance: DesignType, created, **kwargs):
    if not created: return

    created_history = instance.design.history.order_by('history_date').first()
    created_user = created_history.history_user if created_history else None

    design_folder, _ = Folder.objects.get_or_create(
        name='Дизайн',
        parent=instance.design.metering.folder,
        defaults={'owner': created_user}
    )

    design_type_folder, _ = Folder.objects.get_or_create(
        name=instance.name,
        parent=design_folder,
        defaults={'owner': created_user}
    )

    instance.folder = design_type_folder
    instance.save()
