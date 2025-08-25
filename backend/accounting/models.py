from django.db import models
from djmoney.models.fields import MoneyField
from djmoney.money import Money
from djmoney.settings import BASE_CURRENCY
from core.djmoney import ConvertedCostManager


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=255)
    user = models.ForeignKey('oauth.User', models.SET_NULL, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Expense(models.Model):
    user = models.ForeignKey('oauth.User', models.CASCADE)
    cost = MoneyField(max_digits=12)
    category = models.ForeignKey(ExpenseCategory, models.PROTECT)
    desc = models.TextField(blank=True, null=True)
    order = models.ForeignKey('order.Order', models.SET_NULL, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    manager = ConvertedCostManager(['cost'])

    def __str__(self):
        return ' - '.join([str(self.category), str(self.cost)])
    
    @property
    def cost_converted(self):
        if hasattr(self, "converted_cost") and hasattr(self, "converted_cost_currency"):
            return Money(self.converted_cost, self.converted_cost_currency)
        return self.cost


class IncomeCategory(models.Model):
    name = models.CharField(max_length=255)
    user = models.ForeignKey('oauth.User', models.SET_NULL, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Income(models.Model):
    user = models.ForeignKey('oauth.User', models.CASCADE)
    cost = MoneyField(max_digits=12)
    category = models.ForeignKey(IncomeCategory, models.PROTECT)
    desc = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    manager = ConvertedCostManager(['cost'])

    def __str__(self):
        return ' - '.join([str(self.category), str(self.cost)])
    
    @property
    def cost_converted(self):
        if hasattr(self, "converted_cost") and hasattr(self, "converted_cost_currency"):
            return Money(self.converted_cost, self.converted_cost_currency)
        return self.cost

