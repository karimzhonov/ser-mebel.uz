from django.db import migrations

# Until «Keyingi bosqich» was blocked for Yaratildi -> Detalirovka (commit 8e24c24),
# it moved the order's status without creating its Detailing row, so such orders
# never showed up on the Detalirovka page. Give each of them its row (no deadline,
# not done) and the same files folder the post_save signal would have made.
# Assembly is NOT created here: its signal notifies the assembly staff; it appears
# as soon as the detailing is saved from the Detalirovka page.


def backfill(apps, schema_editor):
    from filer.models import Folder  # real MPTT model, so the folder tree stays valid

    Order = apps.get_model("order", "Order")
    Detailing = apps.get_model("detailing", "Detailing")

    orphans = Order.objects.filter(status="detailing", detailing__isnull=True)
    for order in orphans:
        folder_id = None
        parent = Folder.objects.filter(pk=order.folder_id).first() if order.folder_id else None
        if parent is not None:
            folder_id = Folder.objects.create(
                name="Деталировка / Производстьво", parent=parent, owner=parent.owner
            ).pk
        Detailing.objects.create(order=order, folder_id=folder_id)


class Migration(migrations.Migration):

    dependencies = [
        ("detailing", "0010_detailing_due_at"),
        ("order", "0025_backfill_location"),
        ("filer", "__first__"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
