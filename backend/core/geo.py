"""Map points: parse what people paste (Google / Yandex / 2GIS / Apple / OSM links,
`geo:` URIs, plain coordinates, DMS) into a `MapPoint`, and build Yandex Maps links.

Pure functions: no database and no network. Short links (maps.app.goo.gl, ...) are not
resolved - they are kept as a link only (`is_short_link`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import parse_qs, quote, unquote, urlparse

from core.exceptions import ServiceError

UNSET = object()  # "argument not given" (None / "" are real values: clear)
_Q = Decimal("0.000001")
LINK_MAX = 1000
BAD_LOCATION = "Xarita havolasi yoki koordinata tushunilmadi"
TASHKENT_LL = "69.279737,41.311081"  # lon,lat

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_NUM = r"[-+]?\d{1,3}(?:\.\d+)?"
# Whitespace is collapsed to single spaces before matching, so the separator is
# unambiguous (no quadratic backtracking on long runs of spaces).
_PAIR = re.compile(rf"^({_NUM})(?: ?[,;] ?| )({_NUM})$")
_PAIR_PREFIX = re.compile(rf"^({_NUM})(?: ?[,;] ?| )({_NUM})(?![\d.])")
_DMS = re.compile(
    r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*[°º]\s*(?:(\d{1,2})\s*['′’]\s*)?"
    r"(?:(\d{1,2}(?:\.\d+)?)\s*(?:\"|″|”|'')\s*)?"
    r"([NSEWnsew])"
)
_YANDEX_HOST = re.compile(r"(?:^|\.)yandex\.(?:uz|ru|com|kz|by|com\.tr)$")
_GOOGLE_HOST = re.compile(r"(?:^|\.)google\.(?:com|co\.[a-z]{2}|com\.[a-z]{2}|[a-z]{2})$")
# Uzbekistan bounding box, used only to decide whether "lon, lat" was typed backwards.
_UZ_LAT = (Decimal("37.1"), Decimal("45.6"))
_UZ_LON = (Decimal("55.9"), Decimal("73.2"))


@dataclass(frozen=True)
class MapPoint:
    lat: Decimal
    lon: Decimal

    def __post_init__(self):
        lat, lon = _dec(self.lat), _dec(self.lon)
        if lat is None or lon is None:
            raise ValueError("bad coordinate")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("coordinate out of range")
        if lat == 0 and lon == 0:
            raise ValueError("null island")
        object.__setattr__(self, "lat", lat)
        object.__setattr__(self, "lon", lon)

    @property
    def lat_str(self) -> str:
        return f"{self.lat:.6f}"

    @property
    def lon_str(self) -> str:
        return f"{self.lon:.6f}"


def _dec(value) -> Decimal | None:
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite():
        return None
    return d.quantize(_Q, rounding=ROUND_HALF_UP)


def make_point(lat, lon) -> MapPoint | None:
    """MapPoint from two numbers/strings, None when invalid."""
    try:
        return MapPoint(lat, lon)
    except (ValueError, TypeError):
        return None


def coord_str(value) -> str | None:
    """A stored coordinate as a 6-place string (None stays None)."""
    return None if value is None else f"{Decimal(value):.6f}"


def _pair(a, b, *, lon_first=False) -> MapPoint | None:
    return make_point(b, a) if lon_first else make_point(a, b)


def _squash(text: str) -> str:
    return " ".join((text or "").split())


def _split_pair(value: str, *, lon_first=False, exact=False) -> MapPoint | None:
    """`exact`: the whole value must be the pair (free-text params like Google `q`
    may hold an address that merely starts with two numbers)."""
    text = _squash(unquote(value or "").replace("+", " "))
    m = (_PAIR if exact else _PAIR_PREFIX).match(text)
    if not m:
        return None
    return _pair(m[1], m[2], lon_first=lon_first)


def _first(qs: dict, *names):
    for name in names:
        values = qs.get(name)
        if values and values[0]:
            return values[0]
    return None


def is_yandex_host(host: str) -> bool:
    return bool(_YANDEX_HOST.search(host or ""))


def is_google_host(host: str) -> bool:
    host = host or ""
    return bool(_GOOGLE_HOST.search(host))


def _http(url) -> str | None:
    """The url when it is an http(s) link, else None (never hand out javascript: etc.)."""
    url = (url or "").strip()
    return url if urlparse(url).scheme.lower() in ("http", "https") and url else None


def _parse_google(url, host, qs, path):
    # The exact place marker wins over everything.
    m = re.search(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", url)
    if m:
        p = _pair(m[1], m[2])
        if p:
            return p
    # Explicit query / destination coordinates (not the view centre `ll` / `center`).
    for name in ("q", "query", "destination", "daddr"):
        v = _first(qs, name)
        if v:
            p = _split_pair(v, exact=True)
            if p:
                return p
    m = re.search(rf"/maps/(?:search|place)/({_NUM}),\+?({_NUM})", path)
    if m:
        return _pair(m[1], m[2])
    # `/@lat,lon`, `ll`, `center` are where the map is looking: a place only on /maps/place/.
    if "/maps/place/" in path:
        m = re.search(rf"/@({_NUM}),({_NUM})", path)
        if m:
            p = _pair(m[1], m[2])
            if p:
                return p
        for name in ("ll", "center"):
            v = _first(qs, name)
            if v:
                p = _split_pair(v)
                if p:
                    return p
    return None


def _parse_yandex(url, host, qs, path):
    for name in ("pt", "whatshere[point]"):
        v = _first(qs, name)
        if v:
            p = _split_pair(v, lon_first=True)
            if p:
                return p
    rtext = _first(qs, "rtext")
    if rtext:
        # a route: its end is the point, the `ll` is only the viewport
        return _split_pair(rtext.split("~")[-1])  # rtext is lat,lon
    v = _first(qs, "ll")
    if v and not _first(qs, "text") and _first(qs, "mode") != "search":
        try:
            z = float(_first(qs, "z") or 0)
        except ValueError:
            z = 0
        if "/org/" in path or "/house/" in path or z >= 16:
            return _split_pair(v, lon_first=True)
    return None


def _parse_apple(url, host, qs, path):
    for name in ("ll", "q", "sll", "daddr"):
        v = _first(qs, name)
        if v:
            p = _split_pair(v)
            if p:
                return p
    return None


def _parse_2gis(url, host, qs, path):
    v = _first(qs, "m")
    if v:
        p = _split_pair(v.split("/")[0], lon_first=True)
        if p:
            return p
    m = re.search(rf"[?&]m=({_NUM}),({_NUM})", unquote(url))
    if m:
        return _pair(m[1], m[2], lon_first=True)
    return None


def _parse_osm(url, host, qs, path, fragment=""):
    lat, lon = _first(qs, "mlat"), _first(qs, "mlon")
    if lat and lon:
        p = _pair(lat, lon)
        if p:
            return p
    m = re.search(rf"map=\d+/({_NUM})/({_NUM})", fragment or url)
    if m:
        return _pair(m[1], m[2])
    return None


def _in_uz(lat, lon) -> bool:
    return _UZ_LAT[0] <= lat <= _UZ_LAT[1] and _UZ_LON[0] <= lon <= _UZ_LON[1]


def _swap_guard(lat, lon):
    """A "lon, lat" typed backwards: swap only when that lands inside Uzbekistan and
    the order as typed does not."""
    try:
        a, b = Decimal(str(lat)), Decimal(str(lon))
    except InvalidOperation:
        return lat, lon
    if not _in_uz(a, b) and _in_uz(b, a):
        return lon, lat
    return lat, lon


def _dms(text: str) -> MapPoint | None:
    parts = _DMS.findall(_squash(text))
    if len(parts) != 2:
        return None
    vals = {}
    for deg, minutes, seconds, hemi in parts:
        if "." in deg and (minutes or seconds):
            return None  # fractional degrees can't also carry minutes / seconds
        v = Decimal(deg) + Decimal(minutes or 0) / 60 + Decimal(seconds or 0) / 3600
        hemi = hemi.upper()
        if hemi in "SW":
            v = -v
        vals["lat" if hemi in "NS" else "lon"] = v
    if set(vals) != {"lat", "lon"}:
        return None
    return make_point(vals["lat"], vals["lon"])


def extract_url(text: str) -> str | None:
    m = _URL_RE.search(text or "")
    return m[0].rstrip(".,;)") if m else None


def _parse_url(url: str) -> MapPoint | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    qs = parse_qs(parsed.query, keep_blank_values=False)
    path = unquote(parsed.path)
    decoded = unquote(url)
    if is_google_host(host):
        return _parse_google(decoded, host, qs, path)
    if is_yandex_host(host):
        return _parse_yandex(decoded, host, qs, path)
    if host == "apple.com" or host.endswith(".apple.com"):
        return _parse_apple(decoded, host, qs, path)
    if re.search(r"(?:^|\.)2gis\.(?:uz|ru|com)$", host):
        return _parse_2gis(decoded, host, qs, path)
    if host == "openstreetmap.org" or host.endswith(".openstreetmap.org"):
        return _parse_osm(decoded, host, qs, path, unquote(parsed.fragment))
    return None


def parse_map_point(text) -> MapPoint | None:
    """A map point from a pasted link or coordinates; None when nothing is recognised."""
    text = (text or "").strip()
    if not text:
        return None
    if text.lower().startswith("geo:"):
        m = re.match(rf"geo:({_NUM}),({_NUM})", text, re.I)
        return _pair(m[1], m[2]) if m else None
    url = extract_url(text)
    if url:
        return _parse_url(url)
    m = _PAIR.match(_squash(text))
    if m:
        lat, lon = _swap_guard(m[1], m[2])
        return make_point(lat, lon)
    return _dms(text)


def is_short_link(url) -> bool:
    host_path = urlparse(url or "")
    host = (host_path.hostname or "").lower()
    path = host_path.path or ""
    if host == "maps.app.goo.gl":
        return True
    if host in ("goo.gl", "www.goo.gl") and path.startswith("/maps"):
        return True
    if is_yandex_host(host) and path.startswith("/maps/-/"):
        return True
    return host == "go.2gis.com"


def location_input(text) -> tuple[MapPoint | None, str | None, bool]:
    """Panel/bot input -> (point, link, short).

    A URL is kept as `link` (the raw provenance) and parsed for a point; bare
    coordinates give a point only; empty = (None, None, False) = clear the location."""
    text = (text or "").strip()
    if not text:
        return None, None, False
    url = extract_url(text)
    if url:
        point = _parse_url(url)
        short = point is None and is_short_link(url)
        if point is None and not short:
            raise ServiceError(BAD_LOCATION)
        return point, url[:LINK_MAX], short
    point = parse_map_point(text)
    if point is None:
        raise ServiceError(BAD_LOCATION)
    return point, None, False


def yandex_url(lat=None, lon=None, address="", link="") -> str | None:
    """Where "open on the map" goes: the exact point, else the stored Yandex link, else
    a Yandex text search of the address (biased to Tashkent), else any stored link."""
    point = make_point(lat, lon) if lat is not None and lon is not None else None
    if point:
        ll = f"{point.lon_str},{point.lat_str}"
        return f"https://yandex.uz/maps/?ll={ll}&pt={ll}&z=17&l=map"
    link = _http(link) or ""
    host = (urlparse(link).hostname or "").lower() if link else ""
    if link and is_yandex_host(host):
        return link
    address = (address or "").strip()
    if address:
        return f"https://yandex.uz/maps/?text={quote(address)}&ll={TASHKENT_LL}&z=12"
    return link or None


def obj_map_url(obj) -> str | None:
    """yandex_url() for any model that has lat/lon/address/address_link."""
    return yandex_url(
        getattr(obj, "lat", None),
        getattr(obj, "lon", None),
        getattr(obj, "address", "") or "",
        getattr(obj, "address_link", "") or "",
    )


def resolve_location(locked, point, link):
    """The (lat, lon, address_link) a location edit leads to.

    `point is UNSET` keeps the stored point and link (address-only edit). A new link wins;
    without one the stored link survives only when the incoming point is the stored one
    (re-saving the prefilled "lat, lon"); otherwise it is stale and dropped."""
    if point is UNSET:
        return locked.lat, locked.lon, locked.address_link
    lat = point.lat if point else None
    lon = point.lon if point else None
    if link and link is not UNSET:
        return lat, lon, link
    if point is not None and (locked.lat, locked.lon) == (lat, lon):
        return lat, lon, locked.address_link
    return lat, lon, None


def copy_location(src, dst, *, only_blank: bool = True) -> list[str]:
    """Copy lat/lon/address_link (and address when dst's is blank) from src to dst.
    Never overwrites an existing point on dst when `only_blank`. Returns the changed
    field names; the caller saves."""
    changed: list[str] = []
    s_lat, s_lon = getattr(src, "lat", None), getattr(src, "lon", None)
    has_src_point = s_lat is not None and s_lon is not None
    has_dst_point = dst.lat is not None and dst.lon is not None
    if has_src_point and not (only_blank and has_dst_point):
        if dst.lat != s_lat or dst.lon != s_lon:
            dst.lat, dst.lon = s_lat, s_lon
            changed += ["lat", "lon"]
    link = getattr(src, "address_link", None)
    if link and not (only_blank and dst.address_link) and dst.address_link != link:
        dst.address_link = link
        changed.append("address_link")
    address = (getattr(src, "address", "") or "").strip()
    if address and not (dst.address or "").strip():
        meta = getattr(dst, "_meta", None)
        limit = getattr(meta.get_field("address"), "max_length", None) if meta else None
        dst.address = address[:limit] if limit else address
        changed.append("address")
    return changed
