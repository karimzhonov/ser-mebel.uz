"""The /admin/ landing page.

It is three kanban boards and nothing else: Заказы, Замеры, Call-center. A board is
built only for a user who may view that model, so someone with call-centre access
alone lands on a single-tab page rather than an empty one.
"""

from django.http.request import HttpRequest

from order.constants import ORDER_VIEW_PRICE_PERMISSION


def dashboard_callback(request: HttpRequest, context):
    from call_center.models import Invoice
    from call_center.services import call_center_board
    from metering.models import Metering
    from metering.services import metering_board
    from order.models import Order
    from order.services import order_board

    boards = []

    if request.user.has_perm("order.view_order"):
        boards.append(
            {
                "id": "orders",
                "label": "Заказы",
                "icon": "box",
                "total": Order.objects.count(),
                "card_template": "core/kanban/card_order.html",
                "columns": order_board(
                    user=request.user,
                    show_price=request.user.has_perm(f"order.{ORDER_VIEW_PRICE_PERMISSION}"),
                ),
            }
        )

    if request.user.has_perm("metering.view_metering"):
        boards.append(
            {
                "id": "meterings",
                "label": "Замеры",
                "icon": "straighten",
                "total": Metering.objects.count(),
                "card_template": "core/kanban/card_metering.html",
                "columns": metering_board(),
            }
        )

    if request.user.has_perm("call_center.view_invoice"):
        boards.append(
            {
                "id": "callcenter",
                "label": "Call-center",
                "icon": "phone",
                "total": Invoice.objects.count(),
                "card_template": "core/kanban/card_invoice.html",
                "columns": call_center_board(),
            }
        )

    context.update(boards=boards)
    return context
