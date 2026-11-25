import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0025_backfill_debt_allocations"),
        ("payroll", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="sheetline",
            name="order_bonus",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sheet_lines",
                to="accounting.orderbonus",
            ),
        ),
        migrations.AddConstraint(
            model_name="sheetline",
            constraint=models.UniqueConstraint(
                fields=("order_bonus",), name="uniq_sheetline_order_bonus"
            ),
        ),
    ]
