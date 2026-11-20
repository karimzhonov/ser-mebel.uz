"""JSON shape of a detailing job for the bot channel (docs/BOT_CONTRACT.md, "DetailingTask")."""

from __future__ import annotations

from call_center.dto import dt
from core.geo import obj_map_url


def _base() -> str:
    from django.conf import settings

    return (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")


def detailing_url(detailing_id) -> str:
    return f"{_base()}/production/detailing?open={detailing_id}"


def detailing_task(d) -> dict:
    order = d.order
    client = order.client
    return {
        "id": d.pk,
        "order": {"id": order.pk, "number": order.order_number},
        "client": {
            "fio": client.fio if client else "",
            "phone": str(client.phone) if client and client.phone else "",
        },
        "address": order.address or "",
        "map_url": obj_map_url(order),
        "end_date": order.end_date.isoformat() if order.end_date else None,
        "due_at": dt(d.due_at),
        "done": d.done,
        "url": detailing_url(d.pk),
        "folder_url": f"{_base()}/files/{order.folder_id}" if order.folder_id else None,
    }
