from core.notifications import (
    SMS_ORDER_ASSEMBLY,
    SMS_ORDER_DETAILING,
    SMS_ORDER_INSTALLING,
    SMS_ORDER_WORKING,
)

from .constants import OrderStatus

_STATUS_SMS_TEMPLATES = {
    OrderStatus.DETAILING: SMS_ORDER_DETAILING,
    OrderStatus.WORKING: SMS_ORDER_WORKING,
    OrderStatus.ASSEMBLY: SMS_ORDER_ASSEMBLY,
    OrderStatus.INSTALLING: SMS_ORDER_INSTALLING,
}


def send_order_status_sms(order) -> None:
    template = _STATUS_SMS_TEMPLATES.get(order.status)
    if template is None:
        return
    from oauth.models import User

    context = {"buyurtma_raqami": order.order_number}
    if order.status == OrderStatus.INSTALLING:
        context.update(
            manzil=order.address or "",
            mijoz_tel=order.client_phone() or "",
            sana=order.end_date or "",
            vaqt="",
        )
    User.send_messages(
        OrderStatus.permission(order.status),
        "admin:order_order_change",
        {"object_id": order.pk},
        sms_template=template,
        sms_context=context,
    )


def resolve_order_status_on_save(order) -> None:
    """Derive an Order's status from whether end_date is set.

    A newly created order without an end_date starts out WAITING. It leaves
    WAITING once end_date is set (here, on save) — never via the "Изменить
    статус" button (see OrderStatus.progression_statuses(), which excludes
    WAITING).

    Only demote to WAITING on creation (order._state.adding is True). Blanking
    end_date on an order that already progressed past WAITING/CREATED must not
    silently reset its status and lose that progress — so on saves of an
    already-existing order, a missing end_date is left alone. 
    """
    if order.end_date is None:
        if order._state.adding:
            order.status = OrderStatus.WAITING
    elif order.status == OrderStatus.WAITING:
        order.status = OrderStatus.CREATED


def order_board(*, user, show_price: bool) -> list[dict]:
    """Columns for the "Заказы" kanban on the admin dashboard.

    Each order lands in exactly one column. Statuses map straight across, with one
    exception: WORKING is split by the production work that is still open, so an
    order whose rover is unfinished sits in Ровер, one whose painting is unfinished
    sits in Моляр, and only an order with neither outstanding shows under
    Заказ на сырьё. Rover and painter are optional (Detailing only creates them when
    its squares are non-zero), hence the explicit isnull arms. The two pairs are
    exact complements only because Rover.done / Painter.done are non-nullable.

    Сборка and Установка are narrowed to the viewer's own jobs unless they hold the
    assembly-manager permission — the same scoping AssemblyAdmin.get_queryset applies,
    and what the previous dashboard's StatusBanner did before this board replaced it.
    """
    from django.db.models import F, Q
    from django.urls import reverse

    from core.kanban import IDLE, INFO, OK, WARN, Column, build_board

    from .assembly.constants import ASSEMBLY_MANAGER_PERMISSION
    from .models import Order

    rover_pending = Q(rover__done=False)
    rover_clear = Q(rover__isnull=True) | Q(rover__done=True)
    painter_pending = Q(painter__done=False)
    painter_clear = Q(painter__isnull=True) | Q(painter__done=True)

    assembly = Q(status=OrderStatus.ASSEMBLY)
    installing = Q(status=OrderStatus.INSTALLING)
    if not user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}"):
        own_jobs = Q(assembly__user=user)
        assembly &= own_jobs
        installing &= own_jobs

    changelist = reverse("admin:order_order_changelist")

    def by_status(status):
        return f"{changelist}?status={status}"

    columns = [
        Column("waiting", "Ожидание", "hourglass_empty", IDLE,
               Q(status=OrderStatus.WAITING), more_url=by_status(OrderStatus.WAITING)),
        Column("created", "Создан", "add", INFO,
               Q(status=OrderStatus.CREATED), more_url=by_status(OrderStatus.CREATED)),
        Column("detailing", "Деталировка", "book", INFO,
               Q(status=OrderStatus.DETAILING), more_url=by_status(OrderStatus.DETAILING)),
        # The three WORKING columns link to the matching production list rather than to
        # the order changelist, which has no filter for "rover still open" — hence the
        # explicit labels instead of a row count the link would not match.
        Column("rover", "Ровер", "design_services", WARN,
               Q(status=OrderStatus.WORKING) & rover_pending,
               more_url=reverse("admin:rover_rover_changelist") + "?done=False",
               more_label="Все роверы →"),
        Column("painter", "Моляр", "brush", WARN,
               Q(status=OrderStatus.WORKING) & rover_clear & painter_pending,
               more_url=reverse("admin:painter_painter_changelist") + "?done=False",
               more_label="Все моляры →"),
        Column("working", "Заказ на сырьё", "monitor", WARN,
               Q(status=OrderStatus.WORKING) & rover_clear & painter_clear,
               more_url=by_status(OrderStatus.WORKING),
               more_label="Все в работе →"),
        Column("assembly", "Сборка", "bolt", WARN, assembly,
               more_url=by_status(OrderStatus.ASSEMBLY),
               more_label="Все на сборке →"),
        Column("installing", "Установка", "build", WARN, installing,
               more_url=by_status(OrderStatus.INSTALLING),
               more_label="Все на установке →"),
        Column("done", "Готов", "check", OK,
               Q(status=OrderStatus.DONE), collapsed=True,
               more_url=by_status(OrderStatus.DONE)),
    ]

    # order_number is nullable only while a row is being bootstrapped (see
    # Order.save), but Postgres still sorts NULLs first on DESC — pin them last so a
    # half-written row can't head every column.
    queryset = Order.objects.select_related("client", "factory").order_by(
        F("order_number").desc(nulls_last=True)
    )

    return build_board(
        queryset, columns, lambda order: _order_card(order, show_price=show_price)
    )


def _order_card(order, *, show_price: bool) -> dict:
    from constance import config
    from django.urls import reverse
    from django.utils import timezone

    from .admin_display import order_money_left_display

    days = (order.end_date - timezone.now().date()).days if order.end_date else None

    # Mirrors OrderAdmin.show_days: finished beats everything, then overdue, then the
    # WARNING_ORDER_DAYS window, then plenty of time left.
    if order.status == OrderStatus.DONE:
        pill = ("ok", "Готов")
    elif days is None:
        pill = ("idle", "Нет даты сдачи")
    elif days < 0:
        pill = ("danger", f"Просрочен {abs(days)} дн.")
    elif days <= config.WARNING_ORDER_DAYS:
        pill = ("warn", f"{days} дн.")
    else:
        pill = ("info", f"{days} дн.")

    card = {
        "url": reverse("admin:order_order_change", args=[order.pk]),
        "number": order.order_number,
        "client": str(order.client) if order.client else "—",
        "phone": str(order.client.phone) if order.client else "",
        "address": order.address,
        "desc": (order.desc or "").strip(),
        "factory": order.factory.name,
        "end_date": order.end_date,
        "pill_level": pill[0],
        "pill_text": pill[1],
        # Explicit flag, not a truth test on the amount: Money(0) is falsy, and a
        # fully paid order must still show its total.
        "show_money": show_price and order.price is not None,
    }
    if card["show_money"]:
        card["total"] = order.total_price
        card["left"] = order_money_left_display(order)
    return card
