"""One PainterPart per existing Painter that has a team (the whole job to that team).

The backfill does not touch the Painter rows; the service keeps `Painter.type` equal to
the single part's team (NULL when split), so the reverse (delete the parts) restores a
consistent pre-split state for unsplit jobs. Idempotent: a job that already has parts is skipped."""

from decimal import Decimal

from django.db import migrations

CHUNK = 500


def _amount(value):
    return getattr(value, "amount", value)


def backfill(apps, schema_editor):
    Painter = apps.get_model("painter", "Painter")
    PainterPart = apps.get_model("painter", "PainterPart")
    batch = []
    jobs = (
        Painter.objects.filter(type__isnull=False, parts__isnull=True)
        .select_related("type")
        .order_by("pk")
    )
    for p in jobs.iterator(chunk_size=CHUNK):
        # historical models give a bare Decimal, the real ones a Money (tests): take the number
        amount, currency = _amount(p.price), p.price_currency
        if amount is None:
            amount = _amount(p.type.price) * Decimal(str(p.square))
            currency = p.type.price_currency
        batch.append(
            PainterPart(
                painter_id=p.pk,
                type_id=p.type_id,
                square=p.square,
                price=amount,
                price_currency=currency,
                started_at=p.started_at,
                due_date=p.due_date,
                due_auto=p.due_auto,
                due_set_by_id=p.due_set_by_id,
                due_set_at=p.due_set_at,
                note=p.note,
                rev=p.rev,
                done=p.done,
                done_at=p.done_at,
                done_by_id=p.done_by_id,
            )
        )
        if len(batch) >= CHUNK:
            PainterPart.objects.bulk_create(batch)
            batch = []
    if batch:
        PainterPart.objects.bulk_create(batch)


def unbackfill(apps, schema_editor):
    apps.get_model("painter", "PainterPart").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("painter", "0012_painterpart")]
    operations = [migrations.RunPython(backfill, unbackfill)]
