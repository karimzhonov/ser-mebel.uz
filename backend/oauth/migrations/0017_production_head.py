"""New permission «Ishlab chiqarish rahbari» (oauth.user_production_head): sets/moves the
Rover deadline (panel + Telegram buttons) and gets the overdue reminders.

Creates the default lavozim «Ishlab chiqarish rahbari» only if no group with that name
exists (case-insensitive, whitespace-collapsed). Existing groups are never changed. Safe
to run twice."""

from django.contrib.auth.management import create_permissions
from django.db import migrations

NAME = "Ishlab chiqarish rahbari"
PERMS = (
    ("oauth", "user_production_head"),
    ("rover", "view_rover"),
    ("order", "view_order"),
)


def create_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    key = " ".join(NAME.split()).lower()
    if any(" ".join(g.name.split()).lower() == key for g in Group.objects.all()):
        return
    for label in ("oauth", "rover", "order"):
        config = apps.get_app_config(label)
        config.models_module = True
        create_permissions(config, apps=apps, verbosity=0)
    perms = [
        p
        for p in (
            Permission.objects.filter(content_type__app_label=a, codename=c).first()
            for a, c in PERMS
        )
        if p is not None
    ]
    group = Group.objects.create(name=NAME)
    group.permissions.add(*perms)


class Migration(migrations.Migration):
    dependencies = [
        ("oauth", "0016_rover_checker"),
        ("rover", "0007_rover_due_note"),
        ("order", "0025_backfill_location"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "permissions": [
                    ("user_call_center", "Call center"),
                    ("user_metering", "Metering"),
                    ("user_design", "Design"),
                    ("user_detailing", "Detailing"),
                    ("user_rover", "Rover"),
                    ("user_rover_checker", "Rover tekshiruvchi"),
                    ("user_production_head", "Ishlab chiqarish rahbari"),
                    ("user_painter", "Painter"),
                    ("user_assembly", "Assembly"),
                ]
            },
        ),
        migrations.RunPython(create_group, migrations.RunPython.noop),
    ]
