from unfold.components import BaseComponent, register_component
from django.contrib.admin import site
from core.utils import sev_to_color

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
        
        statuses = [
            {
                'border': 'border-2' if status in current_status else 'border',
                'status': status,
                'label': status.label,
                'count': queryset.filter(status=status).count(),
                'icon': MeteringStatus.icon(status),
                'color': sev_to_color(MeteringStatus.variant(status).value),
            } for status in MeteringStatus.get_order()
        ]
        context.update({
            'statuses': [
                {
                    'status': '',
                    'label': 'Все заявки',
                    'count': queryset.count(),
                    'icon': 'box',
                    'color': 'gray',
                },
                *statuses,
            ]
        })
        return context