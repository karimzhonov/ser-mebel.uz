from django.contrib import admin
from django.http import HttpRequest
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from unfold.contrib.filters.admin import RangeDateFilter
from unfold.admin import ModelAdmin
from unfold.decorators import display
from simple_history.admin import SimpleHistoryAdmin
from core.utils import get_tag
from constance import config
from .forms import OrderAddForm
from .actions import OrderActions
from .models import Order, OrderStatus
from .filters import OrderStatusDropdownFilter, OrderWarningDropdownFilter
from .constants import ORDER_VIEW_PRICE_PERMISSION
from .components import *


@admin.register(Order)
class OrderAdmin(OrderActions, ModelAdmin, SimpleHistoryAdmin):
    list_display = ['client', 'show_status', 'reception_date', 'end_date', 'show_days']
    readonly_fields = ['link_folder_document', 'link_folder_images', 'link_folder_schemas']
    ordering = ['-reception_date']
    autocomplete_fields = ['client']
    list_filter = [
        OrderStatusDropdownFilter,
        OrderWarningDropdownFilter,
        ('reception_date', RangeDateFilter),
    ]
    list_filter_submit = True
    list_before_template = 'order/order_list_before.html'

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def get_fieldsets(self, request: HttpRequest, obj=None):
        fieldsets = [
            ('Заказ', {"fields": ('client', 'desc', 'reception_date', 'end_date', 'metering'), "classes": ("tab-primary",)}),
            ('Адрес', {"fields": ('address', 'address_link'), "classes": ("tab-secondary",)}),
        ]
        if request.user.has_perm(f'order.{ORDER_VIEW_PRICE_PERMISSION}'):
            fieldsets.append(
                ('Цена', {'fields': ('currency', 'price', 'advance'), "classes": ("tab-info",)}),
            )
        fieldsets.append(
            ('Файлы', {'fields': ('link_folder_document', 'link_folder_images', 'link_folder_schemas'), "classes": ("tab-help",)})
        )
        add_fieldsets = [
            ('Заказ', {"fields": ('client', 'desc', 'reception_date', 'end_date', 'metering')}),
            ('Адрес', {"fields": ('address', 'address_link')}),
            ('Цена', {'fields': ('currency', 'price', 'advance')}),
        ]
        if obj:
            return fieldsets
        return add_fieldsets
    
    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs['form'] = OrderAddForm
        return super().get_form(request, obj, **kwargs)
    
    @display(
        description='Статус',
    )
    def show_status(self, obj: Order):
        statuses = {
            OrderStatus.CREATED: "info",
            OrderStatus.DETAILING: "info",
            OrderStatus.WORKING: "warning",
            OrderStatus.ASSEMBLY:  "warning",
            OrderStatus.INSTALLING:  "warning",
            OrderStatus.DONE:  "success",
        }
        return get_tag(OrderStatus(obj.status).label, statuses[obj.status])
    
    @display(
        description='Дней осталось',
    )
    def show_days(self, obj: Order):
        if obj.status == OrderStatus.DONE:
            return get_tag('Заказ готов', 'success')
        days = obj.days
        return (
            get_tag(f'До сдачи заказа осталось {days} дней', 'secondary' if days > config.WARNING_ORDER_DAYS else 'warning')
            if days >= 0 
            else get_tag(f'Заказ просрочен на {abs(days)} дней', 'danger')
        )
    
    # Filer links
    @display(
        description='Документы',
    )
    def link_folder_document(self, obj: Order):
        return format_html(f'<a class="text-blue-700" href="/admin/filer/folder/{obj.folder_documents_id}/list/">Перейти</a>') if obj.folder_documents_id else '-'


    @display(
        description='Фото',
    )
    def link_folder_images(self, obj: Order):
        return format_html(f'<a class="text-blue-700" href="/admin/filer/folder/{obj.folder_images_id}/list/">Перейти</a>') if obj.folder_images_id else '-'


    @display(
        description='Схеми',
    )
    def link_folder_schemas(self, obj: Order):
        return format_html(f'<a class="text-blue-700" href="/admin/filer/folder/{obj.folder_schemas_id}/list/">Перейти</a>') if obj.folder_schemas_id else '-'
