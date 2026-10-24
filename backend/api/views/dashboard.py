from constance import config
from djmoney import settings as dj_settings
from rest_framework.response import Response
from rest_framework.views import APIView

from call_center.constants import SolutionChoice
from metering.constants import MeteringStatus
from metering.price.models import InventoryType, ObjectType
from order.constants import ORDER_VIEW_PRICE_PERMISSION, OrderStatus

from .. import i18n as uz
from ..serializers.common import money_left
from ..utils import order_deadline

# ActionVariant / get_sev values -> one tone vocabulary for the SPA.
_TONE = {
    "danger": "danger",
    "warning": "warn",
    "info": "info",
    "success": "ok",
    "primary": "primary",
    "secondary": "idle",
    "default": "idle",
}


def _tone(value):
    return _TONE.get(str(getattr(value, "value", value)), "idle")


class MetaView(APIView):
    """Enum labels/colours/icons + the few settings the SPA needs, so the frontend
    never hard-codes a status label that the backend owns."""

    def get(self, request):
        return Response(
            {
                "order_statuses": [
                    {
                        "value": s.value,
                        "label": uz.order_status(s.value),
                        "tone": _tone(OrderStatus.get_sev(s)),
                        "icon": OrderStatus.icon(s),
                    }
                    for s in OrderStatus
                ],
                "metering_statuses": [
                    {
                        "value": s.value,
                        "label": uz.metering_status(s.value),
                        "tone": _tone(MeteringStatus.variant(s)),
                        "icon": MeteringStatus.icon(s),
                        "archive": s in MeteringStatus.archive_statuses(),
                    }
                    for s in MeteringStatus
                ],
                "solutions": [
                    {
                        "value": s.value,
                        "label": uz.solution(s.value),
                        "tone": _tone(SolutionChoice.variant(s)),
                        "icon": SolutionChoice.icon(s),
                    }
                    for s in SolutionChoice
                ],
                "inventory_type_kinds": [
                    {"value": v, "label": uz.INVENTORY_KIND.get(v, label)}
                    for v, label in InventoryType.TYPES
                ],
                "count_names": [
                    {"value": v, "label": uz.COUNT_NAME.get(v, label)}
                    for v, label in ObjectType.COUNT_NAMES
                ],
                "currencies": [code for code, _ in dj_settings.CURRENCY_CHOICES],
                "default_currency": dj_settings.DEFAULT_CURRENCY,
                "warning_order_days": config.WARNING_ORDER_DAYS,
                "usd_rate": config.USD_CURRENCY,
                "site_title": config.SITE_TITLE,
            }
        )


def _order_card(order, show_price):
    card = {
        "id": order.pk,
        "number": order.order_number,
        "client": str(order.client) if order.client_id else "—",
        "phone": str(order.client.phone) if order.client_id else "",
        "address": order.address,
        "desc": (order.desc or "").strip(),
        "factory": order.factory.name,
        "end_date": order.end_date,
        "deadline": order_deadline(order),
    }
    if show_price and order.price is not None:
        card["left"] = money_left(order)
    return card


def _metering_card(metering):
    design = getattr(metering, "design", None)
    price = getattr(metering, "price", None)
    return {
        "id": metering.pk,
        "client": str(metering.client),
        "phone": str(metering.client.phone),
        "address": metering.address or "",
        "desc": (metering.desc or "").strip(),
        "when": metering.date_time,
        "has_design": design is not None,
        "design_done": bool(design and design.done),
        "has_price": price is not None,
        "price_done": bool(price and price.done),
    }


def _invoice_card(invoice):
    return {
        "id": invoice.pk,
        "client": str(invoice.client),
        "phone": str(invoice.client.phone),
        "desc": (invoice.desc or "").strip(),
        "when": invoice.create_date,
    }


def _strip(columns, board):
    """Drop the admin-only link fields from core.kanban.build_board output and give
    the columns their Uzbek titles (the board definitions are shared with the admin)."""
    keep = ("key", "title", "icon", "accent", "collapsed", "count", "cards", "more")
    titles = uz.BOARD_COLUMN.get(board, {})
    return [
        {**{k: column[k] for k in keep}, "title": titles.get(column["key"], column["title"])}
        for column in columns
    ]


class BoardsView(APIView):
    """The /admin/ landing page: three kanban boards, each only for users who may view
    that model (core/views.py dashboard_callback)."""

    def get(self, request):
        from call_center.models import Invoice
        from call_center.services import call_center_board
        from metering.models import Metering
        from metering.services import metering_board
        from order.models import Order
        from order.services import order_board

        user = request.user
        boards = []
        if user.has_perm("order.view_order"):
            show_price = user.has_perm(f"order.{ORDER_VIEW_PRICE_PERMISSION}")
            boards.append(
                {
                    "id": "orders",
                    "label": uz.BOARD_LABEL["orders"],
                    "total": Order.objects.count(),
                    "columns": _strip(
                        order_board(
                            user=user,
                            show_price=show_price,
                            to_card=lambda o: _order_card(o, show_price),
                        ),
                        "orders",
                    ),
                }
            )
        if user.has_perm("metering.view_metering"):
            boards.append(
                {
                    "id": "meterings",
                    "label": uz.BOARD_LABEL["meterings"],
                    "total": Metering.objects.count(),
                    "columns": _strip(metering_board(to_card=_metering_card), "meterings"),
                }
            )
        if user.has_perm("call_center.view_invoice"):
            boards.append(
                {
                    "id": "callcenter",
                    "label": uz.BOARD_LABEL["callcenter"],
                    "total": Invoice.objects.count(),
                    "columns": _strip(call_center_board(to_card=_invoice_card), "callcenter"),
                }
            )
        return Response({"boards": boards})
