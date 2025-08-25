import json
from unfold.components import BaseComponent, register_component
from django.contrib.admin import site
from django.db.models import Count
from django.db.models.functions import TruncDate, TruncMonth
from django.contrib.admin import site
from core.utils import get_colors

from .models import Metering
from .constants import MeteringStatus


@register_component
class MeteringStatusBanner(BaseComponent):
    def get_context_data(self, **kwargs):
        from .admin import MeteringAdmin

        self.request.GET._mutable = True
        current_status = self.request.GET.pop('status', [])
        
        context = super().get_context_data(**kwargs)
        change_list = MeteringAdmin(Metering, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)
        count = queryset.count()

        statuses = [
            {
                'border': f'border-2 border-{MeteringStatus.variant(status).value}-500' if status in current_status else '',
                'status': status,
                'label': MeteringStatus(status).label,
                'count': queryset.filter(status=status).count(),
                'per': (queryset.filter(status=status).count() / count) if count > 0 else 0,
                'icon': MeteringStatus.icon(status),
                'color': get_colors(MeteringStatus.variant(status).value),
            } for status in MeteringStatus.values
        ]
        context.update({
            'statuses': [
                {
                    'border': 'border dark:border-transparent',
                    'status': '',
                    'label': 'Все заявки',
                    'count': queryset.count(),
                    'icon': 'box',
                    'color': 'gray',
                },
                *statuses,
            ],
            'statuses_per': statuses
        })
        return context


@register_component
class MeteringLineChartComponent(BaseComponent):

    def get_context_data(self, **kwargs):
        from .admin import MeteringAdmin

        change_list = MeteringAdmin(Metering, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)
        dateExp = TruncMonth if 'year' in self.request.GET.get('date', []) else TruncDate

        qs = list(queryset.annotate(
            date=dateExp("create_date")
        ).values('date').annotate(
            count=Count('id'),
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
    