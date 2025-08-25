from unfold.contrib.filters.admin import DropdownFilter
from django.utils.translation import gettext_lazy as _
from django.db.models import F, ExpressionWrapper, DecimalField, Value
from djmoney.settings import CURRENCY_CHOICES
from core.djmoney import get_rate


class CurrencyDropdownFilter(DropdownFilter):
    title = _("Валюта")
    parameter_name = "currency"

    def lookups(self, request, model_admin):
        return CURRENCY_CHOICES

    def queryset(self, request, queryset):
        return queryset
