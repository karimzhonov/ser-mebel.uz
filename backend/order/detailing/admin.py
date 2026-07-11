from django.contrib import admin
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from unfold.decorators import action, display
from unfold.enums import ActionVariant

from core.filters import get_date_filter
from core.unfold import ModelAdmin
from core.utils.html import get_boolean_icons, get_folder_link_html

from ..admin_display import order_days_display, order_ref_display, order_status_display
from ..constants import OrderStatus
from .models import Detailing


@admin.register(Detailing)
class DetailingAdmin(ModelAdmin):
    list_display = [
        "order",
        "order_number",
        "order_status",
        "order_days",
        "is_done",
        "square",
        "rover_square",
        "painter_square",
    ]
    list_select_related = ["order__client"]
    actions_submit_line = ["done_action"]
    exclude = ["folder", "done", "order", "working_done"]
    list_filter = [get_date_filter("created_at"), "done"]

    def get_readonly_fields(self, request: HttpRequest, obj=None):
        return ["order_folder_link", "folder_link"]

    @display(description="Выполнен деталировку")
    def is_done(self, obj: Detailing):
        return get_boolean_icons([obj.done])

    @display(description="Файли")
    def folder_link(self, obj: Detailing):
        return get_folder_link_html(obj.folder_id)

    @display(description="Файлы заказа")
    def order_folder_link(self, obj: Detailing):
        return get_folder_link_html(obj.order.folder_id)

    @display(description="Номер заказа")
    def order_number(self, obj: Detailing):
        return order_ref_display(obj.order)

    @display(description="Статус заказа")
    def order_status(self, obj: Detailing):
        return order_status_display(obj.order)

    @display(description="Дней осталось")
    def order_days(self, obj: Detailing):
        return order_days_display(obj.order)

    @action(
        description="Выполнить деталировку",
        url_path="done",
        variant=ActionVariant.SUCCESS,
        permissions=["done_action"],
    )
    def done_action(self, request, obj):
        obj.done = True
        obj.save(update_fields=["done"])
        obj.order.status = OrderStatus.WORKING
        obj.order.save(update_fields=["status"])

    def has_done_action_permission(self, request, object_id: Detailing):
        if not object_id:
            return True
        obj = get_object_or_404(Detailing, pk=object_id)
        return request.user.has_perm("detailing.change_detailing") and not obj.done
