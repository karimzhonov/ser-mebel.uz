from django.db import migrations


def forwards(apps, schema_editor):
    """A chiqim that named a site order becomes one allocation for that order."""
    Movement = apps.get_model("warehouse", "Movement")
    Allocation = apps.get_model("warehouse", "MovementAllocation")
    rows = []
    qs = Movement.objects.filter(kind="out", order__isnull=False, order__order_number__isnull=False)
    for m in qs.select_related("order", "order__client").iterator():
        client = getattr(m.order.client, "fio", "") if m.order.client_id else ""
        rows.append(
            Allocation(
                movement=m,
                order_ref=str(m.order.order_number),
                order=m.order,
                client=(client or "")[:255],
                quantity=m.quantity,
                total=m.total,
            )
        )
    Allocation.objects.bulk_create(rows, batch_size=500)


def backwards(apps, schema_editor):
    apps.get_model("warehouse", "MovementAllocation").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("warehouse", "0004_movementallocation")]
    operations = [migrations.RunPython(forwards, backwards)]
