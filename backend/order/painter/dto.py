"""JSON shape of a painter job for the bot channel (docs/BOT_CONTRACT.md, "PainterTask")."""

from __future__ import annotations

from call_center.dto import dt, user_ref
from core.geo import obj_map_url


def painter_url(painter_id) -> str:
    from django.conf import settings

    base = (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/production/painter?open={painter_id}"


def _parts(p) -> list:
    """The job's parts in id order (uses the prefetch when there is one)."""
    return sorted(p.parts.all(), key=lambda x: x.pk)


def assigned_square(parts) -> float:
    return float(round(sum(x.square for x in parts), 2))


def remainder_square(p, parts=None) -> float:
    """m² of the job not given to any team yet (never negative)."""
    if p.done:
        return 0.0
    parts = _parts(p) if parts is None else parts
    return max(round(round(p.square, 2) - assigned_square(parts), 2), 0.0)


def part_ref(x) -> dict:
    ptype = x.type
    return {
        "id": x.pk,
        "type": {"id": ptype.pk, "name": ptype.name},
        "painter": user_ref(ptype.user) if ptype.user_id else None,
        "outsource": bool(ptype.outsource),
        "square": x.square,
        "state": x.state,
        "done_at": dt(x.done_at),
        "due_date": x.due_date.isoformat() if x.due_date else None,
        "rev": x.rev,
    }


def painter_task(p, viewer=None) -> dict:
    """The job. With exactly one part the per-team keys (type, painter, due_*, note,
    outsource) are that part's; with several they are null (see `parts`)."""
    order = p.order
    client = order.client
    parts = _parts(p)
    one = parts[0] if len(parts) == 1 else None
    ptype = one.type if one else None
    if one is not None:
        due_date, due_auto, due_set_by, note = one.due_date, one.due_auto, one.due_set_by, one.note
    else:
        due_date, due_auto, due_set_by, note = None, False, None, p.note
    # never show the client's phone to an outsource molyar on a legacy card: for a split
    # job the flag is "any outsource team", or the viewer's own part when known
    outsource = bool(ptype and ptype.outsource) if one else any(x.type.outsource for x in parts)
    if viewer is not None and one is None:
        own = [x for x in parts if x.type.user_id == viewer.pk]
        if own:
            outsource = any(x.type.outsource for x in own)
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
        "outsource": outsource,
        "painter": user_ref(ptype.user) if ptype and ptype.user_id else None,
        "state": p.state,
        "state_label": p.state_label,
        "started_at": dt(p.started_at),
        "done_at": dt(p.done_at),
        "done_by": user_ref(p.done_by),
        "due_date": due_date.isoformat() if due_date else None,
        "due_auto": due_auto,
        "due_set_by": user_ref(due_set_by),
        "overdue": any(x.overdue for x in parts),
        "days_late": max((x.days_late for x in parts), default=0),
        "note": note,
        "rev": p.rev,
        "url": painter_url(p.pk),
        "parts": [part_ref(x) for x in parts],
        "assigned_square": assigned_square(parts),
        "remainder": remainder_square(p, parts),
        "split_url": f"{painter_url(p.pk)}&split=1",
    }


def painter_part_task(x) -> dict:
    """One team's part of a job (no money)."""
    p = x.painter
    order = p.order
    client = order.client
    ptype = x.type
    return {
        "id": x.pk,
        "painter_id": p.pk,
        "order": {"id": order.pk, "number": order.order_number},
        "client": {
            "fio": client.fio if client else "",
            "phone": str(client.phone) if client and client.phone else "",
        },
        "address": order.address or "",
        "map_url": obj_map_url(order),
        "square": x.square,
        "total_square": p.square,
        "type": {"id": ptype.pk, "name": ptype.name},
        "outsource": bool(ptype.outsource),
        "painter": user_ref(ptype.user) if ptype.user_id else None,
        "state": x.state,
        "state_label": x.state_label,
        "started_at": dt(x.started_at),
        "done_at": dt(x.done_at),
        "done_by": user_ref(x.done_by),
        "due_date": x.due_date.isoformat() if x.due_date else None,
        "due_auto": x.due_auto,
        "due_set_by": user_ref(x.due_set_by),
        "overdue": x.overdue,
        "days_late": x.days_late,
        "note": x.note,
        "rev": x.rev,
        "url": painter_url(p.pk),
    }
