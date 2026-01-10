from django.contrib import admin
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from core.unfold import ModelAdmin
from unfold.decorators import display, action
from unfold.dataclasses import ActionVariant
from simple_history.admin import SimpleHistoryAdmin
from core.utils.messages import instance_archive
from core.filters import get_date_filter
from core.utils import get_folder_link_html
from core.utils.html import get_boolean_icons

from .excel import download_inlines_excel
from .components import *
from .models import Price, Inventory, InventoryType, ObjectType
from .inlines import InventoryInline, CalculateInline


@admin.register(Price)
class PriceAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ['metering', 'is_done', 'price']
    actions_submit_line = ['done_action']
    actions_detail = ['download_excel']
    exclude = ['folder', 'done', 'metering']
    readonly_fields = ['metering_folder', 'folder_link']
    list_filter = [get_date_filter('created_at'), 'done']
    list_filter_submit = True
    
    def get_inlines(self, request, obj):
        inlines = []
        for o in ObjectType.objects.all():
            class_attrs = {
                "verbose_name": o.name,
                "verbose_name_plural": o.name,
                "object_type_id": int(o.pk),
            }
            inlines.append(type(f'Object{o.pk}CalculateInline',(CalculateInline,), class_attrs))
        return inlines

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
    
    @action(
        description='Excel',
        url_path="download-excel",
        variant=ActionVariant.PRIMARY,
        permissions=['download_excel']
    )
    def download_excel(self, request, object_id):
        return download_inlines_excel(request, object_id)
    
    def has_download_excel_permission(self, request, object_id):
        return True


@admin.register(InventoryType)
class InventoryTypeAdmin(ModelAdmin):
    list_display = ['name', 'type']
    inlines = [InventoryInline]

    def has_add_permission(self, request):
        return super(ModelAdmin, self).has_add_permission(request)


@admin.register(Inventory)
class InventoryAdmin(ModelAdmin):
    list_display = ['name', 'type', 'price']
    list_filter = ['type']


@admin.register(ObjectType)
class ObjectTypeAdmin(ModelAdmin):
    list_display = ['name']
