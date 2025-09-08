from django import forms
from djmoney.money import Money
from unfold.widgets import UnfoldAdminTextInputWidget, UnfoldAdminMoneyWidget
from .models import Calculate, InventoryType, InventoryInCalculate, Inventory
from .widgets import InventoryArrayWidget


class CalculateForm(forms.ModelForm):
    data = forms.JSONField(
        label='Список',
        widget=InventoryArrayWidget()
    )

    amount = forms.CharField(
        label='Сумма',
        widget=UnfoldAdminTextInputWidget(
            attrs={
                'disabled': True,
                'style': 'background-color: oklch(88.5% .062 18.334);!important'
            }
        )
    )

    object_type_id = None

    class Meta:
        model = Calculate
        fields = ['name', 'data', 'amount']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.initial['data'] = []
        inv_types = InventoryType.objects.all()
        if self.object_type_id:
            inv_types = inv_types.filter(obj_id=self.object_type_id)
        for inv_type in inv_types:
            count = None
            inventory = None
            price = ''
            if self.instance.pk:
                inv_calc = InventoryInCalculate.objects.filter(calculate=self.instance, inventory__type=inv_type).first()
                if inv_calc:
                    count = inv_calc.count
                    inventory = inv_calc.inventory_id
                    price = str(inv_calc.price or '')

            self.initial['data'].append([inv_type.name, inventory, count, price])

    def save(self, commit = True):
        instance: Calculate = super().save(True)
        amount = 0
        
        for data in self.cleaned_data['data']:
            name, inventory_id, count, price = data
            if count and inventory_id: 
                inventory_price = getattr(Inventory.objects.filter(id=inventory_id).first(), 'converted_price', Money(0, 'USD'))
                amount += int(count) * inventory_price
                InventoryInCalculate.objects.update_or_create(
                    calculate=instance,
                    inventory_id=inventory_id,
                    defaults={
                        "count": count,
                        "price": Money(amount=int(count) * inventory_price, currency='USD')
                    }
                )
        instance.amount = Money(amount=amount, currency='USD')
        if commit:
            instance.save()
        return instance
