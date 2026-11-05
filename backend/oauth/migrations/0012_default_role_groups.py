"""Default roles (groups): Operator, O'lcham oluvchi, Dizayner, Narxchi, Menejer, Bosh
menejer, Konstruktor, Molyar, Sborkachi, Rover. Each group mirrors the per-section setup
the staff had before (section levels + the yes/no task flags); the owner switches the
toggles later on the Users page.

Only creates a group whose exact name does not exist yet: existing groups are never
changed and nobody is moved into a group. Safe to run twice."""

from django.contrib.auth.management import create_permissions
from django.db import migrations

# a snapshot of oauth.access sections at the time of writing (not imported: the
# sections may change later, this migration must not)
DEFAULT_GROUPS = {
    "Operator": [
        "call_center.add_invoice",
        "call_center.change_invoice",
        "call_center.delete_invoice",
        "call_center.view_invoice",
        "client.add_client",
        "client.change_client",
        "client.delete_client",
        "client.view_client",
        "discussion.add_discussionmessage",
        "discussion.change_discussionmessage",
        "discussion.delete_discussionmessage",
        "discussion.view_discussionmessage",
        "filer.view_file",
        "filer.view_folder",
        "filer.view_image",
        "metering.add_metering",
        "metering.change_metering",
        "metering.change_status",
        "metering.delete_metering",
        "metering.view_metering",
        "oauth.user_call_center",
    ],
    "O'lcham oluvchi": [
        "discussion.add_discussionmessage",
        "discussion.change_discussionmessage",
        "discussion.delete_discussionmessage",
        "discussion.view_discussionmessage",
        "filer.add_file",
        "filer.add_folder",
        "filer.add_image",
        "filer.change_file",
        "filer.change_folder",
        "filer.change_image",
        "filer.delete_file",
        "filer.delete_folder",
        "filer.delete_image",
        "filer.view_file",
        "filer.view_folder",
        "filer.view_image",
        "metering.add_metering",
        "metering.change_metering",
        "metering.change_status",
        "metering.delete_metering",
        "metering.view_metering",
        "oauth.user_metering",
        "price.view_inventory",
        "price.view_inventorytype",
        "price.view_objecttype",
        "price.view_roomtype",
    ],
    "Dizayner": [
        "design.add_design",
        "design.add_designtype",
        "design.change_design",
        "design.change_designtype",
        "design.delete_design",
        "design.delete_designtype",
        "design.view_design",
        "design.view_designtype",
        "discussion.add_discussionmessage",
        "discussion.change_discussionmessage",
        "discussion.delete_discussionmessage",
        "discussion.view_discussionmessage",
        "filer.add_file",
        "filer.add_folder",
        "filer.add_image",
        "filer.change_file",
        "filer.change_folder",
        "filer.change_image",
        "filer.delete_file",
        "filer.delete_folder",
        "filer.delete_image",
        "filer.view_file",
        "filer.view_folder",
        "filer.view_image",
        "metering.view_metering",
        "oauth.user_design",
    ],
    "Narxchi": [
        "discussion.add_discussionmessage",
        "discussion.change_discussionmessage",
        "discussion.delete_discussionmessage",
        "discussion.view_discussionmessage",
        "filer.add_file",
        "filer.add_folder",
        "filer.add_image",
        "filer.change_file",
        "filer.change_folder",
        "filer.change_image",
        "filer.delete_file",
        "filer.delete_folder",
        "filer.delete_image",
        "filer.view_file",
        "filer.view_folder",
        "filer.view_image",
        "metering.view_metering",
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
    ],
    "Menejer": [
        "call_center.view_invoice",
        "client.view_client",
        "design.view_design",
        "design.view_designtype",
        "discussion.add_discussionmessage",
        "discussion.change_discussionmessage",
        "discussion.delete_discussionmessage",
        "discussion.view_discussionmessage",
        "filer.view_file",
        "filer.view_folder",
        "filer.view_image",
        "metering.present_to_client",
        "metering.view_metering",
        "order.add_order",
        "order.change_order",
        "order.change_status_order",
        "order.delete_order",
        "order.reverse_status_order",
        "order.view_order",
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
    ],
    "Bosh menejer": [
        "call_center.manage_invoice",
        "call_center.view_invoice",
        "client.view_client",
        "design.view_design",
        "design.view_designtype",
        "discussion.add_discussionmessage",
        "discussion.change_discussionmessage",
        "discussion.delete_discussionmessage",
        "discussion.view_discussionmessage",
        "filer.view_file",
        "filer.view_folder",
        "filer.view_image",
        "metering.manage_metering",
        "metering.view_metering",
        "order.add_order",
        "order.change_order",
        "order.change_status_order",
        "order.delete_order",
        "order.reverse_status_order",
        "order.view_order",
        "order.view_order_price",
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
    ],
    "Konstruktor": [
        "detailing.add_detailing",
        "detailing.change_detailing",
        "detailing.delete_detailing",
        "detailing.view_detailing",
        "oauth.user_detailing",
        "order.view_order",
    ],
    "Molyar": [
        "oauth.user_painter",
        "order.view_order",
        "painter.add_painter",
        "painter.add_paintertype",
        "painter.change_painter",
        "painter.change_paintertype",
        "painter.delete_painter",
        "painter.delete_paintertype",
        "painter.view_painter",
        "painter.view_paintertype",
    ],
    "Sborkachi": [
        "assembly.add_assembly",
        "assembly.change_assembly",
        "assembly.delete_assembly",
        "assembly.manager",
        "assembly.view_assembly",
        "oauth.user_assembly",
        "order.view_order",
    ],
    "Rover": [
        "oauth.user_rover",
        "order.view_order",
        "rover.add_rover",
        "rover.change_rover",
        "rover.delete_rover",
        "rover.view_rover",
    ],
}

APPS = {
    "call_center",
    "client",
    "discussion",
    "filer",
    "metering",
    "design",
    "price",
    "order",
    "detailing",
    "rover",
    "painter",
    "assembly",
    "oauth",
}


def create_default_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    todo = [
        name
        for name in DEFAULT_GROUPS
        if not Group.objects.filter(name__iexact=name.strip()).exists()
    ]
    if not todo:
        return
    # permissions are normally created after migrate: a fresh database has none yet
    for label in APPS:
        config = apps.get_app_config(label)
        config.models_module = True
        create_permissions(config, apps=apps, verbosity=0)
    existing = {
        f"{app}.{code}": pk
        for pk, app, code in Permission.objects.values_list(
            "pk", "content_type__app_label", "codename"
        )
    }
    for name in todo:
        group = Group.objects.create(name=name)
        group.permissions.set([existing[p] for p in DEFAULT_GROUPS[name] if p in existing])


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("oauth", "0011_telegrammember_wallet_mode"),
        ("call_center", "0008_zamer_stage1"),
        ("client", "0003_client_created_at"),
        ("discussion", "0001_initial"),
        ("filer", "0017_image__transparent"),
        ("metering", "0016_offer_stage2"),
        ("design", "0010_offer_stage2_backfill"),
        ("price", "0025_offer_stage2_backfill"),
        ("order", "0025_backfill_location"),
        ("detailing", "0009_remove_detailing_pointer_type_and_more"),
        ("rover", "0005_alter_historicalrover_options_alter_rover_options"),
        ("painter", "0007_alter_historicalpainter_options_and_more"),
        ("assembly", "0011_alter_assembly_user_alter_historicalassembly_user"),
    ]

    operations = [migrations.RunPython(create_default_groups, migrations.RunPython.noop)]
