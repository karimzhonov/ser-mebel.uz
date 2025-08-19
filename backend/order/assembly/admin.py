from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.http import HttpRequest
from unfold.admin import ModelAdmin
from unfold.enums import ActionVariant
from unfold.decorators import display, action
from core.utils.html import get_boolean_icons, get_folder_link_html
from ..constants import OrderStatus
from .models import Assembly


@admin.register(Assembly)
class AssemblyAdmin(ModelAdmin):
    list_display = ['order', 'is_done', 'is_installing_done']
    exclude = ['folder', 'done', 'installing_done']
    readonly_fields = ['folder_link', 'order', 'square', 'price']
    actions_detail = ['done_action', 'installing_done_action']
    
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @display(description='Выполнен сборка')
    def is_done(self, obj: Assembly):
        return get_boolean_icons([obj.done])
    
    @display(description='Выполнен установка')
    def is_installing_done(self, obj: Assembly):
        return get_boolean_icons([obj.installing_done])
    
    @display(description='Папка')
    def folder_link(self, obj: Assembly):
        return get_folder_link_html(obj.folder_id)
    
    def get_actions_detail(self, request, object_id: int):
        obj = Assembly.objects.get(pk=object_id)
        if not obj.done:
            return [self.get_unfold_action('done_action')]
        return [] if obj.installing_done else [self.get_unfold_action('installing_done_action')]

    @action(
        description='Выполнить сборку',
        url_path="done",
        variant=ActionVariant.SUCCESS
    )
    def done_action(self, request, object_id):
        obj = Assembly.objects.get(pk=object_id)
        obj.done = True
        obj.save(update_fields=['done'])
        obj.order.status = OrderStatus.INSTALLING
        obj.order.save(update_fields=['status'])
        return redirect(reverse_lazy('admin:assembly_assembly_changelist'))
    
    @action(
        description='Выполнить установку',
        url_path="installing-done",
        variant=ActionVariant.SUCCESS
    )
    def installing_done_action(self, request, object_id):
        obj = Assembly.objects.get(pk=object_id)
        obj.installing_done = True
        obj.save(update_fields=['installing_done'])
        obj.order.status = OrderStatus.DONE
        obj.order.save(update_fields=['status'])
        return redirect(reverse_lazy('admin:assembly_assembly_changelist'))
