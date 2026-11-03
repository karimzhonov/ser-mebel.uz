from django.db import migrations

BATCH = 1000


def desc_to_notes(apps, schema_editor):
    """Every lead's old description becomes the first note of its history."""
    Invoice = apps.get_model("call_center", "Invoice")
    InvoiceNote = apps.get_model("call_center", "InvoiceNote")
    batch = []
    qs = (
        Invoice.objects.exclude(desc__isnull=True)
        .exclude(desc="")
        .only("id", "desc", "create_date")
    )
    for invoice in qs.iterator(chunk_size=BATCH):
        text = (invoice.desc or "").strip()
        if not text:
            continue
        batch.append(
            InvoiceNote(
                invoice_id=invoice.pk,
                author=None,
                kind="note",
                text=text,
                created_at=invoice.create_date,
                meta={"migrated": True},
            )
        )
        if len(batch) >= BATCH:
            InvoiceNote.objects.bulk_create(batch)
            batch = []
    if batch:
        InvoiceNote.objects.bulk_create(batch)


def drop_migrated_notes(apps, schema_editor):
    apps.get_model("call_center", "InvoiceNote").objects.filter(meta__migrated=True).delete()


class Migration(migrations.Migration):
    dependencies = [("call_center", "0005_crm")]

    operations = [migrations.RunPython(desc_to_notes, drop_migrated_notes)]
