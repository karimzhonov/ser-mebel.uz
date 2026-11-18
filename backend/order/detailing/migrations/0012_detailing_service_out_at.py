from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("detailing", "0011_backfill_missing_detailing"),
    ]

    operations = [
        migrations.AddField(
            model_name="detailing",
            name="service_out_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Выход из услуги"),
        ),
        migrations.AddField(
            model_name="historicaldetailing",
            name="service_out_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Выход из услуги"),
        ),
    ]
