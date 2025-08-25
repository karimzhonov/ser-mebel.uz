from typing import Any
from django.contrib import admin
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from unfold.admin import ModelAdmin
from unfold.decorators import display
from simple_history.admin import SimpleHistoryAdmin
from core.utils import get_tag, get_folder_link_html
from core.filters import get_date_filter
from constance import config
from .forms import OrderAddForm
from .actions import OrderActions
from .models import Order, OrderStatus
from .constants import ORDER_VIEW_PRICE_PERMISSION
from .filters import OrderStatusDropdownFilter, OrderWarningDropdownFilter
from .components import *


@admin.register(Order)
class OrderAdmin(OrderActions,SimpleHistoryAdmin, ModelAdmin):
    list_display = ['client', 'show_status', 'reception_date', 'end_date', 'show_days']
    ordering = ['-reception_date']
    autocomplete_fields = ['client']
    list_filter = [
        OrderStatusDropdownFilter,
        OrderWarningDropdownFilter,
        get_date_filter('reception_date')
    ]
    list_filter_submit = True
    
    def get_readonly_fields(self, request: HttpRequest, obj: Any | None = ...) -> list[str] | tuple[Any, ...]:
        return ['folder_link', 'metering', 'client'] if obj else []

    def get_fieldsets(self, request: HttpRequest, obj=None):
        fieldsets = [
            ('Заказ', {"fields": ('client', 'desc', 'reception_date', 'end_date', 'folder_link'), "classes": ("tab-info",)}),
            ('Адрес', {"fields": ('address', 'address_link'), "classes": ("tab-info",)}),
        ]
        add_fieldsets = [
            ('Заказ', {"fields": ('client', 'desc', 'reception_date', 'end_date', 'design_type', 'metering')}),
            ('Адрес', {"fields": ('address', 'address_link')}),
            ('Цена', {'fields': ('price', 'lost_money')}),
        ]
        if request.user.has_perm(f'order.{ORDER_VIEW_PRICE_PERMISSION}'):
            fieldsets.append(
                ('Цена', {'fields': ('price', 'lost_money'), "classes": ("tab-info",)}),
            )
        return add_fieldsets if not obj else fieldsets
    
    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs['form'] = OrderAddForm
        return super().get_form(request, obj, **kwargs)
    
    @display(
        description='Статус',
    )
    def show_status(self, obj: Order):
        return get_tag(OrderStatus(obj.status).label, OrderStatus.get_sev(obj.status))
    
    @display(
        description='Дней осталось',
    )
    def show_days(self, obj: Order, days_minus = 0):
        if obj.status == OrderStatus.DONE:
            return get_tag('Заказ готов', 'success')
        days = obj.days - days_minus
        return (
            get_tag(f'До сдачи заказа осталось {days} дней', 'secondary' if days > config.WARNING_ORDER_DAYS else 'warning')
            if days >= 0 
            else get_tag(f'Заказ просрочен на {abs(days)} дней', 'danger')
        )
    
    # Filer links
    @display(
        description='Файлы',
    )
    def folder_link(self, obj: Order):
        return get_folder_link_html(obj.folder_id)
    