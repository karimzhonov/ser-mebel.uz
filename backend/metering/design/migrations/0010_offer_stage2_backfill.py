"""Data step of 0009_offer_stage2, in its own transaction: Postgres refuses the deferred FK index
of the schema migration while the same transaction holds row updates («pending trigger
events»). Touches only rows never backfilled (assigned_at IS NULL)."""

from django.db import migrations, models


def backfill_stage(apps, schema_editor):
    """Finished rows count as approved. An unfinished row whose zamer already has an
    order or is sold out is approved too (the work is evidently over); one whose zamer
    was cancelled is cancelled; the rest are in work with no deadline (no reminders for
    old rows; the site shows «Muddat yo'q»). Invariant: done == stage in (review,
    approved)."""
    Design = apps.get_model("design", "Design")
    Order = apps.get_model("order", "Order")
    ordered = Order.objects.filter(metering__isnull=False).values("metering_id")
    Design.objects.filter(assigned_at__isnull=True, done=True).update(
        stage="approved",
        confirm=True,
    )
    open_rows = Design.objects.filter(assigned_at__isnull=True, done=False)
    open_rows.filter(
        models.Q(metering__status="sold_out") | models.Q(metering_id__in=ordered)
    ).update(stage="approved", done=True, confirm=True)
    Design.objects.filter(
        assigned_at__isnull=True, done=False, metering__status="dont_need"
    ).update(stage="cancelled")
    Design.objects.filter(assigned_at__isnull=True, done=False).exclude(stage="cancelled").update(
        stage="work"
    )
    Design.objects.filter(assigned_at__isnull=True).update(assigned_at=models.F("created_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("design", "0009_offer_stage2"),
        ("order", "0025_backfill_location"),
    ]

    operations = [migrations.RunPython(backfill_stage, migrations.RunPython.noop)]
