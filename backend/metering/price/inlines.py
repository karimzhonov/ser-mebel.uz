from django import forms
from unfold.admin import TabularInline, StackedInline
from unfold.widgets import UnfoldAdminSelectWidget
from .models import Inventory, Calculate, InventoryType
from .forms import InventoryCountWidget, CalculateForm


class InventoryInline(TabularInline):
    model = Inventory
    extra = 0
    tab = True


class CalculateInline(StackedInline):
    model = Calculate
    tab = True
    extra = 0
    readonly_fields = ['amount']
    object_type_id = None

    def get_queryset(self, request):
        return super().get_queryset(request).filter(obj_id=self.object_type_id)
    
    def get_formset(self, request, obj = None, **kwargs):
        extra_fields = {
            "object_type_id": self.object_type_id
        }
        for inv_type in InventoryType.objects.filter(obj_id=self.object_type_id).order_by('id'):
            if inv_type.type == InventoryType.TYPE_KV:
                extra_fields[f'inv_{inv_type.id}'] = forms.ModelChoiceField(
                    label=inv_type.name,
                    required=False,
                    queryset=Inventory.objects.filter(type=inv_type),
                    widget=UnfoldAdminSelectWidget()
                )
            elif inv_type.type == InventoryType.TYPE_COUNT:
                extra_fields[f'inv_{inv_type.id}'] = forms.JSONField(
                    label=inv_type.name,
                    required=False,
                    widget=InventoryCountWidget(choices=[
                        (None, '---------'), 
                        *[
                            (inv.id, f'{inv.name} - {inv.price}') for inv in Inventory.objects.filter(type=inv_type)
                        ]
                    ])
                )
        
        kwargs.update(form=type('CalculateFullForm', (CalculateForm,), extra_fields))
        return super().get_formset(request, obj, **kwargs)
    