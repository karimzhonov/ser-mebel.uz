from unfold.components import BaseComponent, register_component
from django.contrib.admin import site
from .models import Rover


@register_component
class RoverStatusComponent(BaseComponent):

    def get_context_data(self, **kwargs):
        from .admin import RoverAdmin

        change_list = RoverAdmin(Rover, site).get_changelist_instance(self.request)
        queryset = change_list.get_queryset(self.request)

        kwargs.update(
            done=queryset.filter(done=True).count(),
            not_done=queryset.filter(done=False).count(),
        )
        return kwargs
