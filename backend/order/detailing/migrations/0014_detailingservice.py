import django.db.models.deletion
from django.db import migrations, models

# One detailing may go to several services at once (half Timber, half Eman). The single
# place/note added in 0013 moves into DetailingService rows (dropped in 0015: a separate
# migration, so Postgres doesn't ALTER the table with the new FK rows' triggers pending).


def forward(apps, schema_editor):
    Detailing = apps.get_model("detailing", "Detailing")
    DetailingService = apps.get_model("detailing", "DetailingService")
    rows = Detailing.objects.filter(service_out_at__isnull=False).exclude(service_place="")
    DetailingService.objects.bulk_create(
        [
            DetailingService(
                detailing_id=d.pk, place=d.service_place, out_at=d.service_out_at, note=d.service_note
            )
            for d in rows
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("detailing", "0013_detailing_service_place_note"),
    ]

    operations = [
        migrations.CreateModel(
            name="DetailingService",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "place",
                    models.CharField(
                        choices=[("timber", "Timber"), ("eman", "Eman"), ("other", "Boshqa")],
                        max_length=16,
                        verbose_name="Услуга",
                    ),
                ),
                ("out_at", models.DateTimeField(db_index=True, verbose_name="Выход из услуги")),
                ("note", models.TextField(blank=True, default="", verbose_name="Комментарий")),
                (
                    "detailing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="services",
                        to="detailing.detailing",
                        verbose_name="Деталировка",
                    ),
                ),
            ],
            options={
                "verbose_name": "Услуга деталировки",
                "verbose_name_plural": "Услуги деталировки",
                "ordering": ["out_at", "pk"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("detailing", "place"), name="detailing_service_unique_place"
                    )
                ],
            },
        ),
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
