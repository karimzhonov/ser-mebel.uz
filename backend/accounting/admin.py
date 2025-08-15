from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Income, IncomeCategory, Expense, ExpenseCategory


@admin.register(Income)
class IncomeAdmin(ModelAdmin):
    pass


@admin.register(IncomeCategory)
class IncomeCategoryAdmin(ModelAdmin):
    pass


@admin.register(Expense)
class ExpenseAdmin(ModelAdmin):
    pass


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(ModelAdmin):
    pass
