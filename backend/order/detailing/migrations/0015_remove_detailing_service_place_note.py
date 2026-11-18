from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("detailing", "0014_detailingservice"),
    ]

    operations = [
        migrations.RemoveField(model_name="detailing", name="service_place"),
        migrations.RemoveField(model_name="historicaldetailing", name="service_place"),
        migrations.RemoveField(model_name="detailing", name="service_note"),
        migrations.RemoveField(model_name="historicaldetailing", name="service_note"),
    ]
