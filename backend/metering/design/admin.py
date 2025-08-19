from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.http import urlencode
from django.utils import timezone
from django.http import HttpRequest
from unfold.admin import ModelAdmin
from unfold.dataclasses import ActionVariant, UnfoldAction
from unfold.decorators import action, display
from simple_history.admin import SimpleHistoryAdmin
from core.utils.html import get_boolean_icons
from .models import Design
from .inlines import DesignTypeInline


@admin.register(Design)
class DesignAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = ['metering', 'is_done']
    actions_detail = ['create_order', 'done_action']
    inlines = [DesignTypeInline]
    readonly_fields = ['metering']
    exclude = ['done']
    
    @display(description='Выполнен')
    def is_done(self, obj: Design):
        return get_boolean_icons([obj.done])

    def get_actions_detail(self, request: HttpRequest, object_id: int) -> list[UnfoldAction]:
        obj = Design.objects.get(pk=object_id)
        action_name = 'create_order' if obj.done else 'done_action'
        return [] if hasattr(obj.metering, 'order') and obj.metering.order else [self.get_unfold_action(action_name)]
    
    @action(
        description='Создать заказ',
        url_path="create-order",
        variant=ActionVariant.PRIMARY
    )
    def create_order(self, request, object_id: int):
        obj = Design.objects.get(pk=object_id)
        url = reverse_lazy("admin:order_order_add")
        params = urlencode({
            "client": obj.metering.client_id or '',
            "address": obj.metering.address or '',
            "address_link": obj.metering.address_link or '',
            "reception_date": timezone.now().date().strftime('%d.%m.%Y'),
            "metering": obj.metering.pk
        })
        return redirect(f'{url}?{params}')

    @action(
        description='Выполнить дизайн',
        url_path="done",
        variant=ActionVariant.SUCCESS
    )
    def done_action(self, request, object_id):
        Design.objects.filter(pk=object_id).update(
            done=True
        )
        return redirect(reverse_lazy('admin:design_design_changelist'))
