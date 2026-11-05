"""Data step of 0024_offer_stage2, in its own transaction: Postgres refuses the deferred FK index
of the schema migration while the same transaction holds row updates («pending trigger
events»). Touches only rows never backfilled (assigned_at IS NULL)."""

from django.db import migrations, models


def backfill_stage(apps, schema_editor):
    """Finished rows count as approved. An unfinished row whose zamer already has an
    order or is sold out is approved too (the work is evidently over); one whose zamer
    was cancelled is cancelled; the rest are in work with no deadline (no reminders for
    old rows; the site shows «Muddat yo'q»). Invariant: done == stage in (review,
    approved)."""
    Price = apps.get_model("price", "Price")
    Order = apps.get_model("order", "Order")
    ordered = Order.objects.filter(metering__isnull=False).values("metering_id")
    Price.objects.filter(assigned_at__isnull=True, done=True).update(
        stage="approved",
    )
    open_rows = Price.objects.filter(assigned_at__isnull=True, done=False)
    open_rows.filter(
        models.Q(metering__status="sold_out") | models.Q(metering_id__in=ordered)
    ).update(stage="approved", done=True)
    Price.objects.filter(assigned_at__isnull=True, done=False, metering__status="dont_need").update(
        stage="cancelled"
    )
    Price.objects.filter(assigned_at__isnull=True, done=False).exclude(stage="cancelled").update(
        stage="work"
    )
    Price.objects.filter(assigned_at__isnull=True).update(assigned_at=models.F("created_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("price", "0024_offer_stage2"),
        ("order", "0025_backfill_location"),
    ]

    operations = [migrations.RunPython(backfill_stage, migrations.RunPython.noop)]
