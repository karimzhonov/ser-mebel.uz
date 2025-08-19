from django.contrib import admin
from django.http import HttpRequest
from django.shortcuts import redirect
from django.urls import reverse_lazy
from unfold.admin import ModelAdmin
from unfold.decorators import display, action
from unfold.dataclasses import ActionVariant
from simple_history.admin import SimpleHistoryAdmin

from core.utils import get_folder_link_html
from core.utils.html import get_boolean_icons

from .models import Price


@admin.register(Price)
class PriceAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ['metering', 'is_done']
    actions_detail = ['done_action']
    exclude = ['folder', 'done']
    readonly_fields = ['metering', 'folder_link']

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
    
    @display(description='Папка')
    def folder_link(self, obj: Price):
        return get_folder_link_html(obj.folder_id)

    @display(description='Выполнен')
    def is_done(self, obj: Price):
        return get_boolean_icons([obj.done])
    
    @action(
        description='Выполнить',
        url_path="done",
        variant=ActionVariant.SUCCESS
    )
    def done_action(self, request, object_id):
        Price.objects.filter(pk=object_id).update(
            done=True
        )
        return redirect(reverse_lazy('admin:price_price_changelist'))
