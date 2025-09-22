from unfold.admin import StackedInline, TabularInline
from .models import Calculate, Inventory
from .forms import CalculateForm


class CalculateInline(StackedInline):
    model = Calculate
    extra = 0
    tab = True
    form = CalculateForm

    object_type_id = None

    def get_formset(self, request, obj=None, **kwargs):
        self.form = type(f'Calculate{self.object_type_id}Form', (CalculateForm,), {"object_type_id": self.object_type_id})
        return super().get_formset(request, obj, **kwargs)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(obj_id=self.object_type_id)


class InventoryInline(TabularInline):
    model = Inventory
    extra = 0
    tab = True
