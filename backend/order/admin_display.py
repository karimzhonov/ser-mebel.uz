"""Presentation-only helpers for showing an Order's reference/status/days
remaining on admins that relate to Order either directly (OneToOne, e.g.
Detailing/Rover/Painter/Assembly) or indirectly through Metering (Price/Design).

Not business logic — no writes happen here. Mirrors OrderAdmin.show_status /
OrderAdmin.show_days (order/admin.py) but computes "days remaining" from
end_date directly instead of relying on the `days` annotation that
OrderManager.get_queryset() adds (order/managers.py) — that annotation is only
present when Order is queried directly through Order.objects, not when it's
reached via select_related() from another model's queryset.
"""

from constance import config
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from core.utils import get_tag

from .models import Order, OrderStatus


def order_ref_display(order):
    """Link to the Order admin change page, labeled with its order_number."""
    if order is None:
        return "-"
    url = reverse("admin:order_order_change", args=[order.pk])
    return format_html('<a class="text-blue-700" href="{}">{}</a>', url, order.order_number)


def order_status_display(order):
    """Mirrors OrderAdmin.show_status."""
    if order is None:
        return "-"
    return get_tag(OrderStatus(order.status).label, OrderStatus.get_sev(order.status))


def order_days_display(order):
    """Mirrors OrderAdmin.show_days, computed from end_date instead of the
    `days` annotation (see module docstring)."""
    if order is None:
        return "-"
    if order.status == OrderStatus.DONE:
        return get_tag("Заказ готов", "success")
    if order.status == OrderStatus.WAITING or order.end_date is None:
        return get_tag("Ожидание даты сдачи", "secondary")
    # timezone.localdate() assumes an aware "now" and this project runs with
    # USE_TZ=False (core/settings.py) — timezone.now().date() mirrors what
    # OrderManager's ExtractDay(end_date - Now()) computes without requiring
    # an aware datetime.
    days = (order.end_date - timezone.now().date()).days
    # Same .order-row-danger / .order-row-warning markers OrderAdmin.show_days emits —
    # order/css/order_admin.css colours the whole changelist row off them, so any admin
    # that shows this column must also pull that stylesheet in via its Media class.
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
    return get_tag(f"До сдачи заказа {days} дней", "secondary")


def order_money_left_display(order):
    """Mirrors OrderAdmin.show_lost_money ("Остаток денег") — how much of the order
    is still unpaid.

    Order.other_money assumes price and lost_money are both set and both in the same
    currency. Neither is guaranteed — price and lost_money are independently nullable
    MoneyFields with their own currency columns — and a Money minus None (or minus a
    Money in another currency) raises. Since this runs as a list_display callable, one
    bad row would take down the whole changelist, so both gaps return "-" instead."""
    if order is None or order.price is None:
        return "-"
    total = order.total_price
    if order.lost_money is None:
        return total
    if total.currency != order.lost_money.currency:
        return "-"
    return total - order.lost_money


def order_for_metering(metering):
    """Return the Order linked to a Metering via the reverse OneToOne
    (Order.metering), or None. Accessing metering.order on a metering with no
    linked order raises Order.DoesNotExist (RelatedObjectDoesNotExist), not
    AttributeError, so a plain getattr(..., default) won't catch it."""
    if metering is None:
        return None
    try:
        return metering.order
    except Order.DoesNotExist:
        return None
