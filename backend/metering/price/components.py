from unfold.components import BaseComponent, register_component
from django.contrib.admin import site
from .models import Price


@register_component
class PriceStatusComponent(BaseComponent):

    def get_context_data(self, **kwargs):
        from .admin import PriceAdmin

        change_list = PriceAdmin(Price, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)

        kwargs.update(
            done=queryset.filter(done=True).count(),
            not_done=queryset.filter(done=False).count(),
        )
        return kwargs

