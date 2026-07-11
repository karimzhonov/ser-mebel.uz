from django.contrib import admin
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from unfold.decorators import action, display
from unfold.enums import ActionVariant

from core.filters import get_date_filter
from core.unfold import ModelAdmin
from core.utils.html import get_boolean_icons, get_folder_link_html

from ..admin_display import order_days_display, order_ref_display, order_status_display
from .components import *
from .models import Rover


@admin.register(Rover)
class RoverAdmin(ModelAdmin):
    list_display = [
        "order",
        "order_number",
        "order_status",
        "order_days",
        "is_done",
        "square",
        "price",
    ]
    list_select_related = ["order__client"]
    exclude = ["folder", "done", "order"]
    readonly_fields = ["square", "price", "order_folder_link", "folder_link"]
    actions_detail = ["done_action"]
    list_filter = [get_date_filter("created_at"), "done"]
    list_filter_submit = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        return False

    @display(description="Выполнен")
    def is_done(self, obj: Rover):
        return get_boolean_icons([obj.done])

    @display(description="Файлы")
    def folder_link(self, obj: Rover):
        return get_folder_link_html(obj.folder_id)

    @display(description="Файлы заказа")
    def order_folder_link(self, obj: Rover):
        return get_folder_link_html(obj.order.folder_id)

    @display(description="Номер заказа")
    def order_number(self, obj: Rover):
        return order_ref_display(obj.order)

    @display(description="Статус заказа")
    def order_status(self, obj: Rover):
        return order_status_display(obj.order)

    @display(description="Дней осталось")
    def order_days(self, obj: Rover):
        return order_days_display(obj.order)

    @action(
        description="Выполнить",
        url_path="done",
        variant=ActionVariant.SUCCESS,
        permissions=["done_action"],
    )
    def done_action(self, request, object_id):
        obj = Rover.objects.get(pk=object_id)
        obj.done = True
        obj.save()
        return redirect(reverse_lazy("admin:rover_rover_changelist", query={"done": False}))

    def has_done_action_permission(self, request, object_id: Rover):
        obj = get_object_or_404(Rover, pk=object_id)
        return request.user.has_perm("rover.change_rover") and not obj.done
