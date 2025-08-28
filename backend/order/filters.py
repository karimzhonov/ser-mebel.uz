from unfold.contrib.filters.admin import DropdownFilter, MultipleDropdownFilter
from django.utils.translation import gettext_lazy as _
from .components import WarningBanner
from .constants import OrderStatus


class OrderWarningDropdownFilter(DropdownFilter):
    title = _('Дней осталось')
    parameter_name = 'warning'

    def lookups(self, request, model_admin):
        return [
            (color, warning['label'])
            for color, warning in WarningBanner.defaults().items()
        ]
    
    def queryset(self, request, queryset):
        if self.value() and self.value() in WarningBanner.defaults().keys():
            return queryset.filter(**WarningBanner.defaults()[self.value()]['filters'])
        return queryset


class OrderStatusDropdownFilter(MultipleDropdownFilter):
    title = _("Статус")
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return OrderStatus.choices

    def queryset(self, request, queryset):
        value = ','.join(self.value())
        if value and not value in ['']:
            return queryset.filter(status__in=value.split(','))
        return queryset