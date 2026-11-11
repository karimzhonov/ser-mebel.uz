"""JSON shape of a rover job for the bot channel (docs/BOT_CONTRACT.md, "RoverTask")."""

from __future__ import annotations

from call_center.dto import dt, user_ref
from core.geo import obj_map_url


def rover_url(rover_id) -> str:
    from django.conf import settings

    base = (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/production/rover?open={rover_id}"


def design_folder_url(order) -> str | None:
    """Panel link to the order's «Дизайн» folder (made under the metering folder), else the
    order folder; None when there is neither."""
    from django.conf import settings
    from filer.models import Folder

    folder_id = None
    metering = getattr(order, "metering", None)
    if metering is not None and metering.folder_id:
        folder_id = (
            Folder.objects.filter(parent_id=metering.folder_id, name="Дизайн")
            .values_list("pk", flat=True)
            .first()
        )
    folder_id = folder_id or order.folder_id
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
