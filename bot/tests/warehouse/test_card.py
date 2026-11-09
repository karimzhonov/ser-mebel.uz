"""Product card / gallery: cached tg_file_id, bytes fallback, stale id, no photos."""

from .conftest import PRODUCT, cbs, photo, with_photos

TG_FILE = lambda i: ("POST", f"warehouse/photos/{i}/tg-file/")  # noqa: E731


def detail(wh, product):
    wh.backend.routes[("GET", "warehouse/products/5/")] = {
        "product": product,
        "last_in": None,
        "recent": [],
    }


def raw_fetches(wh):
    return [c for c in wh.backend.calls if c[1].endswith("/file/")]


async def test_cached_file_id_is_sent_without_backend_fetch(wh):
    detail(wh, with_photos(photo(12, 0, "CACHED")))
    await wh.cb("wh:p:5")
    (sent,) = wh.session.photos()
    assert sent.photo == "CACHED"
    assert "DSP 18mm" in sent.caption
    assert "wh:i:5" in cbs(sent.reply_markup)
    assert raw_fetches(wh) == []


async def test_no_cached_id_fetches_bytes_and_caches_new_file_id(wh):
    detail(wh, with_photos(photo(12, 0, "")))
    wh.backend.routes[TG_FILE(12)] = None
    wh.raw[12] = b"JPEGBYTES"
    await wh.cb("wh:p:5")
    (sent,) = wh.session.photos()
    assert sent.photo.data == b"JPEGBYTES"
    (call,) = wh.backend.to("warehouse/photos/12/tg-file/")
    assert call[0] == "POST" and call[2]["file_id"].startswith("new")


async def test_stale_file_id_falls_back_to_bytes(wh):
    detail(wh, with_photos(photo(12, 0, "STALE")))
    wh.session.bad_ids.add("STALE")
    wh.backend.routes[TG_FILE(12)] = None
    await wh.cb("wh:p:5")
    sent = wh.session.photos()
    assert sent[0].photo == "STALE"  # tried first
    assert sent[1].photo.data == b"BACKENDJPEG"  # then the bytes
    assert len(raw_fetches(wh)) == 1
    assert len(wh.backend.to("warehouse/photos/12/tg-file/")) == 1


async def test_no_photos_is_a_text_card(wh):
    detail(wh, PRODUCT)
    await wh.cb("wh:p:5")
    assert wh.session.photos() == []
    assert "Qoldiq" in wh.session.texts()[-1]
    assert raw_fetches(wh) == []


async def test_showing_a_card_remembers_current_product(wh):
    from bot.common.rds import get_redis

    detail(wh, PRODUCT)
    await wh.cb("wh:p:5")
    assert await get_redis().get("wh:cur:555") == b"5"
    assert 0 < await get_redis().ttl("wh:cur:555") <= 1800


async def test_gallery_single_photo(wh):
    detail(wh, with_photos(photo(12, 0, "C1")))
    await wh.cb("wh:g:5")
    (sent,) = wh.session.photos()
    assert sent.photo == "C1"
    assert wh.session.groups() == []
    assert "wh:pd:12" in cbs(wh.session.sent()[-1].reply_markup)
    assert not any(c.startswith("wh:pc:") for c in cbs(wh.session.sent()[-1].reply_markup))


async def test_gallery_three_photos_media_group_and_buttons(wh):
    detail(wh, with_photos(photo(1, 0, "A"), photo(2, 1, "B"), photo(3, 2, "C")))
    await wh.cb("wh:g:5")
    (grp,) = wh.session.groups()
    assert [m.media for m in grp.media] == ["A", "B", "C"]
    kb = cbs(wh.session.sent()[-1].reply_markup)
    assert {"wh:pc:2", "wh:pc:3", "wh:pd:1", "wh:pd:2", "wh:pd:3"} <= set(kb)
    assert "wh:pc:1" not in kb  # the cover has no ⭐


async def test_gallery_without_cached_ids_caches_each(wh):
    detail(wh, with_photos(photo(1, 0, ""), photo(2, 1, "")))
    for i in (1, 2):
        wh.backend.routes[TG_FILE(i)] = None
    await wh.cb("wh:g:5")
    assert len(wh.session.groups()) == 1
    assert len(raw_fetches(wh)) == 2
    ids = [c[2]["file_id"] for c in wh.backend.calls if c[1].endswith("/tg-file/")]
    assert ids == ["grp0", "grp1"]


async def test_gallery_without_photos(wh):
    detail(wh, PRODUCT)
    await wh.cb("wh:g:5")
    assert wh.session.texts()[-1] == "Rasm yo'q."


async def test_cover_and_delete_confirm(wh):
    p2 = with_photos(photo(2, 0, "B"))
    wh.backend.routes[("POST", "warehouse/photos/2/cover/")] = {"product": p2}
    wh.backend.routes[("DELETE", "warehouse/photos/2/")] = {"product": PRODUCT}
    await wh.cb("wh:pc:2")
    assert wh.session.photos()[-1].photo == "B"
    await wh.cb("wh:pd:2")
    assert wh.backend.to("warehouse/photos/2/") == []  # only asked
    assert "wh:pdy:2" in cbs(wh.session.edits()[-1].reply_markup)
    await wh.cb("wh:pdy:2")
    assert len(wh.backend.to("warehouse/photos/2/")) == 1
