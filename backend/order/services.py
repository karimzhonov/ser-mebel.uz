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


def order_board(*, user, show_price: bool, to_card=None) -> list[dict]:
    """Columns for the "Заказы" kanban on the admin dashboard.

    Each order lands in exactly one column. Statuses map straight across, with one
    exception: WORKING is split by the production work that is still open, so an
    order whose rover is unfinished sits in Ровер, one whose painting is unfinished
    sits in Моляр, and only an order with neither outstanding shows under
    Заказ на сырьё. Rover and painter are optional (Detailing only creates them when
    its squares are non-zero), hence the explicit isnull arms. The two pairs are
    exact complements only because Rover.done / Painter.done are non-nullable.

    Сборка, Установка and Моляр are narrowed to the viewer's own jobs unless they
    hold the assembly-manager permission, matching AssemblyAdmin.get_queryset and
    PainterAdmin.get_queryset. Ровер is deliberately not narrowed: RoverAdmin has no
    per-user scoping, so neither does its column.

    Narrowing the WORKING arms this way breaks the exact-partition property for a
    scoped viewer — an order being painted by someone else shows in no column rather
    than in Моляр. That is intended: the alternative is showing that viewer a row the
    matching changelist would refuse them.
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
    painter_column = Q(status=OrderStatus.WORKING) & rover_clear & painter_pending
    if not user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}"):
        own_jobs = Q(assembly__user=user)
        assembly &= own_jobs
        installing &= own_jobs
        # PainterAdmin.get_queryset scopes by the painter type's user, not by the
        # painter row — a painter is assigned work through PainterType.
        painter_column &= Q(painter__type__user=user)

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
        Column("painter", "Моляр", "brush", WARN, painter_column,
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
        queryset,
        columns,
        to_card or (lambda order: _order_card(order, show_price=show_price)),
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


# --- Write services (used by the REST API; mirror OrderAddForm / OrderActions) ---


def create_order(*, count_days=None, **fields):
    """Mirrors OrderAddForm.save + OrderAdmin.get_changeform_initial_data.

    - end_date = reception_date + count_days when count_days is given (else the order
      starts WAITING, see resolve_order_status_on_save);
    - the linked metering becomes "Сотилди", and so does its call-centre invoice;
    - factory defaults to DEFAULT_FACTORY_NAME.
    """
    from datetime import timedelta

    from django.db import transaction
    from django.utils import timezone

    from call_center.constants import SolutionChoice
    from core.exceptions import ServiceError
    from metering.constants import MeteringStatus

    from .constants import DEFAULT_FACTORY_NAME
    from .models import Factory, Order

    metering = fields.get("metering")
    design_type = fields.get("design_type")
    if metering is not None:
        if Order.objects.filter(metering=metering).exists():
            raise ServiceError("Бу замер учун заказ аллақачон яратилган")
        # Reverse OneToOne: getattr with a default swallows RelatedObjectDoesNotExist.
        design = getattr(metering, "design", None)
        if metering.status == MeteringStatus.dont_need:
            raise ServiceError("Замер бекор қилинган — заказ яратиб бўлмайди")
        if design is None or not design.done:
            raise ServiceError("Дизайн ҳали тайёр эмас — аввал дизайнни бажаринг")
        if design_type is None or design_type.design_id != design.pk:
            raise ServiceError("Шу замер дизайнидан вариант танланг")
        fields.setdefault("client", metering.client)

    fields.setdefault("reception_date", timezone.now().date())
    if fields.get("factory") is None:
        factory = Factory.objects.filter(name=DEFAULT_FACTORY_NAME).first()
        if factory is None:
            raise ServiceError("Завод танланг")
        fields["factory"] = factory
    if count_days:
        fields["end_date"] = fields["reception_date"] + timedelta(days=int(count_days))

    with transaction.atomic():
        if metering is not None:
            metering.status = MeteringStatus.sold_out
            metering.save()
            if metering.invoice:
                metering.invoice.solution = SolutionChoice.sold_out
                metering.invoice.save()
        order = Order(**fields)
        order.save()
    return order


def send_order_to_detailing(order):
    """Mirrors OrderActions.detailing_action."""
    from core.exceptions import ServiceError

    from .detailing.models import Detailing

    if order.status != OrderStatus.CREATED:
        raise ServiceError("Деталировкага фақат «Создан» статусидаги заказ юборилади")
    from django.db import transaction

    with transaction.atomic():
        Detailing.objects.get_or_create(order=order)
        order.change_status(OrderStatus.DETAILING)
    return order


def advance_order_status(order):
    """Mirrors OrderActions.change_status: one step along progression_statuses()."""
    from core.exceptions import ServiceError

    next_status = OrderStatus.next_status(order.status)
    if next_status is None:
        raise ServiceError(
            f"Невозможно изменить статус: «{OrderStatus(order.status).label}» — финальный."
        )
    order.change_status(next_status)
    return order


def send_order_to_assembly(order):
    """Mirrors OrderActions.go_to_assembly_action. Returns the Assembly row."""
    from core.exceptions import ServiceError

    from .assembly.models import Assembly

    if order.status != OrderStatus.WORKING:
        raise ServiceError("Сборкага фақат «Заказ на сырье» статусидаги заказ юборилади")
    assembly = Assembly.objects.filter(order=order).first()
    if assembly is None:
        raise ServiceError("Сборка для этого заказа не создана — укажите площадь в деталировке.")
    order.change_status(OrderStatus.ASSEMBLY)
    return assembly
