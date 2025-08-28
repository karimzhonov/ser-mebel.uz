from unfold.contrib.filters.admin import MultipleDropdownFilter
from django.utils.translation import gettext_lazy as _

from .constants import MeteringStatus


class MeteringStatusDropdownFilter(MultipleDropdownFilter):
    title = _("Статус")
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return MeteringStatus.choices

    def queryset(self, request, queryset):
        value = ','.join(self.value())
        if value and not value in ['']:
            return queryset.filter(status__in=value.split(','))
        return queryset
