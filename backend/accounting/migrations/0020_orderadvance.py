import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0019_operationchange"),
        ("order", "0025_backfill_location"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrderAdvance",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(decimal_places=2, max_digits=16, verbose_name="Avans"),
                ),
                (
                    "currency",
                    models.CharField(default="UZS", max_length=3, verbose_name="Valyuta"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "⏳ Tasdiq kutilmoqda"),
                            ("accepted", "✅ Qabul qilindi"),
                            ("rejected", "❌ Pul kelmadi"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("answered_at", models.DateTimeField(blank=True, null=True)),
                ("got_text", models.CharField(blank=True, default="", max_length=64)),
                (
                    "answered_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="oauth.telegrammember",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="oauth.user",
                    ),
                ),
                (
                    "operation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="accounting.operation",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="advances",
                        to="order.order",
                    ),
                ),
            ],
            options={
                "verbose_name": "Buyurtma avansi",
                "verbose_name_plural": "Buyurtma avanslari",
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
