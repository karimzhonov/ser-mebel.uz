"""JSON shapes of the CRM for the bot channel (docs/BOT_CONTRACT.md, "CRM")."""

from __future__ import annotations

from core.geo import obj_map_url
from core.i18n import lead_source, metering_status, solution


def user_ref(user) -> dict | None:
    if user is None:
        return None
    return {"id": user.pk, "name": user.name or str(user.phone)}


def dt(value) -> str | None:
    """Naive local datetime, YYYY-MM-DDTHH:MM:SS."""
    return value.isoformat(timespec="seconds") if value else None


def task_dto(task) -> dict:
    return {
        "id": task.pk,
        "text": task.text,
        "due_at": dt(task.due_at),
        "is_done": task.done_at is not None,
        "assigned": user_ref(task.assigned_to),
    }


def lead_brief(invoice) -> dict:
    return {
        "id": invoice.pk,
        "client": {"fio": invoice.client.fio, "phone": str(invoice.client.phone)},
        "source": invoice.source or None,
        "source_label": lead_source(invoice.source),
        "solution": invoice.solution,
        "solution_label": solution(invoice.solution),
        "assigned": user_ref(invoice.assigned_to),
        "last_note": (invoice.desc or "").strip()[:300],
        "has_point": invoice.lat is not None and invoice.lon is not None,
        "map_url": obj_map_url(invoice),
    }


def location_target(kind: str, obj, user=None) -> dict:
    """A lead or metering the bot may attach a location to (docs/BOT_CONTRACT.md)."""
    if kind == "invoice":
        status, label = obj.solution, solution(obj.solution)
        when = obj.create_date
        mine = user is not None and obj.assigned_to_id == user.pk
    else:
        status, label = obj.status, metering_status(obj.status)
        when = obj.date_time
        invoice = obj.invoice
        mine = user is not None and invoice is not None and invoice.assigned_to_id == user.pk
    return {
        "kind": kind,
        "id": obj.pk,
        "client": {"fio": obj.client.fio, "phone": str(obj.client.phone)},
        "status": status,
        "status_label": label,
        "when": dt(when),
        "address": obj.address or "",
        "has_point": obj.lat is not None and obj.lon is not None,
        "mine": bool(mine),
    }
