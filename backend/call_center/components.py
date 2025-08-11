from unfold.components import BaseComponent, register_component
from django.contrib.admin import site
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
        
        solutions = [
            {
                'border': f'border-2 border-{SolutionChoice.variant(solution).value}-500' if solution in current_solution else '',
                'solution': solution,
                'label': solution.label,
                'count': queryset.filter(solution=solution).count(),
                'icon': SolutionChoice.icon(solution),
                'color': get_colors(SolutionChoice.variant(solution).value),
            } for solution in SolutionChoice.get_order()
        ]
        context.update({
            'solutions': [
                {
                    "border": "border dark:border-transparent",
                    'status': '',
                    'label': 'Все заявки',
                    'count': queryset.count(),
                    'icon': 'box',
                    'color': 'gray',
                },
                *solutions,
            ]
        })
        return context