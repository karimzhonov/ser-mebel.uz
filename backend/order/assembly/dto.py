"""JSON shape of an assembly job for the bot channel (docs/BOT_CONTRACT.md, "AssemblyTask")."""

from __future__ import annotations

from call_center.dto import dt, user_ref
from core.geo import obj_map_url


def assembly_url(assembly_id) -> str:
    from django.conf import settings

    base = (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/production/assembly?open={assembly_id}"


def assembly_task(a) -> dict:
    order = a.order
    client = order.client
    return {
        "id": a.pk,
        "order": {"id": order.pk, "number": order.order_number},
        "client": {
            "fio": client.fio if client else "",
            "phone": str(client.phone) if client and client.phone else "",
        },
        "address": order.address or "",
        "map_url": obj_map_url(order),
        "square": a.square,
        "assembler": user_ref(a.user),
        "state": str(a.state),
        "state_label": a.state_label,
        "started_at": dt(a.started_at),
        "finished_at": dt(a.finished_at),
        "finished_by": user_ref(a.finished_by),
        "confirmed_at": dt(a.confirmed_at),
        "confirmed_by": user_ref(a.confirmed_by),
        "due_date": a.due_date.isoformat() if a.due_date else None,
        "due_auto": a.due_auto,
        "due_set_by": user_ref(a.due_set_by),
        "overdue": a.overdue,
        "days_late": a.days_late,
        "note": a.note,
        "rev": a.rev,
        "url": assembly_url(a.pk),
    }
