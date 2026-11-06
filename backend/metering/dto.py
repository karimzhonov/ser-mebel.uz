"""JSON shape of a metering for the bot channel (docs/BOT_CONTRACT.md, "Zamer")."""

from __future__ import annotations

from call_center.dto import dt, user_ref
from core.geo import obj_map_url
from core.i18n import metering_status


def metering_brief(m) -> dict:
    from .events import metering_url
    from .services import metering_operator

    return {
        "id": m.pk,
        "rev": m.rev,
        "client": {"fio": m.client.fio, "phone": str(m.client.phone)},
        "status": m.status,
        "status_label": metering_status(m.status),
        "date_time": dt(m.date_time),
        "address": m.address or "",
        "map_url": obj_map_url(m),
        "has_point": m.lat is not None and m.lon is not None,
        "desc": (m.desc or "").strip(),
        "measurer": user_ref(m.measurer),
        "operator": user_ref(metering_operator(m)),
        "next_step": m.next_step or "",
        "cancel_reason": m.cancel_reason or "",
        "url": metering_url(m.pk),
    }


def offer_task(obj, kind: str) -> dict:
    """A Design (kind "design") or Price (kind "price") as the bot shows it
    (docs/BOT_CONTRACT.md, "OfferTask")."""
    from .constants import stage_label
    from .events import offer_url, present_url

    m = obj.metering
    last = (
        m.offer_answers.filter(kind=kind).exclude(comment="").order_by("-created_at", "-pk").first()
    )
    return {
        "kind": kind,
        "id": obj.pk,
        "rev": obj.rev,
        "metering_id": m.pk,
        "round": obj.round,
        "stage": obj.stage,
        "stage_label": stage_label(obj.stage),
        "client": {"fio": m.client.fio, "phone": str(m.client.phone)},
        "address": m.address or "",
        "map_url": obj_map_url(m),
        "due_at": dt(obj.due_at),
        "done_at": dt(obj.done_at),
        "assignee": user_ref(obj.user),
        "manager": user_ref(m.manager),
        "measurer": user_ref(m.measurer),
        "note": (m.result_note or "").strip(),
        "last_comment": last.comment if last else None,
        "next_step": m.next_step or "",
        "url": offer_url(kind, obj.pk),
        "present_url": present_url(kind, obj.pk),
    }
