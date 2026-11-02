"""JSON shapes of the CRM for the bot channel (docs/BOT_CONTRACT.md, "CRM")."""

from __future__ import annotations

from core.i18n import lead_source, solution


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
    }
