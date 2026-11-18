from django.db import migrations, models

PLACE = dict(
    blank=True,
    choices=[("timber", "Timber"), ("eman", "Eman"), ("other", "Boshqa")],
    default="",
    max_length=16,
    verbose_name="Услуга (где)",
)
NOTE = dict(blank=True, default="", verbose_name="Комментарий к услуге")


class Migration(migrations.Migration):

    dependencies = [
        ("detailing", "0012_detailing_service_out_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="detailing", name="service_place", field=models.CharField(**PLACE)
        ),
        migrations.AddField(
            model_name="historicaldetailing",
            name="service_place",
            field=models.CharField(**PLACE),
        ),
        migrations.AddField(
            model_name="detailing", name="service_note", field=models.TextField(**NOTE)
        ),
        migrations.AddField(
            model_name="historicaldetailing",
            name="service_note",
            field=models.TextField(**NOTE),
        ),
    ]
