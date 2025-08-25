from django.http import HttpRequest
from unfold.admin import TabularInline

from .models import Expense


class ExposeInline(TabularInline):
    model = Expense
    extra = 0
    tab = True

    def has_add_permission(self, *args, **kwargs) -> bool:
        return False
    
    def has_change_permission(self, *args, **kwargs) -> bool:
        return False
    
    def has_delete_permission(self, *args, **kwargs) -> bool:
        return False
    