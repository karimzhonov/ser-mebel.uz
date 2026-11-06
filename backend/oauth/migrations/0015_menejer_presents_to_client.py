"""Owner's rule: the plain «Menejer» is picked by the zamerchi to calculate the price and
show it to the client, so the «Menejer» lavozim must hold metering.present_to_client
(the «Menejer» flag) and the price rights.

0012 only created the default lavozims that did not exist yet, so a «Menejer» lavozim
made before it never got the flag; 0013 gave it the price rights but the flag only to
«Bosh menejer». Then the zamerchi's «Bajarildi» lists only the bosh menejer.

Only adds rights, never removes any. Matched case-insensitively. Safe to run twice."""

from django.contrib.auth.management import create_permissions
from django.db import migrations

FLAG = ("metering", "present_to_client")
SEE = (("metering", "view_metering"), ("price", "view_price"), ("design", "view_design"))


def menejer_presents(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    groups = [g for g in Group.objects.all() if " ".join(g.name.split()).lower() == "menejer"]
    if not groups:
        return
    for label in ("metering", "price", "design"):
        config = apps.get_app_config(label)
        config.models_module = True
        create_permissions(config, apps=apps, verbosity=0)
    perms = [
        p
        for p in (
            Permission.objects.filter(content_type__app_label=a, codename=c).first()
            for a, c in (FLAG, *SEE)
        )
        if p is not None
    ]
    for group in groups:
        group.permissions.add(*perms)


class Migration(migrations.Migration):
    dependencies = [
        ("oauth", "0014_operator_views_meterings"),
        ("metering", "0016_offer_stage2"),
    ]

    operations = [migrations.RunPython(menejer_presents, migrations.RunPython.noop)]
