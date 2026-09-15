from openpyxl import Workbook
from django.http import HttpResponse
from .models import Price, Calculate, InventoryInCalculate, InventoryType


def download_inlines_excel(modeladmin, request, object_id):
    price = Price.objects.get(pk=object_id)
    queryset = Calculate.objects.filter(price_id=object_id)
    wb = Workbook()
    ws = wb.active
    ws.title = str(price.metering)

    for calc in queryset:
        # Заголовки
        ws.append([
            calc.name,
        ])
        ws.append([
            "Тип",
            calc.obj.name
        ])
        ws.append([
            calc.obj.count_name,
            calc.count
        ])
        
        # Per-inventory prices (unit price and line total) are deliberately left out
        # of the накладной — only the per-calculation "Итого" carries money.
        inventories = InventoryInCalculate.objects.filter(
            calculate=calc
        ).select_related('inventory__type').order_by('id')
        for ic in inventories:
            if ic.inventory.type.type == InventoryType.TYPE_KV:
                ws.append([
                    ic.inventory.type.name,
                    ic.inventory.name,
                ])

            elif ic.inventory.type.type == InventoryType.TYPE_COUNT:
                ws.append([
                    ic.inventory.type.name,
                    ic.inventory.name,
                    ic.count
                ])

        ws.append([
            "Итого",
            str(calc.amount)
        ])

        ws.append([""])
        ws.append([""])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{price.metering}.xlsx"'

    wb.save(response)
    return response

download_inlines_excel.short_description = "📥 Скачать накладной (Excel)"

