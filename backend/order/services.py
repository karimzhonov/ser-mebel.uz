from .constants import OrderStatus


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
