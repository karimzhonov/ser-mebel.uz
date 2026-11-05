"""Owner's rule: the operator books a zamer from the lead (metering.add_metering) but
only VIEWS the zamer afterwards — no editing, deleting or status changes.

- «Operator» lavozim: keeps view_metering + add_metering, loses change_metering,
  delete_metering and change_status;
- the same rights are taken from the personal rights of the operators (people in the
  «Operator» lavozim) — the old per-person setup gave them «O'zgartirish» too — unless
  the person is also a zamerchi or a bosh menejer, or an administrator.

Matched case-insensitively like 0012. Safe to run twice; reverse does nothing."""

from django.contrib.auth.management import create_permissions
from django.db import migrations

EDIT = ("change_metering", "delete_metering", "change_status")
KEEP = ("view_metering", "add_metering")
# a person holding one of these steers zamers on purpose: their rights stay
STEERS = (("oauth", "user_metering"), ("metering", "manage_metering"))


def operators_view_meterings(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("oauth", "User")
    groups = [g for g in Group.objects.all() if g.name.strip().lower() == "operator"]
    if not groups:
        return
    config = apps.get_app_config("metering")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    meter = Permission.objects.filter(content_type__app_label="metering")
    edit = list(meter.filter(codename__in=EDIT))
    keep = list(meter.filter(codename__in=KEEP))
    for group in groups:
        group.permissions.remove(*edit)
        group.permissions.add(*keep)
    for user in User.objects.filter(groups__in=groups, is_superuser=False).distinct():
        steers = any(
            user.user_permissions.filter(content_type__app_label=a, codename=c).exists()
            or Permission.objects.filter(
                group__user=user, content_type__app_label=a, codename=c
            ).exists()
            for a, c in STEERS
        )
        if not steers:
            user.user_permissions.remove(*edit)


class Migration(migrations.Migration):
    dependencies = [
        ("oauth", "0013_managers_calculate_price"),
        ("metering", "0016_offer_stage2"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(operators_view_meterings, migrations.RunPython.noop)]
