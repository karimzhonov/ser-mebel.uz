from django.contrib import admin

from unfold.components import BaseComponent, register_component
from .models import Order, OrderStatus
from .constants import WARNING_ORDER_DAYS


@register_component
class StatusBanner(BaseComponent):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.status_context())
        return context
    
    def status_context(self):
        from .admin import OrderAdmin

        change_list = OrderAdmin(Order, admin.site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)

        status_icons = ['add', 'book', 'monitor', 'bolt', 'build', 'check']
        status_colors = ['blue', 'indigo', 'amber', 'yellow', 'orange', 'green']

        statuses = [
            {
                'status': status,
                'label': status.label,
                'count': queryset.filter(status=status).count(),
                'icon': status_icons[i],
                'color': status_colors[i],
            } for i, status in enumerate(OrderStatus.get_order())
        ]

        return {
            'statuses': [
                {
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
    defaults = {
        'green': {
            "icon": "check",
            "label": 'До сдачи заказа осталось более 7 дней',
            "filters": {"days__gte": WARNING_ORDER_DAYS}
        },
        'orange': {
            "icon": "warning",
            "label": 'До сдачи заказа осталось менее 7 дней',
            "filters": {"days__lt": WARNING_ORDER_DAYS, "days__gt": 0}
        },
        'red': {
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

        change_list = OrderAdmin(Order, admin.site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)
        return {
            'warnings': [
                {
                    'label': warning['label'],
                    'count': queryset.exclude(status=OrderStatus.DONE).filter(**warning['filters']).count(),
                    'color': color,
                    'icon': warning['icon'],
                } for color, warning in self.defaults.items()
            ]
        }