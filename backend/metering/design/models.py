from typing import Type
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from filer.models.foldermodels import Folder
from filer.fields.folder import FilerFolderField
from simple_history.models import HistoricalRecords
from metering.constants import OfferStage


class Design(models.Model):
    metering = models.OneToOneField("metering.Metering", models.CASCADE, verbose_name="Замер")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создание")
    done = models.BooleanField(default=False, verbose_name="Выполнено")
    confirm = models.BooleanField(default=False, verbose_name="Подтверждено")
    # Who draws it. Set when the measurer finishes the zamer (metering.services); the
    # bot task goes to this person only.
    user = models.ForeignKey(
        "oauth.User",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="design_tasks",
        verbose_name="Дизайнер",
    )

    # Stage 2 (docs/BOT_CONTRACT.md, "Dizayn va narx"). Invariant: done == stage in
    # (review, approved); confirm is True on approved. done/confirm stay for old readers.
    stage = models.CharField(
        max_length=10, choices=OfferStage.choices, default=OfferStage.work, db_index=True
    )
    due_at = models.DateTimeField(null=True, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        "oauth.User",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    round = models.PositiveSmallIntegerField(default=1)
    # bumped on every change the bot may have shown: versions reminders and stale cards
    rev = models.PositiveIntegerField(default=0)

    history = HistoricalRecords()

    class Meta:
        indexes = [
            models.Index(fields=["user", "stage", "due_at"], name="design_user_stage_due"),
            models.Index(
                fields=["due_at"], condition=models.Q(stage="work"), name="design_work_due"
            ),
            models.Index(fields=["stage", "done_at"], name="design_stage_done"),
        ]

    def __str__(self):
        return str(self.metering)


class DesignType(models.Model):
    name = models.CharField(max_length=255, null=True, verbose_name="Название")
    design = models.ForeignKey(Design, models.CASCADE, verbose_name="Дизайн")
    folder = FilerFolderField(
        on_delete=models.SET_NULL, related_name="design_files", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создание")

    def __str__(self):
        return f"{self.name} ({self.design})"


@receiver(post_save, sender=Design)
def create_default_design_variant(sender: Type[Design], instance: Design, created, **kwargs):
    """Every design starts with its first variant (its Filer folder is made by the
    DesignType receiver below). Also covers designs made in the legacy admin."""
    if not created:
        return
    DesignType.objects.create(design=instance, name="Дизайн-1")


@receiver(post_save, sender=DesignType)
def create_design_variant_folder(sender: Type[DesignType], instance: DesignType, created, **kwargs):
    if not created:
        return

    created_history = instance.design.history.order_by("history_date").first()
    created_user = created_history.history_user if created_history else None

    design_folder, _ = Folder.objects.get_or_create(
        name="Дизайн", parent=instance.design.metering.folder, defaults={"owner": created_user}
    )

    design_type_folder, _ = Folder.objects.get_or_create(
        name=instance.name, parent=design_folder, defaults={"owner": created_user}
    )

    instance.folder = design_type_folder
    instance.save()
