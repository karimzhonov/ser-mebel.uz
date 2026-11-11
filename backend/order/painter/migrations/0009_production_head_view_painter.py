"""The default lavozim «Ishlab chiqarish rahbari» gets «Ko'rish» on Molyar (it sets the
Molyar deadline and must open the list). Additive and idempotent: only that group, only if
it exists; nothing else is touched."""

from django.contrib.auth.management import create_permissions
from django.db import migrations

NAME = "Ishlab chiqarish rahbari"


def add_view_painter(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    key = " ".join(NAME.split()).lower()
    groups = [g for g in Group.objects.all() if " ".join(g.name.split()).lower() == key]
    if not groups:
        return
    config = apps.get_app_config("painter")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    perm = Permission.objects.filter(
        content_type__app_label="painter", codename="view_painter"
    ).first()
    if perm is None:
        return
    for group in groups:
        group.permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [
        ("oauth", "0017_production_head"),
        ("painter", "0008_painter_due_note"),
    ]

    operations = [migrations.RunPython(add_view_painter, migrations.RunPython.noop)]
