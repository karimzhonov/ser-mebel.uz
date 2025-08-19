from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.http import HttpRequest
from unfold.admin import ModelAdmin
from unfold.enums import ActionVariant
from unfold.decorators import display, action
from core.utils.html import get_boolean_icons, get_folder_link_html
from .models import Rover


@admin.register(Rover)
class RoverAdmin(ModelAdmin):
    list_display = ['order', 'is_done']
    exclude = ['folder', 'done']
    readonly_fields = ['folder_link']
    actions_detail = ['done_action']
    
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
    
    def has_change_permission(self, request: HttpRequest, obj:  None = None) -> bool:
        return False

    @display(description='Выполнен')
    def is_done(self, obj: Rover):
        return get_boolean_icons([obj.done])
    
    @display(description='Папка')
    def folder_link(self, obj: Rover):
        return get_folder_link_html(obj.folder_id)
    
    def get_actions_detail(self, request, object_id: int):
        obj = Rover.objects.get(pk=object_id)
        return [] if obj.done else [self.get_unfold_action('done_action')]

    @action(
        description='Выполнить',
        url_path="done",
        variant=ActionVariant.SUCCESS
    )
    def done_action(self, request, object_id):
        obj = Rover.objects.get(pk=object_id)
        obj.done = True
        obj.save()
        return redirect(reverse_lazy('admin:detailing_detailing_changelist'))
