import json
from unfold.components import BaseComponent, register_component
from django.contrib.admin import site
from django.db.models import Count
from django.db.models.functions import TruncDate, TruncMonth

from core.utils import get_colors

from .models import Invoice
from .constants import SolutionChoice


@register_component
class SolutionBanner(BaseComponent):
    def get_context_data(self, **kwargs):
        from .admin import InvoiceAdmin

        context = super().get_context_data(**kwargs)
        change_list = InvoiceAdmin(Invoice, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)
        self.request.GET._mutable = True
        current_solution = self.request.GET.pop('solution', [])
        count = queryset.count()

        solutions = [
            {
                'border': f'border-2 border-{SolutionChoice.variant(solution).value}-500' if solution in current_solution else '',
                'solution': solution,
                'label': SolutionChoice(solution).label,
                'count': queryset.filter(solution=solution).count(),
                'per': queryset.filter(solution=solution).count() / count if count > 0 else 0,
                'icon': SolutionChoice.icon(solution),
                'color': get_colors(SolutionChoice.variant(solution).value),
            } for solution in SolutionChoice.values
        ]

        context.update({
            'solutions': [
                {
                    "border": "border dark:border-transparent",
                    'status': '',
                    'label': 'Все заявки',
                    'count': count,
                    'icon': 'box',
                    'color': 'gray',
                },
                *solutions,
            ],
            'solutions_per': solutions
        })
        return context
 


@register_component
class InvoiceLineChartComponent(BaseComponent):

    def get_context_data(self, **kwargs):
        from .admin import InvoiceAdmin

        self.request.GET._mutable = True
        self.request.GET.setdefault('date', 'month')

        change_list = InvoiceAdmin(Invoice, site).get_changelist_instance(self.request)
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
