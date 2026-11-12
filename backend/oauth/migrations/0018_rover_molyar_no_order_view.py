"""The «Rover» and «Molyar» lavozims lose order.view_order (and order.view_order_price):
their workers get a reduced order on their own pages (order.visibility) and must not open
the full order through the Orders section.

Only groups whose whitespace-collapsed, case-insensitive name is «rover» or «molyar» are
touched, only those two permissions, only if they exist. Idempotent; reverse adds order.view_order
back to the same groups."""

from django.db import migrations

NAMES = {"rover", "molyar"}
PERMS = (("order", "view_order"), ("order", "view_order_price"))


def _groups(apps):
    Group = apps.get_model("auth", "Group")
    return [g for g in Group.objects.all() if " ".join(g.name.split()).lower() in NAMES]


def _perms(apps):
    Permission = apps.get_model("auth", "Permission")
    return [
        p
        for p in (
            Permission.objects.filter(content_type__app_label=a, codename=c).first()
            for a, c in PERMS
        )
        if p is not None
    ]


def remove_perms(apps, schema_editor):
    perms = _perms(apps)
    for group in _groups(apps):
        group.permissions.remove(*perms)


def restore_perms(apps, schema_editor):
    # 0012 only ever gave view_order (never view_order_price)
    perms = [p for p in _perms(apps) if p.codename == "view_order"]
    for group in _groups(apps):
        group.permissions.add(*perms)


class Migration(migrations.Migration):
    dependencies = [
        ("oauth", "0017_production_head"),
        ("order", "0025_backfill_location"),
    ]

    operations = [migrations.RunPython(remove_perms, restore_perms)]
