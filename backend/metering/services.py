"""Selectors for the Замеры kanban on the admin dashboard."""

from django.db.models import F, Q
from django.urls import reverse

from core.kanban import DANGER, INFO, OK, PRIMARY, WARN, Column, build_board

from .constants import MeteringStatus


def metering_board() -> list[dict]:
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
        Column("created", "Заявка олинди", "add", INFO,
               Q(status=MeteringStatus.created), more_url=by_status(MeteringStatus.created)),
        Column("other_day", "Бошқа кунга", "warning", WARN,
               Q(status=MeteringStatus.other_day), more_url=by_status(MeteringStatus.other_day)),
        Column("measured", "Замерга борилди", "straighten", INFO,
               measured & Q(design__isnull=True),
               more_url=by_status(MeteringStatus.metering_done),
               more_label="Все замеры →"),
        # Дизайн and Нарх link to their own lists, which select a different set than
        # the column counts — so they get a label instead of an "Ещё N" the link
        # would not match.
        Column("design", "Дизайн", "brush", PRIMARY,
               measured & Q(design__isnull=False, design__done=False),
               more_url=reverse("admin:design_design_changelist") + "?done=False",
               more_label="Все дизайны →"),
        Column("price", "Нарх чиқариш", "attach_money", PRIMARY,
               measured & Q(design__done=True),
               more_url=reverse("admin:price_price_changelist") + "?done=False",
               more_label="Все расчёты →"),
        Column("done", "Бажарилди", "check", OK,
               Q(status=MeteringStatus.done), more_url=by_status(MeteringStatus.done)),
        Column("sold_out", "Сотилди", "done_all", OK,
               Q(status=MeteringStatus.sold_out), collapsed=True,
               more_url=by_status(MeteringStatus.sold_out)),
        Column("dont_need", "Отмен болди", "close", DANGER,
               Q(status=MeteringStatus.dont_need), collapsed=True,
               more_url=by_status(MeteringStatus.dont_need)),
    ]

    # date_time is nullable and Postgres sorts NULLs first on DESC — pin them last so
    # an undated metering can't head every column.
    queryset = Metering.objects.select_related("client", "design", "price").order_by(
        F("date_time").desc(nulls_last=True)
    )

    return build_board(queryset, columns, _metering_card)


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
