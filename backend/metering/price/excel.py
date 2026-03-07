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
        
        for ic in InventoryInCalculate.objects.filter(calculate=calc).order_by('id'):
            if ic.inventory.type.type == InventoryType.TYPE_KV:
                ws.append([
                    ic.inventory.type.name,
                    ic.inventory.name,
                    str(ic.inventory.price),
                    '',
                    str(ic.price)
                ])

            elif ic.inventory.type.type == InventoryType.TYPE_COUNT:
                ws.append([
                    ic.inventory.type.name,
                    ic.inventory.name,
                    str(ic.inventory.price),
                    ic.count,
                    str(ic.price)
                ])

        ws.append([
            "Итого",
            "",
            "",
            "",
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

