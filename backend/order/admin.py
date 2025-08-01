from django.contrib import admin
from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from unfold.contrib.filters.admin import RangeDateFilter
from unfold.admin import ModelAdmin
from unfold.decorators import display, action
from simple_history.admin import SimpleHistoryAdmin
from core.utils import get_tag
from .models import Order, OrderStatus
from .filters import OrderStatusDropdownFilter, OrderWarningDropdownFilter
from .constants import WARNING_ORDER_DAYS, ORDER_CHANGE_STATUS_PERMISSION, ORDER_REVERSE_STATUS_PERMISSION
from .components import *


@admin.register(Order)
class OrderAdmin(ModelAdmin, SimpleHistoryAdmin):
    list_display = ['name', 'show_status', 'reception_date', 'end_date', 'show_days']
    readonly_fields = ['show_status', 'show_days', 'link_folder_document', 'link_folder_images', 'link_folder_schemas']
    ordering = ['-reception_date']
    autocomplete_fields = ['client']
    fieldsets = (
        ('Заказ', {"fields": ('client', 'name', 'desc', 'reception_date', 'end_date'), "classes": ("tab-primary",)}),
        ('Адрес', {"fields": ('address', 'address_link'), "classes": ("tab-secondary",)}),
        ('Цена', {'fields': ('currency', 'price', 'advance'), "classes": ("tab-info",)}),
        ('Файлы', {'fields': ('link_folder_document', 'link_folder_images', 'link_folder_schemas'), "classes": ("tab-help",)}),
    )
    actions_row = ['change_status', 'reverse_status']
    list_filter = [
        OrderStatusDropdownFilter,
        OrderWarningDropdownFilter,
        ('reception_date', RangeDateFilter),
    ]
    list_filter_submit = True
    list_before_template = 'order/order_list_before.html'
     
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
            get_tag(f'До сдачи заказа осталось {days} дней', 'secondary' if days > WARNING_ORDER_DAYS else 'warning')
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

    # Row actions
    @action(
        description=_("Изменить статус"),
        permissions=[f'order.{ORDER_CHANGE_STATUS_PERMISSION}'],
        url_path="change-status",
        icon='check',
        variant='success'
    )
    def change_status(self, request, object_id):
        obj = Order.objects.only('status').get(pk=object_id)
        current_status = obj.status
        next_status = OrderStatus.next_status(current_status)

        if next_status:
            obj.change_status(next_status)
            self.message_user(
                request,
                _(f"Статус изменён с «{OrderStatus(current_status).label}» на «{next_status.label}».")
            )
        else:
            self.message_user(
                request,
                _(f"Невозможно изменить статус: «{OrderStatus(current_status).label}» — финальный."),
                level="warning"
            )
        return redirect(
          reverse_lazy("admin:order_order_changelist")
        )
    
    @action(
        description=_("Возвращать статус"),
        permissions=[f'order.{ORDER_REVERSE_STATUS_PERMISSION}'],
        url_path="reverse-status",
        icon='close',
        variant='danger'
    )
    def reverse_status(self, request, object_id):
        obj = Order.objects.only('status').get(pk=object_id)
        current_status = obj.status
        previous_status = OrderStatus.previous_status(current_status)
        if previous_status:
            obj.change_status(previous_status)
            self.message_user(
                request,
                _(f"Статус изменён с «{OrderStatus(current_status).label}» на «{previous_status.label}».")
            )
        else:
            self.message_user(
                request,
                _(f"Невозможно возвращать статус: «{OrderStatus(current_status).label}» — начальный."),
                level="warning"
            )
        return redirect(
          reverse_lazy("admin:order_order_changelist")
        )
