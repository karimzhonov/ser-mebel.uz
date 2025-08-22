import json, datetime
from django.db.models import Count
from django.db.models.functions import TruncDate
from unfold.components import register_component, BaseComponent

from .models import Client


@register_component
class ClientLineChartComponent(BaseComponent):

    def get_context_data(self, **kwargs):
        qs = list(Client.objects.annotate(
            date=TruncDate("created_at")
        ).values('date').annotate(
            count=Count('phone'),
        ).order_by('date'))

        kwargs.update(data=json.dumps({
            "labels": [v['date'].strftime('%d.%m.%Y') for v in qs],
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
        qs = Client.objects.annotate(
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
