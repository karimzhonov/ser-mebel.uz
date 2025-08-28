from django.contrib import admin
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from unfold.enums import ActionVariant
from unfold.admin import ModelAdmin
from unfold.decorators import action, display
from core.utils.html import get_boolean_icons, get_folder_link_html
from core.filters import get_date_filter
from .models import Detailing
from ..constants import OrderStatus


@admin.register(Detailing)
class DetailingAdmin(ModelAdmin):
    list_display = ['order', 'is_done', 'is_working_done', 'square', 'rover_square', 'painter_square']
    actions_submit_line = ['done_action', 'working_done_action']
    exclude = ['folder', 'done', 'working_done', 'order']
    list_filter = [get_date_filter('created_at'), 'done']

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_save"] = False
        extra_context["show_save_and_continue"] = False
        extra_context["show_save_and_add_another"] = False
        return super().changeform_view(request, object_id, form_url, extra_context)

    def get_readonly_fields(self, request: HttpRequest, obj = None):
        return ['square', 'rover_square', 'painter_square', 'order_folder_link', 'folder_link'] if obj and obj.done else ['order_folder_link', 'folder_link']      
    
    @display(description='Выполнен деталировку')
    def is_done(self, obj: Detailing):
        return get_boolean_icons([obj.done])
    
    @display(description='Выполнен заказ на сырье')
    def is_working_done(self, obj: Detailing):
        return get_boolean_icons([obj.working_done])
    
    @display(description='Файли')
    def folder_link(self, obj: Detailing):
        return get_folder_link_html(obj.folder_id)
    
    @display(description='Файлы заказа')
    def order_folder_link(self, obj: Detailing):
        return get_folder_link_html(obj.order.folder_id) 
    
    @action(
        description='Выполнить деталировку',
        url_path="done",
        variant=ActionVariant.SUCCESS,
        permissions=['done_action'],
    )
    def done_action(self, request, obj):
        obj.done = True
        obj.save(update_fields=['done'])
        obj.order.status = OrderStatus.WORKING
        obj.order.save(update_fields=['status'])
    
    def has_done_action_permission(self, request, object_id: Detailing):
        if not object_id: return True
        obj = get_object_or_404(Detailing, pk=object_id)
        return request.user.has_perm('detailing.change_detailing') and not obj.done

    @action(
        description='Выполнить заказ на сырье',
        url_path="working-done",
        variant=ActionVariant.SUCCESS,
        permissions=['working_done_action']
    )
    def working_done_action(self, request, obj):
        obj.working_done = True
        obj.save(update_fields=['working_done'])
        obj.order.status = OrderStatus.ASSEMBLY
        obj.order.save(update_fields=['status'])

    def has_working_done_action_permission(self, request, object_id: Detailing = None):
        if not object_id: return True
        obj = get_object_or_404(Detailing, pk=object_id)
        return request.user.has_perm('detailing.change_detailing') and obj.done and not obj.working_done
