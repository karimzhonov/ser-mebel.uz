from unfold.contrib.filters.admin import MultipleDropdownFilter
from django.utils.translation import gettext_lazy as _

from .constants import MeteringStatus


class MeteringStatusDropdownFilter(MultipleDropdownFilter):
    title = _("Статус")
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return [
            *[
            [status.value, _(status.label)]
            for status in MeteringStatus.get_order()
        ]]

    def queryset(self, request, queryset):
        if self.value() and not self.value() in ['', None]:
            return queryset.filter(status__in=self.value())
        return queryset