import json
from unfold.components import BaseComponent, register_component
from django.contrib.admin import site
from django.db.models import Count, Sum, F
from django.db.models.functions import TruncDate, TruncMonth
from django.contrib.admin import site
from djmoney.settings import CURRENCY_CHOICES, DEFAULT_CURRENCY
from djmoney.money import Money
from .models import Expense, Income


@register_component
class ExpenseProgressComponent(BaseComponent):

    def get_context_data(self, **kwargs):
        from .admin import ExpenseAdmin

        change_list = ExpenseAdmin(Expense, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)
        cost = queryset.aggregate(cost=Sum('converted_cost')).get('cost')
        currency = ''.join(self.request.GET.get('currency', [DEFAULT_CURRENCY]))

        kwargs.update(
            categories=queryset.values(
                "category"
            ).annotate(
                label = F('category__name'),
                per = (Sum('converted_cost') / cost) if cost else 100,
                cost = Sum('converted_cost'),
            ))
        for cat in kwargs['categories']:
            cat['cost'] = Money(round(cat["cost"], 2), currency)

        kwargs.update(
            cost=Money(round(cost, 2), currency)
        )
        return kwargs


@register_component
class ExpenseLineChartComponent(BaseComponent):
    
    def get_context_data(self, **kwargs):
        from .admin import ExpenseAdmin

        self.request.GET._mutable = True
        self.request.GET.setdefault('date', 'month')

        change_list = ExpenseAdmin(Expense, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)
        dateExp = TruncMonth if 'year' in self.request.GET.get('date', []) else TruncDate
    
        qs = list(queryset.annotate(
            date=dateExp("created_at")
        ).values('date').annotate(
            count=Sum('converted_cost'),
        ).order_by('date'))

        kwargs.update(data=json.dumps({
            "labels": [v['date'].strftime('%B' if 'year' in self.request.GET.get('date', []) else '%d.%m.%Y') for v in qs],
            "datasets": [
                {
                    "data": [float(v['count']) for v in qs],
                    "borderColor": "var(--color-primary-700)",
                }
            ]
        }))
        return kwargs
 

 
@register_component
class IncomeProgressComponent(BaseComponent):

    def get_context_data(self, **kwargs):
        from .admin import IncomeAdmin

        change_list = IncomeAdmin(Income, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)
        cost = queryset.aggregate(cost=Sum('converted_cost')).get('cost')
        currency = ''.join(self.request.GET.get('currency', [DEFAULT_CURRENCY]))

        kwargs.update(
            categories=queryset.values(
                "category"
            ).annotate(
                label = F('category__name'),
                per = (Sum('converted_cost') / cost) if cost else 100.0,
                cost = Sum('converted_cost'),
            ))
        for cat in kwargs['categories']:
            cat['cost'] = Money(round(cat["cost"], 2), currency)
        
        kwargs.update(
            cost=Money(round(cost, 2), currency)
        )
        return kwargs


@register_component
class IncomeLineChartComponent(BaseComponent):
    
    def get_context_data(self, **kwargs):
        from .admin import IncomeAdmin

        change_list = IncomeAdmin(Income, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)
        dateExp = TruncMonth if 'year' in self.request.GET.get('date', []) else TruncDate
    
        qs = list(queryset.annotate(
            date=dateExp("created_at")
        ).values('date').annotate(
            count=Count('id'),
        ).order_by('date'))

        kwargs.update(data=json.dumps({
            "labels": [v['date'].strftime('%B' if 'year' in self.request.GET.get('date', []) else '%d.%m.%Y') for v in qs],
            "datasets": [
                {
                    "data": [float(v['count']) for v in qs],
                    "borderColor": "var(--color-primary-700)",
                }
            ]
        }))
        return kwargs


@register_component
class CurrenciesComponent(BaseComponent):

    def get_context_data(self, **kwargs):
        currency = ''.join(self.request.GET.get('currency', [DEFAULT_CURRENCY]))
        currencies = [{"title": c, 'active': c == currency} for c in list(dict(CURRENCY_CHOICES).keys())]
        kwargs.update(
            items=currencies
        )
        return kwargs
