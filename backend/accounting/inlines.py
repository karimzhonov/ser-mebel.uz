from django.http import HttpRequest
from unfold.admin import TabularInline

from .models import Expense, EXPENSE_ORDER_PERMISSION


class ExposeInline(TabularInline):
    model = Expense
    extra = 0
    tab = True

    def has_add_permission(self, request: HttpRequest, *args, **kwargs) -> bool:
        return request.user.has_perm(f'accounting.{EXPENSE_ORDER_PERMISSION}')

    def has_change_permission(self, *args, **kwargs) -> bool:
        return False
    
    def has_delete_permission(self, *args, **kwargs) -> bool:
        return False
    