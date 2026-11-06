"""A Price can be the approximate price of a lead (ariza): Price.invoice + the
«estimate» stage (a Price only — the Design stages are unchanged)."""

import django.db.models.deletion
from django.db import migrations, models

STAGES = [
    ("work", "Ishda"),
    ("review", "Mijozda — javob kutilmoqda"),
    ("approved", "Tasdiqlandi"),
    ("declined", "Rad etildi"),
    ("cancelled", "Bekor"),
    ("estimate", "Taxminiy narx"),
]


class Migration(migrations.Migration):
    dependencies = [
        ("price", "0025_offer_stage2_backfill"),
        ("call_center", "0008_zamer_stage1"),
    ]

    operations = [
        migrations.AddField(
            model_name="price",
            name="invoice",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="estimate",
                to="call_center.invoice",
                verbose_name="Ariza (taxminiy narx)",
            ),
        ),
        migrations.AddField(
            model_name="historicalprice",
            name="invoice",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="call_center.invoice",
                verbose_name="Ariza (taxminiy narx)",
            ),
        ),
        migrations.AlterField(
            model_name="price",
            name="stage",
            field=models.CharField(choices=STAGES, db_index=True, default="work", max_length=10),
        ),
        migrations.AlterField(
            model_name="historicalprice",
            name="stage",
            field=models.CharField(choices=STAGES, db_index=True, default="work", max_length=10),
        ),
    ]
