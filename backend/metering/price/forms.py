import json

from django import forms
from djmoney.money import Money
from unfold.widgets import (
    AdminTextInputWidget,
    UnfoldAdminDecimalFieldWidget,
    UnfoldAdminSelectWidget,
)

from .models import Calculate, Inventory, InventoryInCalculate, InventoryType, ObjectType


class CalculateForm(forms.ModelForm):
    object_type_id = None

    count = forms.FloatField(widget=UnfoldAdminDecimalFieldWidget())

    class Meta:
        model = Calculate
        fields = ["name", "count"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        obj = ObjectType.objects.filter(pk=self.object_type_id).first()
        if obj:
            self.fields["count"].label = dict(obj.COUNT_NAMES)[obj.count_name]

        if self.instance.pk:
            for inv_in_calc in InventoryInCalculate.objects.filter(
                calculate=self.instance
            ).select_related("inventory", "inventory__type"):
                if inv_in_calc.inventory.type.type == InventoryType.TYPE_KV:
                    self.initial[f"inv_{inv_in_calc.inventory.type_id}"] = inv_in_calc.inventory_id
                elif inv_in_calc.inventory.type.type == InventoryType.TYPE_COUNT:
                    self.initial[f"inv_{inv_in_calc.inventory.type_id}"] = [
                        inv_in_calc.inventory_id,
                        inv_in_calc.count,
                        "",
                    ]

    def save(self, commit=True):
        self.instance.obj_id = self.object_type_id
        instance: Calculate = super().save(commit)
        amount = 0
        for key in self.cleaned_data.keys():
            value = self.cleaned_data[key]
            if key.startswith("inv_"):
                if type(value) == list:
                    inv, count, price = value
                    inv = Inventory.objects.filter(id=inv).first() if inv else None
                    count = float(count or 0)
                else:
                    if value and isinstance(value, str):
                        value = Inventory.objects.filter(id=value).first()
                    inv, count = value, instance.count
                if not inv:
                    continue
                inv_in_calc = InventoryInCalculate.objects.filter(
                    inventory__type=inv.type, calculate=instance
                ).first()
                inv_amount = count * float(inv.price.amount)
                if inv_in_calc:
                    InventoryInCalculate.objects.filter(
                        inventory_id=inv.id, calculate=instance
                    ).update(
                        price=Money(amount=inv_amount, currency=inv.price.currency), count=count
                    )
                else:
                    InventoryInCalculate.objects.create(
                        inventory_id=inv.id,
                        calculate=instance,
                        price=Money(amount=inv_amount, currency=inv.price.currency),
                        count=count,
                    )
                amount += inv_amount
        instance.amount = Money(amount, currency="USD")

        if commit:
            instance.save()
        return instance


class InventoryCountWidget(forms.MultiWidget):
    """Renders [inventory select, count, disabled price] for one InventoryType.

    Bound value shape is always a 3-item list: [inv_id, count, price] — this is
    exactly what CalculateForm.save() expects to unpack from cleaned_data for
    every ``inv_*`` key (see forms.CalculateForm.save()). Only one (inventory,
    count) pair is supported per InventoryType today.
    """

    template_name = "metering/price/inventory_list.html"

    def __init__(self, choices=[], attrs=None):
        attrs = attrs or {}
        widgets = [
            UnfoldAdminSelectWidget(choices=choices),
            UnfoldAdminDecimalFieldWidget(attrs={"placeholder": "Количество"}),
            AdminTextInputWidget(attrs={"disabled": True}),
        ]
        super().__init__(widgets, attrs)

    def decompress(self, value):
        """Normalize any stored value into the [inv_id, count, price] shape.

        ``value`` may already be a list (e.g. the [inventory_id, count, ''] initial
        set in CalculateForm.__init__), a JSON-encoded string (raw JSONField value),
        or empty/None (no selection yet) — MultiWidget only calls this when the
        value isn't already a list, but we defensively handle all three shapes.
        """
        if not value:
            return [None, None, ""]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                return [None, None, ""]
        if isinstance(value, (list, tuple)) and len(value) == 3:
            return list(value)
        return [None, None, ""]

    def value_from_datadict(self, data, files, name):
        """Read the [inv_id, count, price] triple back from POST data.

        Explicit override (rather than relying purely on MultiWidget's default)
        to make the [inv_id, count, price] contract CalculateForm.save() relies
        on obvious and to keep it stable if the widget's subwidgets ever change.
        """
        return [
            widget.value_from_datadict(data, files, f"{name}_{i}")
            for i, widget in enumerate(self.widgets)
        ]
