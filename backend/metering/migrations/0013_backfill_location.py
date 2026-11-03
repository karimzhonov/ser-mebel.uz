import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, unquote, urlparse

from django.db import migrations

# A frozen copy of the exact-marker part of the link parser (core.geo may change later).
# Only links that carry the real point are read; a map "view centre" (ll, /@lat,lon,
# center, rtext) is NOT a point and never gets one.
_NUM = r"[-+]?\d{1,3}(?:\.\d+)?"


def _point(lat, lon):
    try:
        la, lo = Decimal(str(lat).strip()), Decimal(str(lon).strip())
    except (InvalidOperation, ValueError):
        return None
    if not (la.is_finite() and lo.is_finite()):
        return None
    if not (-90 <= la <= 90 and -180 <= lo <= 180) or (la == 0 and lo == 0):
        return None
    q = Decimal("0.000001")
    return la.quantize(q), lo.quantize(q)


def _pair(value, lon_first=False):
    m = re.match(
        rf"^\s*({_NUM})\s*[,;\s]\s*({_NUM})(?![\d.])",
        " ".join(unquote(value or "").replace("+", " ").split()),
    )
    if not m:
        return None
    return _point(m[2], m[1]) if lon_first else _point(m[1], m[2])


def parse_exact(text):
    text = (text or "").strip()
    if text.lower().startswith("geo:"):
        m = re.match(rf"geo:({_NUM}),({_NUM})", text, re.I)
        return _point(m[1], m[2]) if m else None
    m = re.search(r"https?://[^\s<>\"']+", text, re.I)
    if not m:
        return None
    url = m[0]
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for name in ("pt", "whatshere[point]"):
        v = (qs.get(name) or [""])[0]
        if v:
            p = _pair(v, lon_first=True)
            if p:
                return p
    m = re.search(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", unquote(url))
    if m:
        return _point(m[1], m[2])
    lat, lon = (qs.get("mlat") or [""])[0], (qs.get("mlon") or [""])[0]
    if lat and lon:
        return _point(lat, lon)
    return None


def backfill(apps, schema_editor):
    Metering = apps.get_model("metering", "Metering")
    for pk, link in (
        Metering.objects.filter(lat__isnull=True, address_link__isnull=False)
        .exclude(address_link="")
        .values_list("pk", "address_link")
        .iterator()
    ):
        point = parse_exact(link)
        if point:
            Metering.objects.filter(pk=pk).update(lat=point[0], lon=point[1])


class Migration(migrations.Migration):

    dependencies = [
        ("metering", "0012_metering_location"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
