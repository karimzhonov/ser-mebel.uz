"""«📷 Rasm qo'shish»: uploads through the real dispatcher (multipart to the backend)."""

from bot.backend.client import ServiceRefusal

from .conftest import PRODUCT, cbs, photo, with_photos

UP = ("POST", "warehouse/products/5/photos/")


def script(wh, product=PRODUCT):
    wh.backend.routes[("GET", "warehouse/products/5/")] = {
        "product": product,
        "last_in": None,
        "recent": [],
    }
    wh.backend.routes[UP] = lambda j, p: {
        "photo": photo(1),
        "product": with_photos(photo(1, tg="x")),
    }


def tg_photo(fid="big"):
    return {
        "photo": [
            {"file_id": "small", "file_unique_id": "a", "width": 90, "height": 90},
            {"file_id": fid, "file_unique_id": "b", "width": 800, "height": 800},
        ]
    }


def tg_doc(mime="image/png", size=1000):
    return {
        "document": {"file_id": "doc1", "file_unique_id": "d", "mime_type": mime, "file_size": size}
    }


async def test_photo_uploaded_multipart_with_tg_file_id(wh):
    script(wh)
    await wh.cb("wh:ph:5")
    assert await wh.state() == "WhPhoto:wait"
    await wh.feed(message=wh._msg(**tg_photo()))
    path, js, files = wh.uploads[0]
    assert path == "warehouse/products/5/photos/"
    assert js == {"tg_file_id": "big"}  # the largest size
    name, content, mime = files["file"]
    assert content == b"TGBYTES" and mime == "image/jpeg"
    assert "📷 1/5 qo'shildi" in wh.session.texts()
    assert await wh.state() == "WhPhoto:wait"  # stays for more
    assert "wh:ok:ph" in cbs(wh.session.sent()[-1].reply_markup)


async def test_image_document_uploaded_without_tg_file_id(wh):
    script(wh)
    await wh.cb("wh:ph:5")
    await wh.feed(message=wh._msg(**tg_doc("image/png")))
    path, js, files = wh.uploads[0]
    assert js is None
    assert files["file"][1] == b"TGBYTES"


async def test_non_supported_documents_are_refused_before_upload(wh):
    script(wh)
    await wh.cb("wh:ph:5")
    await wh.feed(message=wh._msg(**tg_doc("image/gif")))
    await wh.feed(message=wh._msg(**tg_doc("image/png", size=11 * 1024 * 1024)))
    await wh.feed(message=wh._msg(**tg_doc("application/pdf")))
    assert wh.uploads == []
    texts = wh.session.texts()
    assert any("rasm emas" in t for t in texts)  # gif
    assert any("10 MB" in t for t in texts)
    assert await wh.state() == "WhPhoto:wait"


async def test_text_in_photo_state_asks_for_picture(wh):
    script(wh)
    await wh.cb("wh:ph:5")
    await wh.text("salom")
    assert "Rasm yuboring" in wh.session.texts()[-1]
    assert wh.uploads == []


async def test_fifth_photo_finishes_and_shows_card(wh):
    script(wh)
    full = with_photos(*[photo(i, i, "t" if i == 0 else "") for i in range(5)])
    wh.backend.routes[UP] = lambda j, p: {"photo": photo(4, 4), "product": full}
    await wh.cb("wh:ph:5")
    await wh.feed(message=wh._msg(**tg_photo()))
    assert "📷 5/5 qo'shildi" in wh.session.texts()
    assert await wh.state() is None
    assert wh.session.photos()[-1].photo == "t"  # the card with the cover


async def test_backend_400_limit_is_shown(wh):
    script(wh)
    wh.backend.routes[UP] = ServiceRefusal(
        "Bitta mahsulotga 5 tadan ortiq rasm bo'lmaydi.", 400, "file"
    )
    await wh.cb("wh:ph:5")
    await wh.feed(message=wh._msg(**tg_photo()))
    assert wh.session.texts()[-1] == "❗ Bitta mahsulotga 5 tadan ortiq rasm bo'lmaydi."
    assert await wh.state() == "WhPhoto:wait"


async def test_done_button_shows_card_and_clears(wh):
    script(wh)
    await wh.cb("wh:ph:5")
    await wh.cb("wh:ok:ph")
    assert await wh.state() is None
    assert "DSP 18mm" in wh.session.texts()[-1]


async def test_start_refused_when_product_already_has_five(wh):
    script(wh, with_photos(*[photo(i, i) for i in range(5)]))
    await wh.cb("wh:ph:5")
    assert await wh.state() is None
    assert any("5 tadan" in (a.text or "") for a in wh.session.answers())
