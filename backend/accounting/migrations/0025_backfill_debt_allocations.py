from django.db import migrations
from django.db.models import Count


def backfill(apps, schema_editor):
    Debt = apps.get_model("accounting", "Debt")
    Allocation = apps.get_model("accounting", "DebtAllocation")
    Operation = apps.get_model("accounting", "Operation")
    # every debt, soft-deleted too: one allocation = the whole debt on its order
    for debt in Debt.objects.filter(allocations__isnull=True).iterator():
        if debt.currency == "USD" and debt.orig_amount is not None:
            amount = debt.orig_amount
        else:
            amount = debt.amount
        # an old row with a non-positive sum can't satisfy amount > 0 and must not stop
        # the deploy: it keeps showing its single order (the DTO's row without an id)
        if amount <= 0:
            continue
        alloc = Allocation.objects.create(
            debt=debt,
            order_id=debt.order_id,
            order_ref=debt.order_ref,
            amount=amount,
        )
        Operation.objects.filter(debt_id=debt.pk).update(debt_allocation=alloc)


def unbackfill(apps, schema_editor):
    Allocation = apps.get_model("accounting", "DebtAllocation")
    split = Allocation.objects.values("debt_id").order_by().annotate(n=Count("id")).filter(n__gt=1)
    if split.exists():
        raise RuntimeError(
            "Qarzlar bir nechta buyurtmaga bo'lingan - migratsiyani qaytarib bo'lmaydi."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0024_debtallocation"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
