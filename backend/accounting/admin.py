from typing import Any
from django.contrib import admin
from django.db.models.query import QuerySet
from django.http import HttpRequest
from core.unfold import ModelAdmin
from core.filters import get_date_filter
from .filters import CurrencyDropdownFilter
from .forms import ExpenseForm
from .models import Income, IncomeCategory, Expense, ExpenseCategory
from .components import *


@admin.register(Income)
class IncomeAdmin(ModelAdmin):
    exclude = ['user']
    list_display = ['category', 'desc', 'cost', 'created_at']
    list_filter = [get_date_filter('created_at'), CurrencyDropdownFilter]
    list_filter_submit = True
    # list_before_template = 'accounting/income_before_list.html'

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        return super().get_queryset(request).filter(user=request.user)

    def save_model(self, request, obj: Income, *args, **kwargs):
        obj.user = request.user
        super().save_model(request, obj, *args, **kwargs)

    def has_delete_permission(self, request: HttpRequest, obj: Any | None = ...) -> bool:
        return False
    
    def has_change_permission(self, request: HttpRequest, obj: Any | None = ...) -> bool:
        return False
    
    def has_add_permission(self, request):
        return request.user.has_perm('accounting.add_income')


@admin.register(IncomeCategory)
class IncomeCategoryAdmin(ModelAdmin):
    exclude = ['user']

    def save_model(self, request, obj: IncomeCategory, *args, **kwargs):
        obj.user = request.user
        super().save_model(request, obj, *args, **kwargs)

    def has_delete_permission(self, request: HttpRequest, obj: Any | None = ...) -> bool:
        return False
    
    def has_change_permission(self, request: HttpRequest, obj: Any | None = ...) -> bool:
        return False


@admin.register(Expense)
class ExpenseAdmin(ModelAdmin):
    exclude = ['user']
    list_display = ['category', 'desc', 'cost', 'order', 'created_at']
    list_filter = [get_date_filter('created_at'), CurrencyDropdownFilter]
    list_filter_submit = True
    # list_before_template = 'accounting/expense_before_list.html'

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        return super().get_queryset(request).filter(user=request.user)
    
    def get_form(self, request: Any, obj: Expense, change: bool = False, **kwargs: Any) -> Any:
        kwargs.update(form=ExpenseForm)
        return super().get_form(request, obj, change, **kwargs)

    def save_model(self, request, obj: Expense, *args, **kwargs):
        obj.user = request.user
        super().save_model(request, obj, *args, **kwargs)

    def has_delete_permission(self, request: HttpRequest, obj: Any | None = ...) -> bool:
        return False
    
    def has_change_permission(self, request: HttpRequest, obj: Any | None = ...) -> bool:
        return False
    
    def has_add_permission(self, request):
        return request.user.has_perm('accounting.add_expense')


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(ModelAdmin):
    exclude = ['user']

    def save_model(self, request, obj: ExpenseCategory, *args, **kwargs):
        obj.user = request.user
        super().save_model(request, obj, *args, **kwargs)

    def has_delete_permission(self, request: HttpRequest, obj: Any | None = ...) -> bool:
        return False
    
    def has_change_permission(self, request: HttpRequest, obj: Any | None = ...) -> bool:
        return False
