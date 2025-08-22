from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from unfold.enums import ActionVariant
from unfold.admin import ModelAdmin
from unfold.decorators import action, display
from core.utils.html import get_boolean_icons, get_folder_link_html
from .models import Detailing
from ..constants import OrderStatus


@admin.register(Detailing)
class DetailingAdmin(ModelAdmin):
    list_display = ['order', 'is_done', 'is_working_done']
    actions_detail = ['done_action', 'working_done_action']
    readonly_fields = ['order_folder_link', 'folder_link']
    exclude = ['folder', 'done', 'working_done', 'order']

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
    
    def get_actions_detail(self, request, object_id: int):
        obj = Detailing.objects.get(pk=object_id)
        if not obj.done:
            return [self.get_unfold_action('done_action')]
        return [] if obj.working_done else [self.get_unfold_action('working_done_action')]

    @action(
        description='Выполнить деталировку',
        url_path="done",
        variant=ActionVariant.SUCCESS
    )
    def done_action(self, request, object_id):
        obj = Detailing.objects.get(pk=object_id)
        obj.done = True
        obj.save(update_fields=['done'])
        obj.order.status = OrderStatus.WORKING
        obj.order.save(update_fields=['status'])
        return redirect(reverse_lazy('admin:detailing_detailing_changelist'))

    @action(
        description='Выполнить заказ на сырье',
        url_path="working-done",
        variant=ActionVariant.SUCCESS
    )
    def working_done_action(self, request, object_id):
        obj = Detailing.objects.get(pk=object_id)
        obj.working_done = True
        obj.save(update_fields=['working_done'])
        obj.order.status = OrderStatus.ASSEMBLY
        obj.order.save(update_fields=['status'])
        return redirect(reverse_lazy('admin:detailing_detailing_changelist'))
