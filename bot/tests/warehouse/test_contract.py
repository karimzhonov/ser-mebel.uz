"""docs/bot_contract fixtures of the warehouse DTOs through the bot's renderers/handlers."""

from bot.warehouse import keyboards as K
from bot.warehouse import texts as T

from .conftest import cbs, fx

DETAIL = fx("misc.wh_product_detail_response.json")
PRODUCT = fx("dto.wh_product.1.json")
MOVEMENT = fx("dto.wh_movement.1.json")


def test_card_text_and_keyboard_from_fixture():
    text = T.card(PRODUCT)
    assert "LDSP oq 16 mm" in text and "LD-016" in text and "42" in text
    assert len(text) <= 1024
    kb = K.card_kb(PRODUCT)
    assert "wh:g:31" in cbs(kb) and "wh:h:31:1" in cbs(kb)
    assert all(len(c.encode()) <= 64 for c in cbs(kb))
    urls = [b.url for r in kb.inline_keyboard for b in r if b.url]
    assert urls == [PRODUCT["url"]]


def test_movement_and_summary_render():
    assert "412" in T.move_line(MOVEMENT)
    s = T.summary_text(fx("misc.wh_summary_response.json"))
    assert "182" in s and "week" not in s and "shu hafta" in s


def test_moves_keyboard_from_detail_recent():
    res = {"items": DETAIL["recent"], "page": 1, "pages": 1}
    assert "wh:cx:412" in cbs(K.moves_kb(31, res))
    assert "412" in T.moves_text("X", res)


def test_gallery_keyboard_from_detail():
    kb = cbs(K.gallery_kb(DETAIL["product"]["photos"], 31))
    assert "wh:pd:12" in kb and "wh:pc:13" in kb and "wh:pc:12" not in kb


async def test_detail_fixture_drives_card_and_gallery(wh):
    wh.backend.routes[("GET", "warehouse/products/31/")] = DETAIL
    for i in (12, 13):
        wh.backend.routes[("POST", f"warehouse/photos/{i}/tg-file/")] = None
    await wh.cb("wh:p:31")
    assert wh.session.photos()[-1].photo == "AgACAgIAAxkBAAIB"
    await wh.cb("wh:g:31")
    (grp,) = wh.session.groups()  # photo 13 has no cached id -> bytes
    assert len(grp.media) == 2


async def test_kirim_body_matches_request_fixture_shape(wh):
    req = fx("misc.wh_movement_request.json")
    wh.backend.routes[("GET", "warehouse/products/31/")] = DETAIL
    wh.backend.routes[("GET", "warehouse/meta/")] = {
        "usd_rate": "12650.0000",
        "units": [],
        "categories": [],
    }
    wh.backend.routes[("POST", "warehouse/movements/")] = fx("misc.wh_movement_response.json")
    await wh.cb("wh:i:31")
    await wh.text("12,5")
    await wh.text("185000")
    await wh.text("Kronospan")
    await wh.cb("wh:ok")
    (call,) = wh.backend.to("warehouse/movements/")
    allowed = {
        "product",
        "kind",
        "quantity",
        "currency",
        "unit_price",
        "orig_price",
        "counterparty",
    }
    assert set(call[2]) <= allowed and "allocations" not in call[2]
    assert call[2]["product"] == req["product"] and call[2]["kind"] == "in"
    assert call[2]["counterparty"] == "Kronospan"
    assert await wh.state() is None  # response fixture parsed into a fresh card


async def test_chiqim_body_matches_request_fixture_shape(wh):
    req = fx("misc.wh_movement_request.json")
    detail = {**DETAIL, "product": {**DETAIL["product"], "quantity": "50.000"}}
    wh.backend.routes[("GET", "warehouse/products/31/")] = detail
    wh.backend.routes[("GET", "warehouse/meta/")] = {"usd_rate": "1", "units": [], "categories": []}
    refs = [{"ref": a["ref"], "client": "X"} for a in req["allocations"]]
    wh.backend.routes[("GET", "warehouse/orders/")] = {"items": refs}
    wh.backend.routes[("POST", "warehouse/movements/")] = fx("misc.wh_movement_response.json")
    await wh.cb("wh:o:31")
    for i in range(len(refs)):
        await wh.cb(f"wh:ot:0:{i}")
    await wh.cb("wh:on")
    for a in req["allocations"]:
        await wh.text(a["quantity"])
    await wh.text(req["counterparty"])
    await wh.cb("wh:ok")
    (call,) = wh.backend.to("warehouse/movements/")
    assert set(call[2]) <= set(req) and call[2]["allocations"] == req["allocations"]
    assert call[2]["kind"] == "out" and "quantity" not in call[2]


def test_whoami_fixture_has_keeper_flag():
    from bot.common.actor import Actor  # noqa: F401

    assert "is_keeper" in fx("misc.whoami_response.json")["warehouse"]
