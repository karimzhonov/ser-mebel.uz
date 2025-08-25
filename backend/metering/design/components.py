from unfold.components import BaseComponent, register_component
from django.contrib.admin import site
from .models import Design


@register_component
class DesignStatusComponent(BaseComponent):

    def get_context_data(self, **kwargs):
        from .admin import DesignAdmin

        change_list = DesignAdmin(Design, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)

        kwargs.update(
            done=queryset.filter(done=True).count(),
            not_done=queryset.filter(done=False).count(),
        )
        return kwargs
