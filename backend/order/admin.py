from typing import Any

from constance import config
from django.contrib import admin
from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import Truncator
from djmoney import settings as dj_setting
from djmoney.money import Money
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin as UnfoldModelAdmin
from unfold.contrib.filters.admin import RelatedDropdownFilter
from unfold.decorators import display

from accounting.inlines import ExposeInline
from core.filters import get_date_filter
from core.unfold import ModelAdmin
from core.utils import get_boolean_icons, get_folder_link_html, get_tag
from core.utils.admin import not_add_permission_in_admin

from .actions import OrderActions
from .admin_display import order_money_left_display
from .components import *
from .constants import DEFAULT_FACTORY_NAME, ORDER_VIEW_PRICE_PERMISSION
from .filters import OrderStatusDropdownFilter, OrderWarningDropdownFilter
from .forms import OrderAddForm
from .models import Factory, Order, OrderStatus


@admin.register(Factory)
class FactoryAdmin(UnfoldModelAdmin):
    # Deliberately NOT core.unfold.ModelAdmin: that base hides the "Add" button on
    # changelist/change views, and factories are a plain reference table that has to
    # be creatable straight from its own list.
    list_display = ["name", "address", "phone", "ordering"]
    search_fields = ["name", "phone"]
    ordering = ["ordering", "name"]


@admin.register(Order)
class OrderAdmin(OrderActions, SimpleHistoryAdmin, ModelAdmin):
    list_display = [
        "order_number",
        "client",
        "client_phone",
        "factory",
        "address",
        "show_desc",
        "show_status",
        "reception_date",
        "end_date",
        "show_total_price",
        "lost_money",
        "show_lost_money",
        "show_days",
    ]
    list_display_links = ["order_number", "client"]
    list_select_related = ["client", "factory"]
    ordering = ["-order_number"]
    autocomplete_fields = ["client"]
    list_filter = [
        OrderStatusDropdownFilter,
        OrderWarningDropdownFilter,
        ("factory", RelatedDropdownFilter),
        get_date_filter("reception_date"),
    ]
    list_filter_submit = True
    search_fields = ["metering__client__fio", "metering__client__phone"]

    class Media:
        css = {"all": ["order/css/order_admin.css"]}

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, Any]:
        initial = super().get_changeform_initial_data(request)
        # An order is always received "today" — overriding whatever reception_date the
        # referring page put in the query string (DesignAdmin.create_order used to pass
        # the metering date). USE_TZ=False here, so now().date() is the local date.
        initial["reception_date"] = timezone.now().date()
        if "factory" not in initial:
            default_factory = Factory.objects.filter(name=DEFAULT_FACTORY_NAME).first()
            if default_factory:
                initial["factory"] = default_factory.pk
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
                # "reception_date",
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
                    "fields": (
                        "client",
                        "factory",
                        "desc",
                        "reception_date",
                        "end_date",
                        "folder_link",
                    ),
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
                        "factory",
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
        # The marker spans below are what order/css/order_admin.css keys the whole
        # changelist row off, in this precedence: .order-row-done = finished (green),
        # .order-row-danger = overdue (red), .order-row-warning = deadline within
        # WARNING_ORDER_DAYS (orange), .order-row-progress = in production with time
        # to spare (blue). A deadline colour deliberately beats the plain "in
        # progress" blue — every late order is also in progress. WAITING has no end
        # date yet, so it stays uncoloured.
        if obj.status == OrderStatus.DONE:
            return format_html(
                '<span class="order-row-done">{}</span>', get_tag("Заказ готов", "success")
            )
        if obj.status == OrderStatus.WAITING or obj.days is None:
            return get_tag("Ожидание даты сдачи", "secondary")
        days = obj.days - days_minus
        if days < 0:
            return format_html(
                '<span class="order-row-danger">{}</span>',
                get_tag(f"Заказ просрочен на {abs(days)} дней", "danger"),
            )
        if days <= config.WARNING_ORDER_DAYS:
            return format_html(
                '<span class="order-row-warning">{}</span>',
                get_tag(f"До сдачи заказа {days} дней", "warning"),
            )
        return format_html(
            '<span class="order-row-progress">{}</span>',
            get_tag(f"До сдачи заказа {days} дней", "secondary"),
        )

    @display(
        description="Описание",
    )
    def show_desc(self, obj: Order):
        if not obj.desc:
            return "-"
        text = obj.desc.strip()
        short = Truncator(text).chars(60)
        if short == text:
            return text
        return format_html('<span title="{}">{}</span>', text, short)

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
        # Reverse OneToOne: attribute access raises when the row is missing, so it
        # cannot be used as its own truth test.
        rover = getattr(obj, "rover", None)
        return get_boolean_icons([rover.done]) if rover else "-"

    @display(
        description="Моляр выполнен",
    )
    def painter_done(self, obj: Order):
        painter = getattr(obj, "painter", None)
        return get_boolean_icons([painter.done]) if painter else "-"

    @display(
        description="Сборка/Установка выполнен",
    )
    def assembly_done(self, obj: Order):
        assembly = getattr(obj, "assembly", None)
        return get_boolean_icons([assembly.done]) if assembly else "-"

    @display(description="Остаток денег")
    def show_lost_money(self, obj: Order):
        # Shared with MeteringAdmin.order_money_left; Order.other_money itself raises
        # on a null or foreign-currency lost_money.
        return order_money_left_display(obj)
