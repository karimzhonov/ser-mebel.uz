"""JSON shapes of the warehouse for the bot channel (docs/BOT_CONTRACT.md, "Ombor").

Decimals travel as strings (quantities with 3 places, money with 2) so the bot never
sees a float. Photos are read through `product.photos.all()`: prefetch it in lists.
"""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import quote

from call_center.dto import dt

from .services import q2, q3


def _s3(v) -> str:
    return str(q3(v))


def _s2(v) -> str:
    return str(q2(v))


def product_url(p) -> str:
    from django.conf import settings

    base = (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/warehouse?search={quote(p.code or p.name, safe='')}"


def order_ref_dto(o: dict) -> dict:
    """An order / client ID the keeper can give a chiqim to (from services.order_choices)."""
    return {
        "ref": o["ref"],
        "client": o["client"],
        "bucket": o["bucket"],
        "status_label": o["status_label"],
    }


def photo_dto(photo) -> dict:
    return {
        "id": photo.pk,
        "position": photo.position,
        "is_cover": photo.position == 0,
        "width": photo.width,
        "height": photo.height,
        "tg_file_id": photo.tg_file_id,
    }


def product_dto(p, *, with_photos: bool = False) -> dict:
    photos = list(p.photos.all())  # prefetched by services.find_products
    cover = photos[0] if photos else None
    data = {
        "id": p.pk,
        "name": p.name,
        "code": p.code,
        "category": p.category,
        "unit": p.unit,
        "unit_label": p.get_unit_display(),
        "quantity": _s3(p.quantity),
        "min_quantity": _s3(p.min_quantity),
        "avg_cost": _s2(p.avg_cost),
        "value": _s2(p.quantity * p.avg_cost),
        "low": bool(p.min_quantity) and p.quantity <= p.min_quantity,
        "is_active": p.is_active,
        "photos_count": len(photos),
        "cover": photo_dto(cover) if cover else None,
        "url": product_url(p),
    }
    if with_photos:
        data["photos"] = [photo_dto(x) for x in photos]
    return data


def movement_dto(m) -> dict:
    by = m.created_by
    return {
        "id": m.pk,
        "number": m.number,
        "kind": m.kind,
        "kind_label": m.get_kind_display(),
        "quantity": _s3(m.quantity),
        "unit_label": m.product.get_unit_display(),
        "currency": m.currency,
        "unit_price": _s2(m.unit_price),
        "orig_price": _s2(m.orig_price) if m.orig_price is not None else None,
        "rate": str(m.rate.quantize(Decimal("0.0001"))) if m.rate is not None else None,
        "total": _s2(m.total),
        "date": m.date.isoformat(),
        "counterparty": m.counterparty,
        "allocations": [
            {
                "ref": a.order_ref,
                "client": a.client,
                "quantity": _s3(a.quantity),
                "total": _s2(a.total),
            }
            for a in m.allocations.all()
        ],
        "comment": m.comment,
        "balance_after": _s3(m.balance_after),
        "is_cancelled": m.is_cancelled,
        "by_name": (by.name or str(by.phone)) if by else "",
        "created_at": dt(m.created_at),
    }
