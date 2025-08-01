from unfold.components import BaseComponent, register_component
from django.contrib.admin import site
from core.utils import sev_to_color

from .models import Invoice
from .constants import SolutionChoice


@register_component
class SolutionBanner(BaseComponent):
    def get_context_data(self, **kwargs):
        from .admin import InvoiceAdmin

        context = super().get_context_data(**kwargs)
        change_list = InvoiceAdmin(Invoice, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)
        
        solutions = [
            {
                'solution': solution,
                'label': solution.label,
                'count': queryset.filter(solution=solution).count(),
                'icon': SolutionChoice.icon(solution),
                'color': sev_to_color(SolutionChoice.variant(solution).value),
            } for solution in SolutionChoice.get_order()
        ]
        context.update({
            'solutions': [
                {
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