import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("order", "0025_backfill_location"),
        ("payroll", "0002_sheetline_order_bonus"),
    ]

    operations = [
        migrations.CreateModel(
            name="SheetCost",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "order_ref",
                    models.CharField(db_index=True, max_length=32, verbose_name="Buyurtma ID"),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("line", "Varaqdagi ID"),
                            ("car", "Mashina puli (summaga qarab)"),
                        ],
                        default="line",
                        max_length=8,
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2, max_digits=16, verbose_name="Summa (so'm)"
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="order.order",
                    ),
                ),
                (
                    "sheet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="costs",
                        to="payroll.salarysheet",
                    ),
                ),
            ],
            options={
                "verbose_name": "Oylik xarajati (ID bo'yicha)",
                "verbose_name_plural": "Oylik xarajatlari (ID bo'yicha)",
                "ordering": ["sheet", "order_ref", "source"],
            },
        ),
        migrations.AddConstraint(
            model_name="sheetcost",
            constraint=models.UniqueConstraint(
                fields=("sheet", "order_ref", "source"), name="uniq_sheetcost_sheet_ref_source"
            ),
        ),
    ]
