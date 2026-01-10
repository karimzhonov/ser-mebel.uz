import json
from django import forms
from djmoney.money import Money
from unfold.widgets import UnfoldAdminSelectWidget, UnfoldAdminDecimalFieldWidget, AdminTextInputWidget
from .models import Calculate, InventoryInCalculate, Inventory, InventoryType


class CalculateForm(forms.ModelForm):
    object_type_id = None
    class Meta:
        model = Calculate
        fields = ['name', 'count']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            for inv_in_calc in InventoryInCalculate.objects.filter(calculate=self.instance).select_related('inventory', 'inventory__type'):
                if inv_in_calc.inventory.type.type == InventoryType.TYPE_KV:
                    self.initial[f'inv_{inv_in_calc.inventory.type_id}'] = inv_in_calc.inventory_id
                elif inv_in_calc.inventory.type.type == InventoryType.TYPE_COUNT:
                    self.initial[f'inv_{inv_in_calc.inventory.type_id}'] = [inv_in_calc.inventory_id, inv_in_calc.count, '']

    def save(self, commit = True):
        self.instance.obj_id = self.object_type_id
        instance: Calculate = super().save(commit)
        amount = 0
        for key in self.cleaned_data.keys():
            value = self.cleaned_data[key]
            if key.startswith('inv_'):
                if type(value) == list:
                    inv, count, price = value
                    inv = Inventory.objects.filter(id=inv).first() if inv else None
                    count = float(count or 0)
                else:
                    inv, count = value, instance.count
                if not inv: continue
                inv_in_calc = InventoryInCalculate.objects.filter(
                    inventory__type=inv.type, calculate=instance
                ).first()
                inv_amount = count * float(inv.price.amount)
                if inv_in_calc:
                    InventoryInCalculate.objects.filter(inventory_id=inv.id, calculate=instance).update(
                        price=Money(amount=inv_amount, currency=inv.price.currency),
                        count=count
                    )
                else:
                    InventoryInCalculate.objects.create(
                        inventory_id=inv.id,
                        calculate=instance,
                        price=Money(amount=inv_amount, currency=inv.price.currency),
                        count=count
                    )
                amount += inv_amount
        instance.amount = Money(amount, currency='USD')
        
        if commit: instance.save()
        return instance

class InventoryCountWidget(forms.MultiWidget):
    # template_name = 'metering/price/inventory_list.html'
    def __init__(self, choices=[], attrs=None):
        attrs = attrs or {}
        widgets = [
            UnfoldAdminSelectWidget(choices=choices),
            UnfoldAdminDecimalFieldWidget(attrs={'placeholder': 'Количество'}),
            AdminTextInputWidget(attrs={'disabled': True}),
        ]
        super().__init__(widgets, attrs)

    def decompress(self, value):
        value = json.loads(value)
        if not value:
            return []
        return value