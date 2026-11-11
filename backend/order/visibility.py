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
