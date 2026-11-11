"""Who sees the whole order on a production job.

The Rover page and outsource Molyar jobs show a reduced order: no client phone, address,
map, dates or the link to the order. Only the production head, assembly managers and
superusers see it in full. Enforced in the API serializers (`api/serializers/orders.py`)."""

from __future__ import annotations

from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION

# keys of the nested `order` block that a restricted viewer must not get
RESTRICTED_ORDER_FIELDS = (
    "address",
    "address_link",
    "lat",
    "lon",
    "map_url",
    "end_date",
    "deadline",
)


def sees_full_order(user) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(
        user.is_superuser
        or user.has_perm("oauth.user_production_head")
        or user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
    )


def strip_order(order_data: dict | None) -> dict | None:
    """Blank the private fields of a serialized order block (in place)."""
    if not order_data:
        return order_data
    for key in RESTRICTED_ORDER_FIELDS:
        if key in order_data:
            order_data[key] = None
    client = order_data.get("client")
    if isinstance(client, dict):
        client["phone"] = None
    return order_data


DESIGN_FOLDER_NAME = "Дизайн"


def design_folder_access(user, folder):
    """The «Дизайн» folder that gives `user` read access to `folder` (the folder itself or
    an ancestor of it), or None.

    Rover and Molyar workers have no filer permissions: they see only the design folder
    (the «Дизайн» folder under the metering folder, see `order.rover.dto.design_folder_id`)
    of an order they work on, and everything below it:
    - rover: `rover.view_rover` and the order has a Rover row (rovers are not split per worker);
    - molyar: the order's Painter job belongs to the user's own team (`type.user`)."""
    from filer.models import Folder

    from order.models import Order
    from order.painter.models import Painter
    from order.painter.services import ready_for_painter
    from order.rover.models import Rover

    if user is None or not getattr(user, "is_authenticated", False) or folder is None:
        return None
    is_rover = user.has_perm("rover.view_rover")
    if not (is_rover or user.has_perm("painter.view_painter")):
        return None
    node, depth, owner = folder, 0, None
    while node is not None and depth < 20:
        if node.name == DESIGN_FOLDER_NAME and node.parent_id:
            # after the order is made «Дизайн» sits under the order folder; before, under
            # the metering folder
            orders = Order.objects.filter(folder_id=node.parent_id)
            if not orders.exists():
                orders = Order.objects.filter(metering__folder_id=node.parent_id)
            if orders.exists():
                owner = orders
                break
        node = Folder.objects.filter(pk=node.parent_id).first() if node.parent_id else None
        depth += 1
    if owner is None:
        return None
    if is_rover and Rover.objects.filter(order__in=owner).exists():
        return node
    jobs = ready_for_painter(Painter.objects.filter(order__in=owner, type__user=user))
    if jobs.exists():
        return node
    return None
