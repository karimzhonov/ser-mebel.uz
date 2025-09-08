from unfold.admin import StackedInline, TabularInline
from .models import Calculate, Inventory
from .forms import CalculateForm


class CalculateInline(StackedInline):
    model = Calculate
    extra = 0
    tab = True
    form = CalculateForm


class InventoryInline(TabularInline):
    model = Inventory
    extra = 0
    tab = True
