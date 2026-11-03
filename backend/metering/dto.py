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
