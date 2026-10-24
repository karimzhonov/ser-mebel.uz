"""Selectors for the Замеры kanban on the admin dashboard."""

from django.db.models import F, Q
from django.urls import reverse

from core.kanban import DANGER, INFO, OK, PRIMARY, WARN, Column, build_board

from .constants import MeteringStatus


def metering_board(to_card=None) -> list[dict]:
    """Columns for the "Замеры" kanban.

    Дизайн and Нарх are not statuses — they are the Design and Price rows hanging off
    a metering. A metering that has been measured therefore moves through three
    columns without its status changing: Замерга борилди while no design exists,
    Дизайн while the design is unfinished, Нарх once the design is done. Every
    measured metering matches exactly one of those three arms.
    """
    from .models import Metering

    changelist = reverse("admin:metering_metering_changelist")

    def by_status(status):
        return f"{changelist}?status={status}"

    measured = Q(status=MeteringStatus.metering_done)

    columns = [
        Column(
            "created",
            "Заявка олинди",
            "add",
            INFO,
            Q(status=MeteringStatus.created),
            more_url=by_status(MeteringStatus.created),
        ),
        Column(
            "other_day",
            "Бошқа кунга",
            "warning",
            WARN,
            Q(status=MeteringStatus.other_day),
            more_url=by_status(MeteringStatus.other_day),
        ),
        Column(
            "measured",
            "Замерга борилди",
            "straighten",
            INFO,
            measured & Q(design__isnull=True),
            more_url=by_status(MeteringStatus.metering_done),
            more_label="Все замеры →",
        ),
        # Дизайн and Нарх link to their own lists, which select a different set than
        # the column counts — so they get a label instead of an "Ещё N" the link
        # would not match.
        Column(
            "design",
            "Дизайн",
            "brush",
            PRIMARY,
            measured & Q(design__isnull=False, design__done=False),
            more_url=reverse("admin:design_design_changelist") + "?done=False",
            more_label="Все дизайны →",
        ),
        Column(
            "price",
            "Нарх чиқариш",
            "attach_money",
            PRIMARY,
            measured & Q(design__done=True),
            more_url=reverse("admin:price_price_changelist") + "?done=False",
            more_label="Все расчёты →",
        ),
        Column(
            "done",
            "Бажарилди",
            "check",
            OK,
            Q(status=MeteringStatus.done),
            more_url=by_status(MeteringStatus.done),
        ),
        Column(
            "sold_out",
            "Сотилди",
            "done_all",
            OK,
            Q(status=MeteringStatus.sold_out),
            collapsed=True,
            more_url=by_status(MeteringStatus.sold_out),
        ),
        Column(
            "dont_need",
            "Отмен болди",
            "close",
            DANGER,
            Q(status=MeteringStatus.dont_need),
            collapsed=True,
            more_url=by_status(MeteringStatus.dont_need),
        ),
    ]

    # date_time is nullable and Postgres sorts NULLs first on DESC — pin them last so
    # an undated metering can't head every column.
    queryset = Metering.objects.select_related("client", "design", "price").order_by(
        F("date_time").desc(nulls_last=True)
    )

    return build_board(queryset, columns, to_card or _metering_card)


def _metering_card(metering) -> dict:
    # Reverse OneToOne: both are select_related above, so this touches no extra query,
    # but the attribute still raises when the row is absent — hence getattr.
    design = getattr(metering, "design", None)
    price = getattr(metering, "price", None)

    return {
        "url": reverse("admin:metering_metering_change", args=[metering.pk]),
        "client": str(metering.client),
        "phone": str(metering.client.phone),
        "address": metering.address or "—",
        "desc": (metering.desc or "").strip(),
        "when": metering.date_time,
        "has_design": design is not None,
        "design_done": bool(design and design.done),
        "has_price": price is not None,
        "price_done": bool(price and price.done),
    }


# --- Write services (used by the REST API; mirror MeteringCreateForm / MeteringActions) ---


def metering_is_editable(metering) -> bool:
    """MeteringAdmin.has_change_permission: archived meterings are read-only."""
    return metering.status not in MeteringStatus.archive_statuses()


def create_metering(*, client, date_time, address=None, address_link=None, desc=None, invoice=None):
    """Mirrors MeteringCreateForm.save: linking an invoice marks it "Замерга борилади"."""
    from django.db import transaction

    from call_center.constants import SolutionChoice
    from core.exceptions import ServiceError

    from .models import Metering

    if invoice is not None:
        if invoice.client_id != client.pk:
            raise ServiceError("Ariza boshqa mijozga tegishli")
        if Metering.objects.filter(invoice=invoice).exists():
            raise ServiceError("Bu ariza uchun o'lchov allaqachon yaratilgan")

    with transaction.atomic():
        metering = Metering.objects.create(
            client=client,
            date_time=date_time,
            address=address,
            address_link=address_link,
            desc=desc,
            invoice=invoice,
        )
        if invoice is not None:
            invoice.solution = SolutionChoice.go_for_measured
            invoice.save()
    return metering


def _require_status(metering, allowed):
    from core.i18n import metering_status as metering_status_uz
    from core.exceptions import ServiceError

    if metering.status in MeteringStatus.archive_statuses():
        raise ServiceError("Ushbu mijozga xizmat ko'rsatilgan")
    if metering.status not in allowed:
        raise ServiceError(
            f"«{metering_status_uz(metering.status)}» holatida bu amalni bajarib bo'lmaydi"
        )


def mark_metering_dont_need(metering):
    _require_status(
        metering, [MeteringStatus.created, MeteringStatus.other_day, MeteringStatus.metering_done]
    )
    metering.status = MeteringStatus.dont_need
    metering.save(update_fields=["status"])
    return metering


def mark_metering_other_day(metering, date_time=None):
    """ "Бошқа кунга ўзгартирилди" — optionally with the new date in the same step,
    like the admin submit-line button that saves the form and the status together."""
    _require_status(metering, [MeteringStatus.created, MeteringStatus.other_day])
    metering.status = MeteringStatus.other_day
    fields = ["status"]
    if date_time is not None:
        metering.date_time = date_time
        fields.append("date_time")
    metering.save(update_fields=fields)
    return metering


def mark_metering_done(metering):
    _require_status(metering, [MeteringStatus.created, MeteringStatus.other_day])
    metering.status = MeteringStatus.metering_done
    metering.save(update_fields=["status"])
    return metering


def start_design(metering):
    from core.exceptions import ServiceError

    from .design.models import Design

    if Design.objects.filter(metering=metering).exists():
        raise ServiceError("Dizayn allaqachon yaratilgan")
    return Design.objects.create(metering=metering)


def start_price(metering):
    from core.exceptions import ServiceError

    from .price.models import Price

    if Price.objects.filter(metering=metering).exists():
        raise ServiceError("Narx hisoblash allaqachon yaratilgan")
    return Price.objects.create(metering=metering)


# --- Assigning the design / price tasks after the metering --------------------------

ASSIGNABLE_STATUSES = [MeteringStatus.metering_done, MeteringStatus.done]


def designers():
    """Who may be picked to draw the design: design staff who can also open the
    design page the Telegram link points to."""
    from oauth.constants import DESIGN_PERMISSION
    from oauth.services import users_with_perm

    can_open = users_with_perm("design", "view_design").values("pk")
    return (
        users_with_perm("oauth", DESIGN_PERMISSION)
        .filter(pk__in=can_open)
        .order_by("name", "phone")
    )


def pricers():
    """Who may be picked to calculate the price: users who can edit price calculations
    (and open them)."""
    from oauth.services import users_with_perm

    can_open = users_with_perm("price", "view_price").values("pk")
    return (
        users_with_perm("price", "change_price").filter(pk__in=can_open).order_by("name", "phone")
    )


def assign_metering_tasks(metering, *, designer=None, pricer=None) -> dict:
    """After "Замер выполнен": give the design and/or the price task to one person each.

    Owner's rule: the metering staff hand these tasks out themselves, so this creates
    the Design / Price rows without design.add_design / price.add_price.

    A task that doesn't exist yet is created for that person; an existing unfinished
    task is handed over to the new person. Only the chosen people are notified, and only
    after the whole change is committed — a refused or failed request sends nothing.
    Returns {"design": "created"|"reassigned"|None, "price": ...}.
    """
    from django.db import IntegrityError, transaction

    from core.exceptions import ServiceError

    from .design.models import Design
    from .design.services import notify_design_task
    from .models import Metering
    from .price.models import Price
    from .price.services import notify_price_task

    if designer is None and pricer is None:
        raise ServiceError("Dizayner va/yoki narx hisoblovchini tanlang")
    if designer is not None and not designers().filter(pk=designer.pk).exists():
        raise ServiceError("Bu xodim dizayn qila olmaydi")
    if pricer is not None and not pricers().filter(pk=pricer.pk).exists():
        raise ServiceError("Bu xodim narx hisoblay olmaydi")

    result = {"design": None, "price": None}
    try:
        with transaction.atomic():
            # Serialises concurrent assigns of the same metering.
            locked = Metering.objects.select_for_update().get(pk=metering.pk)
            if locked.status not in ASSIGNABLE_STATUSES:
                raise ServiceError("Ijrochilar «O'lchov bajarildi»dan keyin tayinlanadi")
            design = Design.objects.filter(metering=locked).first()
            price = Price.objects.filter(metering=locked).first()
            # Every refusal before any write.
            if designer is not None and design is not None and design.done:
                raise ServiceError("Dizayn allaqachon bajarilgan — qayta tayinlab bo'lmaydi")
            if pricer is not None and price is not None and price.done:
                raise ServiceError("Narx allaqachon hisoblangan — qayta tayinlab bo'lmaydi")

            if designer is not None:
                if design is None:
                    # post_save notifies the designer once this commits.
                    Design.objects.create(metering=locked, user=designer)
                    result["design"] = "created"
                elif design.user_id != designer.pk:
                    design.user = designer
                    design.save(update_fields=["user"])
                    notify_design_task(design)  # deferred to on_commit
                    result["design"] = "reassigned"
            if pricer is not None:
                if price is None:
                    Price.objects.create(metering=locked, user=pricer)
                    result["price"] = "created"
                elif price.user_id != pricer.pk:
                    price.user = pricer
                    price.save(update_fields=["user"])
                    notify_price_task(price)
                    result["price"] = "reassigned"
    except IntegrityError:
        raise ServiceError("Vazifalar hozir tayinlanmoqda — sahifani yangilang")
    return result
