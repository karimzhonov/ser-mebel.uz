"""JSON shape of a rover job for the bot channel (docs/BOT_CONTRACT.md, "RoverTask")."""

from __future__ import annotations

from call_center.dto import dt, user_ref
from core.geo import obj_map_url


def rover_url(rover_id) -> str:
    from django.conf import settings

    base = (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/production/rover?open={rover_id}"


def design_folder_id(order, fallback: bool = True) -> int | None:
    """The order's «Дизайн» folder (made under the metering folder); with `fallback` the
    order folder when there is none; None when there is nothing."""
    from filer.models import Folder

    # After the order is created the metering folder's children move under the order
    # folder, so look there first, then under the metering folder.
    parents = [order.folder_id]
    metering = getattr(order, "metering", None)
    if metering is not None:
        parents.append(metering.folder_id)
    folder_id = None
    for parent_id in parents:
        if not parent_id:
            continue
        folder_id = (
            Folder.objects.filter(parent_id=parent_id, name="Дизайн")
            .order_by("pk")
            .values_list("pk", flat=True)
            .first()
        )
        if folder_id:
            break
    return folder_id or (order.folder_id if fallback else None)


def design_folder_url(order) -> str | None:
    """Panel link to the «Дизайн» folder only (the worker gets it), None when there is none."""
    from django.conf import settings

    folder_id = design_folder_id(order, fallback=False)
    if not folder_id:
        return None
    base = (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/files/{folder_id}"


def rover_task(r) -> dict:
    order = r.order
    client = order.client
    price = r.price
    return {
        "id": r.pk,
        "order": {"id": order.pk, "number": order.order_number},
        "client": {
            "fio": client.fio if client else "",
            "phone": str(client.phone) if client and client.phone else "",
        },
        "square": r.square,
        "amount": f"{price.amount:.2f}" if price is not None else "0.00",
        "currency": str(price.currency) if price is not None else "UZS",
        "state": r.state,
        "state_label": r.state_label,
        "submitted_at": dt(r.submitted_at),
        "submitted_by": user_ref(r.submitted_by),
        "checked_at": dt(r.checked_at),
        "checked_by": user_ref(r.checked_by),
        "address": order.address or "",
        "map_url": obj_map_url(order),
        "due_date": r.due_date.isoformat() if r.due_date else None,
        "due_auto": r.due_auto,
        "due_set_by": user_ref(r.due_set_by),
        "overdue": r.overdue,
        "days_late": r.days_late,
        "note": r.note,
        "rev": r.rev,
        "url": rover_url(r.pk),
        "design_folder_url": design_folder_url(order),
    }
