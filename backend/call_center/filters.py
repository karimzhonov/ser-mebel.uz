from unfold.contrib.filters.admin import DropdownFilter
from django.utils.translation import gettext_lazy as _

from .constants import SolutionChoice


class InvoiceSolutionDropdownFilter(DropdownFilter):
    title = _("Код ответа")
    parameter_name = "solution"

    def lookups(self, request, model_admin):
        return [
            *[
            [solution.value, _(solution.label)]
            for solution in SolutionChoice.get_order()
        ]]

    def queryset(self, request, queryset):
        if not self.value() in ['', None]:
            return queryset.filter(solution=self.value())
        return queryset