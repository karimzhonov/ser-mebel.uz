from unfold.contrib.filters.admin import DropdownFilter
from django.utils.translation import gettext_lazy as _

from .constants import MeteringStatus


class MeteringStatusDropdownFilter(DropdownFilter):
    title = _("Статус")
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return [
            *[
            [status.value, _(status.label)]
            for status in MeteringStatus.get_order()
        ]]

    def queryset(self, request, queryset):
        if not self.value() in ['', None]:
            return queryset.filter(status=self.value())
        return queryset