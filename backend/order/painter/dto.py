"""JSON shape of a painter job for the bot channel (docs/BOT_CONTRACT.md, "PainterTask")."""

from __future__ import annotations

from call_center.dto import dt, user_ref
from core.geo import obj_map_url


def painter_url(painter_id) -> str:
    from django.conf import settings

    base = (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/production/painter?open={painter_id}"


def painter_task(p) -> dict:
    order = p.order
    client = order.client
    ptype = p.type
    return {
        "id": p.pk,
        "order": {"id": order.pk, "number": order.order_number},
        "client": {
            "fio": client.fio if client else "",
            "phone": str(client.phone) if client and client.phone else "",
        },
        "address": order.address or "",
        "map_url": obj_map_url(order),
        "square": p.square,
        "type": {"id": ptype.pk, "name": ptype.name} if ptype else None,
        "outsource": bool(ptype and ptype.outsource),
        "painter": user_ref(ptype.user) if ptype and ptype.user_id else None,
        "state": p.state,
        "state_label": p.state_label,
        "started_at": dt(p.started_at),
        "done_at": dt(p.done_at),
        "done_by": user_ref(p.done_by),
        "due_date": p.due_date.isoformat() if p.due_date else None,
        "due_auto": p.due_auto,
        "due_set_by": user_ref(p.due_set_by),
        "overdue": p.overdue,
        "days_late": p.days_late,
        "note": p.note,
        "rev": p.rev,
        "url": painter_url(p.pk),
    }
