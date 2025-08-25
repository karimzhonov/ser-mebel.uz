import json
from django.db.models import Count
from django.contrib.admin import site
from django.db.models.functions import TruncDate, TruncMonth
from unfold.components import register_component, BaseComponent

from .models import Client


@register_component
class ClientLineChartComponent(BaseComponent):

    def get_context_data(self, **kwargs):
        from .admin import ClientAdmin

        self.request.GET._mutable = True
        self.request.GET.setdefault('date', 'month')

        change_list = ClientAdmin(Client, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)

        dateExp = TruncMonth if 'year' in self.request.GET.get('date', []) else TruncDate
        
        qs = list(queryset.annotate(
            date=dateExp("created_at")
        ).values('date').annotate(
            count=Count('phone'),
        ).order_by('date'))

        kwargs.update(data=json.dumps({
            "labels": [v['date'].strftime('%B' if 'year' in self.request.GET.get('date', []) else '%d.%m.%Y') for v in qs],
            "datasets": [
                {
                    "data": [v['count'] for v in qs],
                    "borderColor": "var(--color-primary-700)",
                }
            ]
        }))
        return kwargs


@register_component
class ClientTopComponent(BaseComponent):

    def get_context_data(self, **kwargs):
        from .admin import ClientAdmin

        change_list = ClientAdmin(Client, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)

        qs = queryset.annotate(
            count_order=Count('order__id', distinct=True)
        ).order_by('-count_order')[:10]
        kwargs.update(
            table_data={
                "headers": ['ФИО', 'Номер телефона', 'Кол-во'],
                "rows": [
                    [row.fio, row.phone, row.count_order] for row in qs
                ]
            }
        )
        return kwargs
