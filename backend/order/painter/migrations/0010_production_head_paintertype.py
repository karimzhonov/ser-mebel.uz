"""The default lavozim «Ishlab chiqarish rahbari» gets «Ko'rish» on Molyar turi: it picks
the team (painter type) after the rover and the site needs the type list. Additive and
idempotent: only that group, only if it exists; nothing else is touched."""

from django.contrib.auth.management import create_permissions
from django.db import migrations

NAME = "Ishlab chiqarish rahbari"


def add_view_paintertype(apps, schema_editor):
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
        content_type__app_label="painter", codename="view_paintertype"
    ).first()
    if perm is None:
        return
    for group in groups:
        group.permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [("painter", "0009_production_head_view_painter")]

    operations = [migrations.RunPython(add_view_paintertype, migrations.RunPython.noop)]
