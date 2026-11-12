from core.geo import UNSET
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
    extra = {}
    if order.status == OrderStatus.ASSEMBLY:
        # the Telegram cards (assembly.ready / assembly.task) replace the bare message;
        # the SMS stays only for staff who have no Telegram
        extra = {"telegram": False, "sms_only_without_telegram": True}
    User.send_messages(
        OrderStatus.permission(order.status),
        "admin:order_order_change",
        {"object_id": order.pk},
        sms_template=template,
        sms_context=context,
        **extra,
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
    from django.db.models import Exists, F, OuterRef, Q
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
    # assembly managers and the production head (who now runs these stages) see all jobs
    if not can_send_to_assembly(user):
        own_jobs = Q(assembly__user=user)
        assembly &= own_jobs
        installing &= own_jobs
        # a painter is assigned work through the job's parts (one per team)
        from .painter.models import PainterPart

        painter_column &= Exists(
            PainterPart.objects.filter(painter__order=OuterRef("pk"), type__user=user)
        )

    changelist = reverse("admin:order_order_changelist")

    def by_status(status):
        return f"{changelist}?status={status}"

    columns = [
        Column(
            "waiting",
            "Ожидание",
            "hourglass_empty",
            IDLE,
            Q(status=OrderStatus.WAITING),
            more_url=by_status(OrderStatus.WAITING),
        ),
        Column(
            "created",
            "Создан",
            "add",
            INFO,
            Q(status=OrderStatus.CREATED),
            more_url=by_status(OrderStatus.CREATED),
        ),
        Column(
            "detailing",
            "Деталировка",
            "book",
            INFO,
            Q(status=OrderStatus.DETAILING),
            more_url=by_status(OrderStatus.DETAILING),
        ),
        # The three WORKING columns link to the matching production list rather than to
        # the order changelist, which has no filter for "rover still open" — hence the
        # explicit labels instead of a row count the link would not match.
        Column(
            "rover",
            "Ровер",
            "design_services",
            WARN,
            Q(status=OrderStatus.WORKING) & rover_pending,
            more_url=reverse("admin:rover_rover_changelist") + "?done=False",
            more_label="Все роверы →",
        ),
        Column(
            "painter",
            "Моляр",
            "brush",
            WARN,
            painter_column,
            more_url=reverse("admin:painter_painter_changelist") + "?done=False",
            more_label="Все моляры →",
        ),
        Column(
            "working",
            "Заказ на сырьё",
            "monitor",
            WARN,
            Q(status=OrderStatus.WORKING) & rover_clear & painter_clear,
            more_url=by_status(OrderStatus.WORKING),
            more_label="Все в работе →",
        ),
        Column(
            "assembly",
            "Сборка",
            "bolt",
            WARN,
            assembly,
            more_url=by_status(OrderStatus.ASSEMBLY),
            more_label="Все на сборке →",
        ),
        Column(
            "installing",
            "Установка",
            "build",
            WARN,
            installing,
            more_url=by_status(OrderStatus.INSTALLING),
            more_label="Все на установке →",
        ),
        Column(
            "done",
            "Готов",
            "check",
            OK,
            Q(status=OrderStatus.DONE),
            collapsed=True,
            more_url=by_status(OrderStatus.DONE),
        ),
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


def create_order(*, count_days=None, author=None, **fields):
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
    from core.geo import make_point
    from metering.constants import ClientResult, MeteringStatus, OfferStage

    from .constants import DEFAULT_FACTORY_NAME
    from .models import Factory, Order

    metering = fields.get("metering")
    design_type = fields.get("design_type")
    if metering is not None:
        if Order.objects.filter(metering=metering).exists():
            raise ServiceError("Bu o'lchov uchun buyurtma allaqachon yaratilgan")
        # Reverse OneToOne: getattr with a default swallows RelatedObjectDoesNotExist.
        design = getattr(metering, "design", None)
        # owner's rule: the admin turns old clients from the «Narx hisoblash» archive into
        # orders — no design / answer checks; a variant, when picked, must be this design's
        admin = author is not None and author.is_superuser
        if admin:
            if design_type is not None and (design is None or design_type.design_id != design.pk):
                raise ServiceError("Shu o'lchov dizaynidan variant tanlang")
        elif metering.status == MeteringStatus.dont_need:
            raise ServiceError("O'lchov bekor qilingan — buyurtma yaratib bo'lmaydi")
        elif metering.client_result in (
            ClientResult.design_declined,
            ClientResult.price_declined,
        ):
            raise ServiceError("Mijoz rad etgan — buyurtma yaratib bo'lmaydi")
        if admin:
            pass
        elif design is None and metering.next_step == "price" and design_type is None:
            pass  # «Faqat narx»: the client wants no design
        else:
            if design is None or not design.done:
                raise ServiceError("Dizayn hali tayyor emas — avval dizaynni bajaring")
            if design.stage != OfferStage.approved:
                raise ServiceError("Dizayn mijoz tomonidan tasdiqlanmagan")
            if design_type is None or design_type.design_id != design.pk:
                raise ServiceError("Shu o'lchov dizaynidan variant tanlang")
        if not admin:
            # owner's rule: the order is made only after the client agreed to the price
            price = getattr(metering, "price", None)
            if price is None or price.stage != OfferStage.approved:
                raise ServiceError("Mijoz narxga rozi bo'lmagan — avval narx javobini yozing")
        fields.setdefault("client", metering.client)

    # location: this call's own, else the metering's (point, pasted link, address)
    if "lat" in fields or "lon" in fields:
        lat, lon = fields.get("lat"), fields.get("lon")
        point = make_point(lat, lon) if lat is not None or lon is not None else None
        if (lat is not None or lon is not None) and point is None:
            raise ServiceError("Lokatsiya koordinatalari noto'g'ri")
        fields["lat"], fields["lon"] = (point.lat, point.lon) if point else (None, None)
    if metering is not None and fields.get("lat") is None and not fields.get("address_link"):
        fields["lat"], fields["lon"] = metering.lat, metering.lon
        fields["address_link"] = metering.address_link
    fields["address"] = (fields.get("address") or "").strip()
    if metering is not None and not fields["address"]:
        fields["address"] = (metering.address or "").strip()[:255]
    if not fields["address"] and fields.get("lat") is None:
        raise ServiceError("Manzilni kiriting yoki xaritadan nuqta qo'shing")

    fields.setdefault("reception_date", timezone.now().date())
    if fields.get("factory") is None:
        factory = Factory.objects.filter(name=DEFAULT_FACTORY_NAME).first()
        if factory is None:
            raise ServiceError("Zavodni tanlang")
        fields["factory"] = factory
    if count_days:
        fields["end_date"] = fields["reception_date"] + timedelta(days=int(count_days))

    with transaction.atomic():
        if metering is not None:
            metering.status = MeteringStatus.sold_out
            metering.save()
            if metering.invoice:
                from call_center.services import log_solution

                old = metering.invoice.solution
                metering.invoice.solution = SolutionChoice.sold_out
                metering.invoice.save()
                log_solution(metering.invoice, old, int(SolutionChoice.sold_out), author)
        order = Order(**fields)
        order.save()
    return order


def set_order_location(order, *, point, link=UNSET, address=UNSET, by=None):
    """Attach / clear the order's map location (`point=None` and no link clears it)."""
    from django.db import transaction

    from core.exceptions import ServiceError
    from core.geo import resolve_location

    from .models import Order

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        new_lat, new_lon, new_link = resolve_location(locked, point, link)
        fields = []
        if (locked.lat, locked.lon, locked.address_link) != (new_lat, new_lon, new_link):
            locked.lat, locked.lon, locked.address_link = new_lat, new_lon, new_link
            fields += ["lat", "lon", "address_link"]
        if address is not UNSET:
            text = (address or "").strip()[:255]
            if (text or locked.lat is not None) and text != locked.address:
                locked.address = text
                fields.append("address")
        if not locked.address and locked.lat is None:
            raise ServiceError("Manzilni kiriting yoki xaritadan nuqta qo'shing")
        if fields:
            locked._history_user = by
            locked.save(update_fields=fields)
    for name in ("lat", "lon", "address", "address_link"):
        setattr(order, name, getattr(locked, name))
    return order, bool(fields)


def send_order_to_detailing(order, *, due_at):
    """The bosh menejer sends a «Yaratildi» order to detailing with a deadline."""
    from core.exceptions import ServiceError

    from .detailing.models import Detailing
    from .detailing.services import clean_detailing_due

    if order.status != OrderStatus.CREATED:
        raise ServiceError("Detalirovkaga faqat «Yaratildi» holatidagi buyurtma yuboriladi")
    due_at = clean_detailing_due(due_at)
    from django.db import transaction

    with transaction.atomic():
        detailing, _ = Detailing.objects.get_or_create(order=order)
        detailing.due_at = due_at
        detailing.save(update_fields=["due_at"])
        order.change_status(OrderStatus.DETAILING)
    return order


INSTALLING_CONFIRM_MSG = (
    "Buyurtma «Готов» bo'ladi faqat Ishlab chiqarish rahbari «Tayyor» bosganda (Yig'ish bo'limida)"
)


def installing_needs_head_confirm(order) -> bool:
    """An order in «Установка» that has an assembly job becomes «Готов» only through the
    production head's «Tayyor» (`confirm_assembly`), never by «Keyingi bosqich». Orders
    without an assembly row keep the plain step."""
    from .assembly.models import Assembly

    # a legacy row already marked installed must not leave the order stuck
    return Assembly.objects.filter(order=order, installing_done=False).exists()


ASSEMBLY_SEND_MSG = "Yig'ishga faqat Ishlab chiqarish rahbari yuboradi"


def can_send_to_assembly(user) -> bool:
    """Who sends an order to «Сборка»: the Ishlab chiqarish rahbari or an assembly manager
    (custom groups / superusers)."""
    from .assembly.constants import ASSEMBLY_MANAGER_PERMISSION

    return bool(
        user.has_perm("oauth.user_production_head")
        or user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
    )


def advance_order_status(order):
    """Mirrors OrderActions.change_status: one step along progression_statuses()."""
    from core.exceptions import ServiceError
    from core.i18n import order_status as order_status_uz

    next_status = OrderStatus.next_status(order.status)
    if next_status == OrderStatus.DETAILING:
        # owner's rule: detailing always gets a deadline — only via «Detalirovkaga yuborish»
        raise ServiceError(
            "Detalirovkaga «Detalirovkaga yuborish» tugmasi bilan, muddatini belgilab yuboring"
        )
    if next_status == OrderStatus.ASSEMBLY:
        # only via «Yig'ishga yuborish» (head / assembly manager, assembly row must exist)
        raise ServiceError(
            "Yig'ishga «Yig'ishga yuborish» tugmasi bilan yuboring (Ishlab chiqarish rahbari)"
        )
    if order.status == OrderStatus.INSTALLING and installing_needs_head_confirm(order):
        raise ServiceError(INSTALLING_CONFIRM_MSG)
    if next_status is None:
        raise ServiceError(
            f"Holatni o'zgartirib bo'lmaydi: «{order_status_uz(order.status)}» — yakuniy holat."
        )
    order.change_status(next_status)
    return order


def send_order_to_assembly(order):
    """Mirrors OrderActions.go_to_assembly_action. Returns the Assembly row."""
    from core.exceptions import ServiceError

    from .assembly.models import Assembly

    if order.status != OrderStatus.WORKING:
        raise ServiceError("Yig'ishga faqat «Xomashyo buyurtmasi» holatidagi buyurtma yuboriladi")
    assembly = Assembly.objects.filter(order=order).first()
    if assembly is None:
        raise ServiceError(
            "Bu buyurtma uchun yig'ish yaratilmagan — detalirovkada maydonni ko'rsating."
        )
    order.change_status(OrderStatus.ASSEMBLY)
    return assembly


# Owner's rule: the first payment is 70% of the contract. An order whose client has
# paid less than this share is followed up by the bosh menejer (home page, «Buyurtmalar»).
UNDERPAID_PCT = 65


def underpaid_orders(qs=None):
    """Live orders (waiting or in work) whose client paid less than UNDERPAID_PCT % of
    the price after discount. Nothing paid yet counts as 0 %. An order paid in another
    currency than its price cannot be compared and is left out (like money_left).
    Annotates `paid_share` (0..1) and `total_sum`."""
    from django.db.models import Case, ExpressionWrapper, F, FloatField, Q, Value, When

    from .models import Order

    if qs is None:
        qs = Order.objects.all()
    total = ExpressionWrapper(F("price") * (1 - F("discount") / 100.0), output_field=FloatField())
    return (
        qs.filter(
            status__in=[OrderStatus.WAITING, *OrderStatus.active_statuses()],
            price__isnull=False,
            price__gt=0,
        )
        .annotate(total_sum=total)
        .filter(total_sum__gt=0)
        .filter(
            Q(lost_money__isnull=True)
            | Q(
                lost_money_currency=F("price_currency"),
                lost_money__lt=F("total_sum") * (UNDERPAID_PCT / 100.0),
            )
        )
        .annotate(
            paid_share=Case(
                When(lost_money__isnull=True, then=Value(0.0)),
                default=ExpressionWrapper(
                    F("lost_money") / F("total_sum"), output_field=FloatField()
                ),
                output_field=FloatField(),
            )
        )
    )
