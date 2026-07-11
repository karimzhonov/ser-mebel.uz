from django.contrib import admin
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from unfold.decorators import action, display
from unfold.enums import ActionVariant

from core.filters import get_date_filter
from core.unfold import ModelAdmin
from core.utils.html import get_boolean_icons, get_folder_link_html
from order.admin_display import order_days_display, order_ref_display, order_status_display
from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION

from .components import *
from .models import Painter, PainterType


@admin.register(PainterType)
class PainterTypeAdmin(ModelAdmin):
    list_display = ["name", "price"]


@admin.register(Painter)
class PainterAdmin(ModelAdmin):
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
    readonly_fields = ["folder_link", "order_folder_link", "square", "price"]
    actions_detail = ["done_action"]
    list_filter = [get_date_filter("created_at"), "done"]
    list_filter_submit = True

    def get_queryset(self, request):
        if request.user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}"):
            return super().get_queryset(request)
        return super().get_queryset(request).filter(type__user=request.user)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: None = None) -> bool:
        return request.user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")

    @display(description="Выполнен")
    def is_done(self, obj: Painter):
        return get_boolean_icons([obj.done])

    @display(description="Файлы")
    def folder_link(self, obj: Painter):
        return get_folder_link_html(obj.folder_id)

    @display(description="Файлы заказа")
    def order_folder_link(self, obj: Painter):
        return get_folder_link_html(obj.order.folder_id)

    @display(description="Номер заказа")
    def order_number(self, obj: Painter):
        return order_ref_display(obj.order)

    @display(description="Статус заказа")
    def order_status(self, obj: Painter):
        return order_status_display(obj.order)

    @display(description="Дней осталось")
    def order_days(self, obj: Painter):
        return order_days_display(obj.order)

    def get_actions_detail(self, request, object_id: int):
        obj = Painter.objects.get(pk=object_id)
        return [] if obj.done else [self.get_unfold_action("done_action")]

    @action(
        description="Выполнить",
        url_path="done",
        variant=ActionVariant.SUCCESS,
        permissions=["done_action"],
    )
    def done_action(self, request, object_id):
        obj = Painter.objects.get(pk=object_id)
        obj.done = True
        obj.save()
        return redirect(reverse_lazy("admin:painter_painter_changelist"))

    def has_done_action_permission(self, request, object_id: Painter):
        obj = get_object_or_404(Painter, pk=object_id)
        return request.user.has_perm("painter.change_painter") and not obj.done

    def save_model(self, request, obj, form, change):
        update_fields = []

        # True if something changed in model
        # Note that change is False at the very first time
        if change:
            if form.initial["type"] != form.cleaned_data["type"]:
                update_fields.append("type")

        obj.save(update_fields=update_fields)
