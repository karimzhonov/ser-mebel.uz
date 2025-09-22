from django.contrib import admin
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.http import HttpRequest
from core.unfold import ModelAdmin
from unfold.enums import ActionVariant
from unfold.decorators import display, action
from core.utils.html import get_boolean_icons, get_folder_link_html
from core.filters import get_date_filter
from .components import *
from .models import Rover


@admin.register(Rover)
class RoverAdmin(ModelAdmin):
    list_display = ['order', 'is_done', 'square', 'price']
    exclude = ['folder', 'done', 'order']
    readonly_fields = ['square', 'price', 'order_folder_link', 'folder_link']
    actions_detail = ['done_action']
    list_filter = [get_date_filter('created_at'), 'done']
    list_filter_submit = True
    
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
    
    def has_change_permission(self, request: HttpRequest, obj = None) -> bool:
        return False

    @display(description='Выполнен')
    def is_done(self, obj: Rover):
        return get_boolean_icons([obj.done])
    
    @display(description='Файлы')
    def folder_link(self, obj: Rover):
        return get_folder_link_html(obj.folder_id)

    @display(description='Файлы заказа')
    def order_folder_link(self, obj: Rover):
        return get_folder_link_html(obj.order.folder_id) 
    
    @action(
        description='Выполнить',
        url_path="done",
        variant=ActionVariant.SUCCESS,
        permissions=['done_action'],
    )
    def done_action(self, request, object_id):
        obj = Rover.objects.get(pk=object_id)
        obj.done = True
        obj.save()
        return redirect(reverse_lazy('admin:rover_rover_changelist', query={'done': False}))

    def has_done_action_permission(self, request, object_id: Rover):
        obj = get_object_or_404(Rover, pk=object_id)
        return request.user.has_perm('rover.change_rover') and not obj.done
