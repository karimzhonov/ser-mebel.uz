"""The «Rover» and «Molyar» lavozims lose every filer.* permission (the Fayllar section and
the generic folder browser): their workers see only the order's design folder, through the
scoped read access in `api.views.files` / `order.visibility.design_folder_access`.

Only groups whose whitespace-collapsed, case-insensitive name is «rover» or «molyar» are
touched. Idempotent. The default groups of 0012 never had filer.* permissions, so what is
removed here are only hand-added ones; they are not recorded anywhere, so the reverse is a
no-op (nothing is re-granted)."""

from django.db import migrations

NAMES = {"rover", "molyar"}


def remove_filer_perms(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    perms = list(Permission.objects.filter(content_type__app_label="filer"))
    if not perms:
        return
    for group in Group.objects.all():
        if " ".join(group.name.split()).lower() in NAMES:
            group.permissions.remove(*perms)


class Migration(migrations.Migration):
    dependencies = [
        ("oauth", "0019_role_perm_cleanup"),
        ("filer", "0017_image__transparent"),
    ]

    operations = [migrations.RunPython(remove_filer_perms, migrations.RunPython.noop)]
