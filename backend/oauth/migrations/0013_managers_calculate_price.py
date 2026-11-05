"""Owner's rule: the price is calculated by the managers, there is no «Narxchi» any more.

- «Menejer» and «Bosh menejer» get the price section (the rights «Narxchi» had), so the
  managers can be picked to calculate the price and can work it on the site;
- «Bosh menejer» also gets metering.present_to_client, so the measurer can pick them as
  the manager of a zamer (they already could record the client's answer);
- an empty «Narxchi» lavozim is deleted. One with people in it is left alone: the owner
  moves them on Xodimlar → Lavozimlar (the merge tool suggests «Menejer»).

Only adds rights, never removes any. Safe to run twice."""

from django.contrib.auth.management import create_permissions
from django.db import migrations

# a snapshot of the «Narxchi» price rights from 0012 (not imported: it must not change)
PRICE_PERMS = [
    "price.add_calcaccessory",
    "price.add_calculate",
    "price.add_inventoryincalculate",
    "price.add_price",
    "price.add_priceversion",
    "price.add_room",
    "price.add_roomimage",
    "price.change_calcaccessory",
    "price.change_calculate",
    "price.change_inventoryincalculate",
    "price.change_price",
    "price.change_priceversion",
    "price.change_room",
    "price.change_roomimage",
    "price.delete_calcaccessory",
    "price.delete_calculate",
    "price.delete_inventoryincalculate",
    "price.delete_price",
    "price.delete_priceversion",
    "price.delete_room",
    "price.delete_roomimage",
    "price.view_calcaccessory",
    "price.view_calculate",
    "price.view_inventory",
    "price.view_inventoryincalculate",
    "price.view_inventorytype",
    "price.view_objecttype",
    "price.view_price",
    "price.view_priceversion",
    "price.view_room",
    "price.view_roomimage",
    "price.view_roomtype",
]
LOW_TARGETS = ("menejer", "bosh menejer")  # matched like 0012: case-insensitively


def give_managers_the_price(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    groups = [g for g in Group.objects.all() if g.name.strip().lower() in LOW_TARGETS]
    if groups:
        for label in ("price", "metering"):
            config = apps.get_app_config(label)
            config.models_module = True
            create_permissions(config, apps=apps, verbosity=0)
        perms = [
            pk
            for pk, app, code in Permission.objects.filter(
                content_type__app_label="price"
            ).values_list("pk", "content_type__app_label", "codename")
            if f"{app}.{code}" in PRICE_PERMS
        ]
        for group in groups:
            group.permissions.add(*perms)
        present = Permission.objects.filter(
            content_type__app_label="metering", codename="present_to_client"
        ).first()
        if present is not None:
            for group in groups:
                if group.name.strip().lower() == "bosh menejer":
                    group.permissions.add(present)
    for group in Group.objects.filter(name__iexact="Narxchi"):
        if not group.user_set.exists():
            group.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("oauth", "0012_default_role_groups"),
    ]

    operations = [migrations.RunPython(give_managers_the_price, migrations.RunPython.noop)]
