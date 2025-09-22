from collections.abc import Sequence
from django.contrib import admin
from django.db.models.query import QuerySet
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.http import HttpRequest
from core.unfold import ModelAdmin
from unfold.enums import ActionVariant
from unfold.decorators import display, action
from core.utils.html import get_boolean_icons, get_folder_link_html
from core.filters import get_date_filter
from ..constants import OrderStatus
from .models import Assembly
from .constants import ASSEMBLY_MANAGER_PERMISSION


@admin.register(Assembly)
class AssemblyAdmin(ModelAdmin):
    list_display = ['order', 'user', 'is_done', 'is_installing_done', 'square', 'price']
    exclude = ['folder', 'done', 'installing_done', 'order']
    readonly_fields = ['folder_link', 'order_folder_link', 'square', 'price']
    actions_detail = ['done_action', 'installing_done_action']
    list_filter = [get_date_filter('created_at'), 'done']

    def get_list_filter(self, request: HttpRequest) -> Sequence[str]:
        if request.user.has_perm(f'assembly.{ASSEMBLY_MANAGER_PERMISSION}'):
            return [get_date_filter('created_at'), 'done', 'user']
        return super().get_list_filter(request)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
    
    def get_exclude(self, request: HttpRequest, obj = None):
        if not request.user.has_perm(f'assembly.{ASSEMBLY_MANAGER_PERMISSION}'):
            return ['folder', 'done', 'installing_done', 'order', 'user']
        return super().get_exclude(request, obj)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Assembly]:
        qs = super().get_queryset(request)
        if not request.user.has_perm(f'assembly.{ASSEMBLY_MANAGER_PERMISSION}'):
            return qs.filter(
                user=request.user
            )
        return qs

    @display(description='Выполнен сборка')
    def is_done(self, obj: Assembly):
        return get_boolean_icons([obj.done])
    
    @display(description='Выполнен установка')
    def is_installing_done(self, obj: Assembly):
        return get_boolean_icons([obj.installing_done])
    
    @display(description='Файли')
    def folder_link(self, obj: Assembly):
        return get_folder_link_html(obj.folder_id)
    
    @display(description='Файлы заказа')
    def order_folder_link(self, obj: Assembly):
        return get_folder_link_html(obj.order.folder_id) 

    @action(
        description='Выполнить сборку',
        url_path="done",
        variant=ActionVariant.SUCCESS,
        permissions=['done_action']
    )
    def done_action(self, request, object_id):
        obj = Assembly.objects.get(pk=object_id)
        obj.done = True
        obj.save(update_fields=['done'])
        obj.order.status = OrderStatus.INSTALLING
        obj.order.save(update_fields=['status'])
        return redirect(reverse_lazy('admin:assembly_assembly_changelist', query={'installing_done': False}))
    
    def has_done_action_permission(self, request, object_id):
        obj = get_object_or_404(Assembly, pk=object_id)
        return request.user.has_perm('assembly.change_assembly') and not obj.done
    
    @action(
        description='Выполнить установку',
        url_path="installing-done",
        variant=ActionVariant.SUCCESS, 
        permissions=['installing_done_action']
    )
    def installing_done_action(self, request, object_id):
        obj = Assembly.objects.get(pk=object_id)
        obj.installing_done = True
        obj.save(update_fields=['installing_done'])
        obj.order.status = OrderStatus.DONE
        obj.order.save(update_fields=['status'])
        return redirect(reverse_lazy('admin:assembly_assembly_changelist', query={'installing_done': True}))

    def has_installing_done_action_permission(self, request, object_id):
        obj = get_object_or_404(Assembly, pk=object_id)
        return request.user.has_perm('assembly.change_assembly') and obj.done and not obj.installing_done
