from unfold.contrib.filters.admin import DropdownFilter
from django.utils.translation import gettext_lazy as _

from .constants import DashboardFilterChoices


def get_date_filter(date_field):

    class DateFilter(DropdownFilter):
        title = _('Дата')
        parameter_name = 'date'

        def lookups(self, request, model_admin):
            return DashboardFilterChoices.choices
        
        def queryset(self, request, queryset):
            value = self.value()
            if value and value in DashboardFilterChoices.values:
                return queryset.filter(**DashboardFilterChoices.filters(value, date_field))
            return queryset
    
    return DateFilter
