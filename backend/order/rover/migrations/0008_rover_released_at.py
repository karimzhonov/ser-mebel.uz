from django.db import migrations, models
from django.db.models import F

# Every rover that already exists was announced on creation (the old rule), so it is
# already in the rover section: released at its creation time.


def backfill(apps, schema_editor):
    Rover = apps.get_model("rover", "Rover")
    Rover.objects.filter(released_at__isnull=True).update(released_at=F("created_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("rover", "0007_rover_due_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="rover",
            name="released_at",
            field=models.DateTimeField(
                blank=True, db_index=True, null=True, verbose_name="Roverga o'tdi"
            ),
        ),
        migrations.AddField(
            model_name="historicalrover",
            name="released_at",
            field=models.DateTimeField(
                blank=True, db_index=True, null=True, verbose_name="Roverga o'tdi"
            ),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
