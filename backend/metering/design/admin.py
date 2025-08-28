from django.contrib import admin
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils.http import urlencode
from django.http import HttpRequest
from unfold.admin import ModelAdmin
from unfold.dataclasses import ActionVariant
from unfold.decorators import action, display
from simple_history.admin import SimpleHistoryAdmin
from core.utils.html import get_boolean_icons, get_folder_link_html
from core.filters import get_date_filter
from core.utils.messages import instance_archive
from .models import Design
from .inlines import DesignTypeInline
from .components import *


@admin.register(Design)
class DesignAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ['metering', 'is_done', 'price']
    actions_detail = ['create_order']
    actions_submit_line = ['done_action']
    inlines = [DesignTypeInline]
    readonly_fields = ['metering_folder', 'created_at']
    exclude = ['done', 'metering']
    list_filter = [get_date_filter('created_at'), 'done']
    list_filter_submit = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
    
    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        if obj and obj.done:
            return False
        return super().has_change_permission(request, obj)
    
    @display(description='Выполнен')
    def is_done(self, obj: Design):
        return get_boolean_icons([obj.done])
    
    @display(description='Замер файлы')
    def metering_folder(self, obj: Design):
        return get_folder_link_html(obj.metering.folder_id)

    @action(
        description='Создать заказ',
        url_path="create-order",
        variant=ActionVariant.PRIMARY,
        permissions=['create_order']
    )
    def create_order(self, request, object_id: int):
        obj = Design.objects.get(pk=object_id)
        if hasattr(obj.metering, 'order'):
            instance_archive(request)
            return redirect(reverse_lazy('admin:design_design_changelist', query={'done': False}))
        url = reverse_lazy("admin:order_order_add")
        params = urlencode({
            "client": obj.metering.client_id or '',
            "address": obj.metering.address or '',
            "address_link": obj.metering.address_link or '',
            "reception_date": obj.metering.date_time.strftime('%d.%m.%Y'),
            "metering": obj.metering.pk,
            "price": f"{float(obj.metering.price.price.amount)}:{obj.metering.price.price.currency}",
        })
        return redirect(f'{url}?{params}')
    
    def has_create_order_permission(self, request, object_id):
        obj = get_object_or_404(Design, pk=object_id)
        return request.user.has_perm('order.add_order') and obj.done and not hasattr(obj.metering, 'order')

    @action(
        description='Выполнить дизайн',
        permissions=['done_action']
    )
    def done_action(self, request, obj: Design):
        if obj.done:
            instance_archive(request)
            return
        obj.done = True
        obj.save()

    def has_done_action_permission(self, request, object_id):
        if not object_id: return True
        obj = get_object_or_404(Design, pk=object_id)
        return request.user.has_perm('design.change_design') and not obj.done
    