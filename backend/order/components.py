from django.contrib import admin

from unfold.components import BaseComponent, register_component
from constance import config
from core.utils import get_colors
from .models import Order, OrderStatus


@register_component
class StatusBanner(BaseComponent):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.status_context())
        return context
    
    def status_context(self):
        from .admin import OrderAdmin

        self.request.GET._mutable = True
        current_status = self.request.GET.pop('status', [])

        change_list = OrderAdmin(Order, admin.site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)

        statuses = [
            {
                'border': f'border-2 border-{OrderStatus.get_sev(status)}-500' if status in current_status else f'',
                'status': status,
                'label': status.label,
                'count': queryset.filter(status=status).count(),
                'icon': OrderStatus.icon(status),
                'color': get_colors(OrderStatus.get_sev(status)),
            } for i, status in enumerate(OrderStatus.get_order())
        ]

        return {
            'statuses': [
                {
                    "border": "border dark:border-transparent",
                    'status': '',
                    'label': 'Все закази',
                    'count': queryset.count(),
                    'icon': 'box',
                    'color': 'gray',
                },
                *statuses,
            ]
        }


@register_component
class WarningBanner(BaseComponent):

    @staticmethod
    def defaults():
        return {
        'success': {
            "icon": "check",
            "label": 'До сдачи заказа осталось более 7 дней',
            "filters": {"days__gte": config.WARNING_ORDER_DAYS}
        },
        'warning': {
            "icon": "warning",
            "label": 'До сдачи заказа осталось менее 7 дней',
            "filters": {"days__lt": config.WARNING_ORDER_DAYS, "days__gt": 0}
        },
        'danger': {
            "icon": 'close',
            "label": 'Заказ просрочен',
            "filters": {"days__lte": 0}
        }
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.warnings_context())
        return context
    
    def warnings_context(self):
        from .admin import OrderAdmin
        
        self.request.GET._mutable = True
        current_warning = self.request.GET.pop('warning', [])

        change_list = OrderAdmin(Order, admin.site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request, exclude_parameters=['tabs'])
        return {
            'warnings': [
                {
                    'warning': color,
                    'border': f'border-2 border-{color}-500' if color in current_warning else f'',
                    'label': warning['label'],
                    'count': queryset.exclude(status=OrderStatus.DONE).filter(**warning['filters']).count(),
                    'color': get_colors(color),
                    'icon': warning['icon'],
                } for color, warning in self.defaults().items()
            ]
        }
