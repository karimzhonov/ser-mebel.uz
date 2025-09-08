import json
from django import forms
from djmoney.money import Money
from unfold.contrib.forms.widgets import ArrayWidget
from unfold.widgets import AdminTextInputWidget, UnfoldAdminTextInputWidget, UnfoldAdminIntegerFieldWidget, UnfoldAdminSelectWidget
from .models import Inventory, InventoryType


class InventoryCountWidget(forms.MultiWidget):
    def __init__(self, attrs=None):
        choices = (attrs or {}).get('choices', [])
        widgets = [
            AdminTextInputWidget(attrs={'style': 'margin-right: 10px; max-width: 200px', 'disabled': True}),
            UnfoldAdminSelectWidget(attrs={'placeholder': 'Выберите'}, choices=choices),
            UnfoldAdminIntegerFieldWidget(attrs={'placeholder': 'Количество', 'style': 'max-width: 200px; margin-left: 10px;'}),
            UnfoldAdminTextInputWidget(attrs={'disabled': True, 'style': 'margin-left: 10px; max-width: 200px; background-color: oklch(88.5% .062 18.334);!important'}),
        ]
        super().__init__(widgets, attrs)

    def decompress(self, value):
        value = json.loads(value) if isinstance(value, str) and value else None
        if value:
            name, inventory, count, price = value
            if not name:
                id = getattr(Inventory.objects.filter(id=inventory).first(), 'type_id', None)
            else:
                id = getattr(InventoryType.objects.filter(name=name).first(), 'id', None)
            if id:
                self.widgets[1].choices = ((None, ''), *Inventory.objects.filter(type_id=id).values_list('id', 'name'))
            return [name, inventory, count, price]
        return [None, None, None, None]


class InventoryArrayWidget(ArrayWidget):
    template_name = 'metering/price/inventory_list.html'
    widget_class = InventoryCountWidget

    def value_from_datadict(self, data, files, name):
        keys = list(sorted(filter(lambda k: k.startswith(name), data.keys())))
        inventory_dict = {}
        values = []
        for inventory_id, count in zip(*[data.getlist(k) for k in keys]):
            if not inventory_id or not count: continue
            type_id = str(getattr(Inventory.objects.filter(id=inventory_id).first(), 'type_id', None))
            if type_id:
                inventory_dict[type_id] = {"inventory": inventory_id, "count": count}

        for inv_type in InventoryType.objects.all():
            inventory = inventory_dict.get(str(inv_type.id), {})
            inv = Inventory.objects.filter(id=inventory.get('inventory', None)).first()
            price = Money(0, 'USD') if not inventory.get('count', None) else Money(amount=inv.converted_price * int(inventory.get('count', 0)), currency='USD')
            values.append([inv_type.name, inventory.get('inventory', None), inventory.get('count', None), str(price)])
        return json.dumps(values)
    
    def get_context(self, name, value, attrs):
        value = json.loads(value)
        return super().get_context(name, [json.dumps(v, ensure_ascii=False) for v in value], attrs)
