from django.db import models
from djmoney.models.fields import MoneyField


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=255)
    user = models.ForeignKey('oauth.User', models.SET_NULL, blank=True, null=True)

    def __str__(self):
        return self.name


class Expense(models.Model):
    user = models.ForeignKey('oauth.User', models.CASCADE)
    cost = MoneyField(max_digits=12)
    category = models.ForeignKey(ExpenseCategory, models.PROTECT)
    desc = models.TextField(blank=True, null=True)
    order = models.ForeignKey('order.Order', models.SET_NULL, blank=True, null=True)


class IncomeCategory(models.Model):
    name = models.CharField(max_length=255)
    user = models.ForeignKey('oauth.User', models.SET_NULL, blank=True, null=True)

    def __str__(self):
        return self.name


class Income(models.Model):
    user = models.ForeignKey('oauth.User', models.CASCADE)
    cost = MoneyField(max_digits=12)
    category = models.ForeignKey(ExpenseCategory, models.PROTECT)
    desc = models.TextField(blank=True, null=True)

