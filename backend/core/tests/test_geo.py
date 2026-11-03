from decimal import Decimal

import pytest

from core import geo
from core.exceptions import ServiceError
from core.geo import MapPoint, copy_location, is_short_link, location_input, parse_map_point

LAT, LON = Decimal("41.311081"), Decimal("69.279737")


@pytest.mark.parametrize(
    "text",
    [
        "https://www.google.com/maps/place/X/@41.311081,69.279737,17z/data=!3m1!4b1",
        "https://www.google.com/maps?q=41.311081,69.279737",
        "https://maps.google.com/maps/place/X/?ll=41.311081,69.279737&z=10",
        "https://www.google.com/maps/dir/?api=1&destination=41.311081,69.279737",
        "https://www.google.com/maps/search/41.311081,+69.279737",
        "https://www.google.com/maps/place/X/@0.5,0.5,17z/data=!3d41.311081!4d69.279737",
        "https://yandex.uz/maps/10335/tashkent/?ll=69.279737%2C41.311081&z=17",
        "https://yandex.ru/maps/?pt=69.279737,41.311081&z=16",
        "https://yandex.uz/maps/?whatshere[point]=69.279737,41.311081&whatshere[zoom]=17",
        "https://yandex.uz/maps/?rtext=41.0,69.0~41.311081,69.279737",
        "https://maps.apple.com/?ll=41.311081,69.279737",
        "https://maps.apple.com/?q=41.311081,69.279737",
        "https://2gis.uz/tashkent?m=69.279737,41.311081/17",
        "https://www.openstreetmap.org/?mlat=41.311081&mlon=69.279737",
        "https://www.openstreetmap.org/#map=17/41.311081/69.279737",
        "geo:41.311081,69.279737",
        "41.311081, 69.279737",
        "41.311081 69.279737",
        "41.311081;69.279737",
        "69.279737, 41.311081",  # typed lon,lat: swapped back
        "Manzil mana: https://yandex.ru/maps/?pt=69.279737,41.311081 rahmat",
    ],
)
def test_parse_variants(text):
    p = parse_map_point(text)
    assert p == MapPoint(LAT, LON), text


def test_pt_wins_over_ll_in_yandex():
    url = "https://yandex.uz/maps/?ll=1.0,2.0&pt=69.279737,41.311081"
    assert parse_map_point(url) == MapPoint(LAT, LON)


def test_dms():
    p = parse_map_point("41°18'40.0\"N 69°16'47.3\"E")
    assert abs(p.lat - Decimal("41.311111")) < Decimal("0.00001")
    assert abs(p.lon - Decimal("69.279806")) < Decimal("0.00001")


@pytest.mark.parametrize(
    "text",
    ["", "salom", "0,0", "95, 20", "41.3, 190", "https://example.com/x", "12"],
)
def test_parse_rejects(text):
    assert parse_map_point(text) is None


def test_point_is_quantized_and_validated():
    p = MapPoint("41.3110815", "69.2797374")
    assert p.lat == Decimal("41.311082") and p.lon_str == "69.279737"
    with pytest.raises(ValueError):
        MapPoint(0, 0)
    with pytest.raises(ValueError):
        MapPoint(91, 10)


def test_short_links_are_not_resolved():
    for url in (
        "https://maps.app.goo.gl/abc123",
        "https://goo.gl/maps/abc",
        "https://yandex.uz/maps/-/CCUKAZiZ",
        "https://go.2gis.com/xyz",
    ):
        assert is_short_link(url)
        assert parse_map_point(url) is None
    assert not is_short_link("https://yandex.uz/maps/?pt=1,2")


def test_location_input():
    point, link, short = location_input("https://yandex.ru/maps/?pt=69.279737,41.311081")
    assert point == MapPoint(LAT, LON) and link.startswith("https://yandex.ru") and not short
    point, link, short = location_input("41.311081, 69.279737")
    assert point == MapPoint(LAT, LON) and link is None and not short
    assert location_input("  ") == (None, None, False)
    point, link, short = location_input("https://maps.app.goo.gl/abc")
    assert point is None and link == "https://maps.app.goo.gl/abc" and short
    with pytest.raises(ServiceError) as e:
        location_input("hech narsa")
    assert e.value.message == "Xarita havolasi yoki koordinata tushunilmadi"
    with pytest.raises(ServiceError):
        location_input("https://example.com/page")


def test_yandex_url_is_lon_first():
    assert geo.yandex_url(LAT, LON) == (
        "https://yandex.uz/maps/?ll=69.279737,41.311081&pt=69.279737,41.311081&z=17&l=map"
    )
    y = "https://yandex.uz/maps/?text=abc"
    assert geo.yandex_url(None, None, "Chilonzor 5", y) == y
    assert geo.yandex_url(None, None, "Chilonzor 5", "https://goo.gl/maps/x") == (
        "https://yandex.uz/maps/?text=Chilonzor%205&ll=69.279737,41.311081&z=12"
    )
    assert geo.yandex_url(None, None, "", "https://goo.gl/maps/x") == "https://goo.gl/maps/x"
    assert geo.yandex_url(None, None, "", "") is None
    assert "google.com" not in geo.yandex_url(LAT, LON, "x", "https://google.com/maps")


class Box:
    def __init__(self, lat=None, lon=None, address="", address_link=None):
        self.lat, self.lon, self.address, self.address_link = lat, lon, address, address_link


def test_copy_location_never_overwrites_an_existing_point():
    src = Box(LAT, LON, "Chilonzor", "https://yandex.ru/maps/?pt=1,2")
    dst = Box()
    assert set(copy_location(src, dst)) == {"lat", "lon", "address_link", "address"}
    assert (dst.lat, dst.address, dst.address_link) == (LAT, "Chilonzor", src.address_link)

    own = Box(Decimal("40.1"), Decimal("68.2"), "Mening manzilim", "https://x.uz/own")
    assert copy_location(src, own) == []
    assert own.lat == Decimal("40.1") and own.address == "Mening manzilim"
    # a point-less dst with a typed address keeps its address
    typed = Box(address="Yozilgan")
    copy_location(src, typed)
    assert typed.address == "Yozilgan" and typed.lat == LAT
    assert copy_location(src, Box(LAT, LON, "a", src.address_link)) == []


@pytest.mark.parametrize(
    "url,expected",
    [
        # route: the end point wins over the viewport centre
        (
            "https://yandex.uz/maps/?ll=69.279737,41.311081&rtext=41.30,69.24~41.35,69.33",
            MapPoint("41.35", "69.33"),
        ),
        # search / view centre links are no exact point
        ("https://yandex.uz/maps/10335/tashkent/search/Chilonzor%2019/?ll=69.2,41.3&z=12", None),
        ("https://yandex.uz/maps/?ll=69.2,41.3&text=mebel&z=17", None),
        ("https://yandex.uz/maps/?ll=69.2,41.3&z=12", None),
        ("https://yandex.uz/maps/org/x/123/?ll=69.2,41.3&z=12", MapPoint("41.3", "69.2")),
        ("https://yandex.uz/maps/?ll=69.2,41.3&z=17", MapPoint("41.3", "69.2")),
        ("https://yandex.uz/maps/?whatshere[point]=69.2,41.3", MapPoint("41.3", "69.2")),
        ("https://www.google.com/maps/search/mebel/@41.3111,69.2797,13z", None),
        ("https://www.google.com/maps/@41.3111,69.2797,13z", None),
        (
            "https://www.google.com/maps/place/X/@41.3111,69.2797,13z",
            MapPoint("41.3111", "69.2797"),
        ),
        (
            "https://www.google.com/maps/place/X/@41.0,69.0,13z/data=!3d41.3111!4d69.2797",
            MapPoint("41.3111", "69.2797"),
        ),
        ("https://www.google.com/maps/dir/?api=1&destination=41.3,69.2", MapPoint("41.3", "69.2")),
        ("https://www.google.com/maps?q=41.3,69.2&ll=1,2", MapPoint("41.3", "69.2")),
        ("https://www.google.com/maps?ll=41.3,69.2&z=10", None),
        ("https://yandex.evil.com/maps/?pt=69.2,41.3", None),
        ("https://notgoogle.com/maps?q=41.3,69.2", None),
        ("https://m.yandex.uz/maps/?pt=69.2,41.3", MapPoint("41.3", "69.2")),
    ],
)
def test_exact_marker_vs_view_centre(url, expected):
    assert parse_map_point(url) == expected


def test_dms_and_decimal_hemispheres():
    assert parse_map_point("41.31°N 69.27°E") == MapPoint("41.31", "69.27")
    assert parse_map_point("41°18'40\"N 69°16'47\"E") is not None
    assert parse_map_point("41.5°30'N 69°E") is None  # fractional degrees + minutes


def test_swap_only_into_uzbekistan():
    assert parse_map_point("55.75, 37.62") == MapPoint("55.75", "37.62")
    assert parse_map_point("69.279737, 41.311081") == MapPoint(LAT, LON)


def test_pair_with_long_whitespace_is_fast_and_valid():
    assert parse_map_point("41.3" + " " * 5000 + "69.2") == MapPoint("41.3", "69.2")
    assert parse_map_point("41.3" + " " * 5000 + "x") is None


def test_yandex_url_only_http():
    assert geo.yandex_url(None, None, "", "javascript:alert(1)") is None
    assert geo.yandex_url(None, None, "", "ftp://yandex.uz/x") is None
    assert (
        geo.yandex_url(None, None, "", "https://yandex.evil.com/x") == "https://yandex.evil.com/x"
    )


def test_resolve_location_keeps_link_for_same_point():
    box = Box(LAT, LON, "", "https://yandex.uz/maps/-/abc")
    assert geo.resolve_location(box, MapPoint(LAT, LON), None)[2] == box.address_link
    assert geo.resolve_location(box, MapPoint("40", "68"), None)[2] is None
    assert geo.resolve_location(box, geo.UNSET, geo.UNSET) == (LAT, LON, box.address_link)


def test_google_query_address_starting_with_numbers_is_not_a_point():
    from core.geo import parse_map_point

    assert parse_map_point("https://www.google.com/maps/search/?api=1&query=12+34+Navoi") is None
    p = parse_map_point("https://www.google.com/maps/search/?api=1&query=41.311081,69.279737")
    assert (str(p.lat), str(p.lon)) == ("41.311081", "69.279737")
