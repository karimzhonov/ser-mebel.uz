from django.db import models
from djmoney.models.fields import MoneyField
from djmoney.money import Money
from core.djmoney import ConvertedCostManager

EXPENSE_ORDER_PERMISSION = 'create_order_expose'


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=255, verbose_name='Название')
    user = models.ForeignKey('oauth.User', models.SET_NULL, blank=True, null=True, verbose_name='Пользователь')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создание')

    def __str__(self):
        return self.name


class Expense(models.Model):
    user = models.ForeignKey('oauth.User', models.SET_NULL, null=True, blank=True, verbose_name='Пользователь')
    cost = MoneyField(max_digits=12, verbose_name='Сумма')
    category = models.ForeignKey(ExpenseCategory, models.CASCADE, verbose_name='Категория')
    desc = models.TextField(blank=True, null=True, verbose_name='Описание')
    order = models.ForeignKey('order.Order', models.SET_NULL, blank=True, null=True, verbose_name='Заказ')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создание')

    objects = ConvertedCostManager(['cost'])

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="User or order",
                check=(
                    models.Q(user__isnull=False) | models.Q(order__isnull=False)
                ),
            )
        ]
        permissions = [
            (EXPENSE_ORDER_PERMISSION, 'Create expense in order instance')
        ]

    def __str__(self):
        return ' - '.join([str(self.category), str(self.cost)])
    
    @property
    def cost_converted(self):
        if hasattr(self, "converted_cost") and hasattr(self, "converted_cost_currency"):
            return Money(self.converted_cost, self.converted_cost_currency)
        return self.cost


class IncomeCategory(models.Model):
    name = models.CharField(max_length=255, verbose_name='Название')
    user = models.ForeignKey('oauth.User', models.SET_NULL, blank=True, null=True, verbose_name='Пользователь')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создание')

    def __str__(self):
        return self.name


class Income(models.Model):
    user = models.ForeignKey('oauth.User', models.CASCADE, verbose_name='Пользователь')
    cost = MoneyField(max_digits=12, verbose_name='Сумма')
    category = models.ForeignKey(IncomeCategory, models.CASCADE, verbose_name='Категория')
    desc = models.TextField(blank=True, null=True, verbose_name='Описание')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создание')

    objects = ConvertedCostManager(['cost'])

    def __str__(self):
        return ' - '.join([str(self.category), str(self.cost)])
    
    @property
    def cost_converted(self):
        if hasattr(self, "converted_cost") and hasattr(self, "converted_cost_currency"):
            return Money(self.converted_cost, self.converted_cost_currency)
        return self.cost

