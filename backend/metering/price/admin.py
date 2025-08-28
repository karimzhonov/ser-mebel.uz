from django.contrib import admin
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from unfold.admin import ModelAdmin
from unfold.decorators import display, action
from unfold.dataclasses import ActionVariant
from simple_history.admin import SimpleHistoryAdmin
from core.utils.messages import instance_archive
from core.filters import get_date_filter
from core.utils import get_folder_link_html
from core.utils.html import get_boolean_icons
from .components import *
from .models import Price


@admin.register(Price)
class PriceAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ['metering', 'is_done', 'price']
    actions_submit_line = ['done_action']
    exclude = ['folder', 'done', 'metering']
    readonly_fields = ['metering_folder', 'folder_link']
    list_filter = [get_date_filter('created_at'), 'done']
    list_filter_submit = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        if obj and obj.done:
            return False
        return super().has_change_permission(request, obj)

    @display(description='Замер файлы')
    def metering_folder(self, obj: Price):
        return get_folder_link_html(obj.metering.folder_id)
    
    @display(description='Папка')
    def folder_link(self, obj: Price):
        return get_folder_link_html(obj.folder_id)

    @display(description='Выполнен')
    def is_done(self, obj: Price):
        return get_boolean_icons([obj.done])
    
    @action(
        description='Выполнить',
        url_path="done",
        variant=ActionVariant.SUCCESS,
        permissions=['done_action']
    )
    def done_action(self, request, obj: Price):
        if obj.done:
            instance_archive(request)
        obj.done = True
        obj.save()

    def has_done_action_permission(self, request, object_id):
        if not object_id: return True
        obj = get_object_or_404(Price, pk=object_id)
        return request.user.has_perm('price.change_price') and not obj.done
