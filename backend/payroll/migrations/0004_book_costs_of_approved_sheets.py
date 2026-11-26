"""Sheets approved before stage 2 shipped have no client costs: book them once from
their frozen snapshot (the same rule approval uses, payroll.services.cost_rows)."""

from django.db import migrations


def book(apps, schema_editor):
    from payroll.services import cost_rows

    SalarySheet = apps.get_model("payroll", "SalarySheet")
    SheetCost = apps.get_model("payroll", "SheetCost")
    Order = apps.get_model("order", "Order")
    for sh in SalarySheet.objects.filter(status="approved", snapshot__isnull=False):
        if SheetCost.objects.filter(sheet=sh).exists() or not isinstance(sh.snapshot, dict):
            continue
        rows = cost_rows(sh.snapshot)
        # an order deleted since the approval: keep the ID, drop the link
        alive = set(
            Order.objects.filter(id__in=[r["order_id"] for r in rows if r["order_id"]]).values_list(
                "id", flat=True
            )
        )
        for r in rows:
            if r["order_id"] not in alive:
                r["order_id"] = None
        SheetCost.objects.bulk_create(
            [
                SheetCost(
                    sheet=sh,
                    order_ref=r["order_ref"],
                    order_id=r["order_id"],
                    source=str(r["source"]),
                    amount=r["amount"],
                )
                for r in rows
            ]
        )


class Migration(migrations.Migration):
    dependencies = [("payroll", "0003_sheetcost")]

    operations = [migrations.RunPython(book, migrations.RunPython.noop)]
