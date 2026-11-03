from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .constants import LeadSource, NoteKind, SolutionChoice


class Invoice(models.Model):
    client = models.ForeignKey("client.Client", models.PROTECT, verbose_name="Мижоз")
    create_date = models.DateTimeField("Дата создание", auto_now_add=True)
    update_date = models.DateTimeField("Дата изменение", auto_now=True)
    # Cache of the latest "note" (InvoiceNote); the notes are the source of truth.
    desc = models.TextField("Описание", blank=True, null=True)
    solution = models.IntegerField(
        "Код ответа", choices=SolutionChoice.choices, default=None, null=True, db_index=True
    )
    source = models.CharField(  # noqa: DJ001 - NULL = not set (old leads)
        "Manba", max_length=20, choices=LeadSource.choices, null=True, blank=True, db_index=True
    )
    # Where the client lives: a map point (source of truth), the typed address and the raw
    # pasted link. Inherited by the metering and the order created from this lead.
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    address = models.CharField("Manzil", max_length=255, blank=True, default="")
    address_link = models.URLField("Xarita havolasi", max_length=1000, blank=True, null=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_invoices",
        verbose_name="Mas'ul",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.PROTECT,
        null=True,
        blank=True,
        related_name="created_invoices",
        verbose_name="Yaratgan",
    )

    class Meta:
        verbose_name = "Заяавка"
        verbose_name_plural = "Заяавки"
        permissions = [
            ("manage_invoice", "Call-center rahbari: barcha xodimlarning ishlari"),
        ]

    def __str__(self):
        return str(self.client_id)


class InvoiceTask(models.Model):
    """A reminder "call this client at <due_at>" for one person."""

    invoice = models.ForeignKey(Invoice, models.CASCADE, related_name="tasks")
    text = models.CharField(max_length=500)
    due_at = models.DateTimeField()
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.PROTECT, related_name="crm_tasks"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, related_name="+"
    )
    # set once the bot reminder went out (cleared again when the task is rescheduled)
    notified_at = models.DateTimeField(null=True, blank=True)
    # bumped on every reschedule: part of the once-key of the reminder
    remind_seq = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["assigned_to", "done_at", "due_at"]),
            models.Index(
                fields=["due_at"],
                condition=Q(done_at__isnull=True, notified_at__isnull=True),
                name="cc_task_due_pending",
            ),
        ]

    def __str__(self):
        return f"#{self.pk} {self.text}"


class InvoiceNote(models.Model):
    """Append-only history of a lead: notes, answer changes, reassignments."""

    invoice = models.ForeignKey(Invoice, models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.PROTECT, null=True, blank=True, related_name="+"
    )
    kind = models.CharField(max_length=20, choices=NoteKind.choices, default=NoteKind.note)
    text = models.TextField(blank=True)
    meta = models.JSONField(default=dict, blank=True)
    task = models.ForeignKey(InvoiceTask, models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["invoice", "created_at"])]

    def __str__(self):
        return f"#{self.pk} {self.kind}"
