from typing import Any

from constance import config
from django.contrib import admin
from django.http import HttpRequest
from django.utils.html import format_html
from djmoney import settings as dj_setting
from djmoney.money import Money
from simple_history.admin import SimpleHistoryAdmin
from unfold.decorators import display

from accounting.inlines import ExposeInline
from core.filters import get_date_filter
from core.unfold import ModelAdmin
from core.utils import get_boolean_icons, get_folder_link_html, get_tag
from core.utils.admin import not_add_permission_in_admin

from .actions import OrderActions
from .components import *
from .constants import ORDER_VIEW_PRICE_PERMISSION
from .filters import OrderStatusDropdownFilter, OrderWarningDropdownFilter
from .forms import OrderAddForm
from .models import Order, OrderStatus


@admin.register(Order)
class OrderAdmin(OrderActions, SimpleHistoryAdmin, ModelAdmin):
    list_display = [
        "order_number",
        "client",
        "client_phone",
        "address",
        "show_status",
        "reception_date",
        "end_date",
        "show_total_price",
        "lost_money",
        "show_lost_money",
        "show_days",
    ]
    list_display_links = ["order_number", "client"]
    list_select_related = ["client"]
    ordering = ["-order_number"]
    autocomplete_fields = ["client"]
    list_filter = [
        OrderStatusDropdownFilter,
        OrderWarningDropdownFilter,
        get_date_filter("reception_date"),
    ]
    list_filter_submit = True
    search_fields = ["metering__client__fio", "metering__client__phone"]

    class Media:
        css = {"all": ["order/css/order_admin.css"]}

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, str]:
        initial = super().get_changeform_initial_data(request)
        try:
            price = request.GET.get("price")
            if price:
                amount, currency = price.split(":")
                initial["price"] = Money(amount, currency)
            else:
                initial["price"] = Money(amount=0, currency=dj_setting.DEFAULT_CURRENCY)
        except Exception:
            pass
        return initial

    def has_add_permission(self, request: HttpRequest) -> bool:
        return not_add_permission_in_admin(request)

    def get_inlines(self, request: HttpRequest, obj: Any | None):
        return [ExposeInline] if obj else []

    def get_readonly_fields(
        self, request: HttpRequest, obj: Any | None = ...
    ) -> list[str] | tuple[Any, ...]:
        # end_date is intentionally NOT readonly here: per decision (a), end_date is
        # no longer derived at creation time and is set later on an existing order —
        # this is the only place an order can leave the WAITING status (see
        # order/services.py resolve_order_status_on_save).
        return (
            [
                "show_status",
                "show_days",
                "folder_link",
                "metering",
                "client",
                "reception_date",
                "address",
                "address_link",
                "show_total_price",
                "rover",
                "rover_done",
                "painter",
                "painter_done",
                "assembly",
                "assembly_done",
            ]
            if obj
            else []
        )

    def get_fieldsets(self, request: HttpRequest, obj=None):
        fieldsets = [
            (
                "Инфо",
                {
                    "fields": ("order_number", "show_status", "show_days"),
                    "classes": ("tab-info",),
                },
            ),
            (
                "Заказ",
                {
                    "fields": ("client", "desc", "reception_date", "end_date", "folder_link"),
                    "classes": ("tab-info",),
                },
            ),
            ("Адрес", {"fields": ("address", "address_link"), "classes": ("tab-info",)}),
            (
                "Производство",
                {
                    "fields": (
                        "rover",
                        "rover_done",
                        "painter",
                        "painter_done",
                        "assembly",
                        "assembly_done",
                    ),
                    "classes": ("tab-info",),
                },
            ),
        ]
        add_fieldsets = [
            (
                "Заказ",
                {
                    "fields": (
                        "client",
                        "desc",
                        "reception_date",
                        "count_days",
                        "design_type",
                        "metering",
                    )
                },
            ),
            ("Адрес", {"fields": ("address", "address_link")}),
            ("Цена", {"fields": ("price", "lost_money", "discount")}),
        ]
        if request.user.has_perm(f"order.{ORDER_VIEW_PRICE_PERMISSION}"):
            fieldsets.append(
                (
                    "Цена",
                    {
                        "fields": ("price", "lost_money", "discount", "show_total_price"),
                        "classes": ("tab-info",),
                    },
                ),
            )
        return add_fieldsets if not obj else fieldsets

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = OrderAddForm
        return super().get_form(request, obj, **kwargs)

    @display(
        description="Статус",
    )
    def show_status(self, obj: Order):
        return get_tag(OrderStatus(obj.status).label, OrderStatus.get_sev(obj.status))

    @display(
        description="Дней осталось",
    )
    def show_days(self, obj: Order, days_minus=0):
        if obj.status == OrderStatus.DONE:
            return get_tag("Заказ готов", "success")
        if obj.status == OrderStatus.WAITING or obj.days is None:
            return get_tag("Ожидание даты сдачи", "secondary")
        days = obj.days - days_minus
        if days >= 0:
            tag = get_tag(
                f"До сдачи заказа {days} дней",
                "secondary" if days > config.WARNING_ORDER_DAYS else "warning",
            )
            return (
                format_html('<span class="order-row-warning">{}</span>', tag)
                if days <= config.WARNING_ORDER_DAYS
                else tag
            )
        return format_html(
            '<span class="order-row-warning">{}</span>',
            get_tag(f"Заказ просрочен на {abs(days)} дней", "danger"),
        )

    # Filer links
    @display(
        description="Файлы",
    )
    def folder_link(self, obj: Order):
        return get_folder_link_html(obj.folder_id)

    @display(
        description="Итого",
    )
    def show_total_price(self, obj: Order):
        return obj.total_price

    @display(
        description="Ровер выполнен",
    )
    def rover_done(self, obj: Order):
        return get_boolean_icons([obj.rover.done]) if obj.rover else "-"

    @display(
        description="Моляр выполнен",
    )
    def painter_done(self, obj: Order):
        return get_boolean_icons([obj.painter.done]) if obj.painter else "-"

    @display(
        description="Сборка/Установка выполнен",
    )
    def assembly_done(self, obj: Order):
        return get_boolean_icons([obj.assembly.done]) if obj.assembly else "-"

    @display(description="Остаток денег")
    def show_lost_money(self, obj: Order):
        return obj.other_money
