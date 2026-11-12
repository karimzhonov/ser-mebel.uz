"""Narrow lavozim permissions (owner's rule), matched by whitespace-collapsed, case-insensitive
group name, only if the group / permission exists. Idempotent; reverse restores them.

- «Molyar» loses add/change/delete on Molyar turi (it keeps view): teams are managed by the
  production head and superusers.
- «Ishlab chiqarish rahbari» gains add/change/delete on Molyar turi.
- «Sborkachi» loses assembly.manager (assemblers see only their own jobs; managers are
  other lavozims)."""

from django.db import migrations

TYPE_PERMS = (
    ("painter", "add_paintertype"),
    ("painter", "change_paintertype"),
    ("painter", "delete_paintertype"),
)
MANAGER = (("assembly", "manager"),)

# (group name, permissions, True = remove on forward / add on reverse)
PLAN = (
    ("molyar", TYPE_PERMS, True),
    ("ishlab chiqarish rahbari", TYPE_PERMS, False),
    ("sborkachi", MANAGER, True),
)


def _groups(apps, name):
    Group = apps.get_model("auth", "Group")
    return [g for g in Group.objects.all() if " ".join(g.name.split()).lower() == name]


def _perms(apps, pairs):
    Permission = apps.get_model("auth", "Permission")
    found = (
        Permission.objects.filter(content_type__app_label=a, codename=c).first() for a, c in pairs
    )
    return [p for p in found if p is not None]


def _apply(apps, reverse):
    for name, pairs, removes in PLAN:
        perms = _perms(apps, pairs)
        for group in _groups(apps, name):
            if removes != reverse:
                group.permissions.remove(*perms)
            else:
                group.permissions.add(*perms)


def forward(apps, schema_editor):
    _apply(apps, reverse=False)


def backward(apps, schema_editor):
    _apply(apps, reverse=True)


class Migration(migrations.Migration):
    dependencies = [
        ("oauth", "0018_rover_molyar_no_order_view"),
        ("order", "0025_backfill_location"),
        ("painter", "0011_paintertype_outsource"),
        ("assembly", "0014_assembly_confirm"),
    ]

    operations = [migrations.RunPython(forward, backward)]
