from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.http import HttpRequest
from unfold.admin import ModelAdmin
from unfold.enums import ActionVariant
from unfold.decorators import display, action
from core.utils.html import get_boolean_icons, get_folder_link_html
from core.filters import get_date_filter
from .components import *
from .models import Painter


@admin.register(Painter)
class PainterAdmin(ModelAdmin):
    list_display = ['order', 'is_done']
    exclude = ['folder', 'done', 'order']
    readonly_fields = ['folder_link', 'order_folder_link']
    actions_detail = ['done_action']
    list_filter = [get_date_filter('created_at')]
    
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
    
    def has_change_permission(self, request: HttpRequest, obj:  None = None) -> bool:
        return False

    @display(description='Выполнен')
    def is_done(self, obj: Painter):
        return get_boolean_icons([obj.done])
    
    @display(description='Файлы')
    def folder_link(self, obj: Painter):
        return get_folder_link_html(obj.folder_id)
    
    @display(description='Файлы заказа')
    def order_folder_link(self, obj: Painter):
        return get_folder_link_html(obj.order.folder_id) 
    
    def get_actions_detail(self, request, object_id: int):
        obj = Painter.objects.get(pk=object_id)
        return [] if obj.done else [self.get_unfold_action('done_action')]

    @action(
        description='Выполнить',
        url_path="done",
        variant=ActionVariant.SUCCESS
    )
    def done_action(self, request, object_id):
        obj = Painter.objects.get(pk=object_id)
        obj.done = True
        obj.save()
        return redirect(reverse_lazy('admin:detailing_detailing_changelist'))
