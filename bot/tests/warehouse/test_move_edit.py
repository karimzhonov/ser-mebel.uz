"""Chiqim, new product, edit, active toggle, movement history / undo."""

import pytest

from bot.backend.client import Conflict, ServiceRefusal

from .conftest import PRODUCT, cbs

MOVE = {"movement": {"number": "K-1"}, "product": PRODUCT}


def product_routes(wh):
    wh.backend.routes[("GET", "warehouse/products/5/")] = {
        "product": PRODUCT,
        "last_in": None,
        "recent": [],
    }
    wh.backend.routes[("GET", "warehouse/meta/")] = {
        "usd_rate": "12650.0000",
        "units": [{"value": "dona", "label": "dona"}, {"value": "list", "label": "list"}],
        "categories": ["Plita", "Furnitura"],
        "max_photos": 5,
    }


# ------------------------------------------------------------------ chiqim (no client)
ORDERS = ("GET", "warehouse/orders/")
NOCLIENT_ITEMS = {"items": []}


async def _to_out_confirm(wh):
    wh.backend.routes[ORDERS] = NOCLIENT_ITEMS
    await wh.cb("wh:o:5")
    await wh.cb("wh:o0")
    await wh.text("3")
    await wh.cb("wh:sk")


async def test_chiqim_without_client_posts_quantity_no_price(wh):
    product_routes(wh)
    wh.backend.routes[("POST", "warehouse/movements/")] = MOVE
    wh.backend.routes[ORDERS] = NOCLIENT_ITEMS
    await wh.cb("wh:o:5")
    assert "Omborda: 10" in wh.session.texts()[-1]
    await wh.cb("wh:o0")
    await wh.text("3")
    await wh.text("Ali usta")  # to whom
    assert await wh.state() == "WhOut:confirm"
    assert "Jami: ≈" in wh.session.texts()[-1]
    await wh.cb("wh:ok")
    (call,) = wh.backend.to("warehouse/movements/")
    assert call[2] == {"product": 5, "kind": "out", "quantity": "3", "counterparty": "Ali usta"}
    assert not {"unit_price", "orig_price", "currency", "order_number"} & set(call[2])
    assert await wh.state() is None


async def test_chiqim_skips(wh):
    product_routes(wh)
    wh.backend.routes[("POST", "warehouse/movements/")] = MOVE
    await _to_out_confirm(wh)
    await wh.cb("wh:ok")
    (call,) = wh.backend.to("warehouse/movements/")
    assert call[2] == {"product": 5, "kind": "out", "quantity": "3"}


async def test_chiqim_400_on_quantity_reasks(wh):
    product_routes(wh)
    wh.backend.routes[("POST", "warehouse/movements/")] = ServiceRefusal(
        "Omborda yetarli emas", 400, "quantity"
    )
    await _to_out_confirm(wh)
    await wh.cb("wh:ok")
    assert await wh.state() == "WhOut:qty"
    assert "❗ Omborda yetarli emas" in wh.session.texts()[-1]
    assert "Necha" in wh.session.texts()[-1]


async def test_chiqim_other_400_ends_flow(wh):
    product_routes(wh)
    wh.backend.routes[("POST", "warehouse/movements/")] = ServiceRefusal(
        "Mahsulot faol emas", 400, ""
    )
    await _to_out_confirm(wh)
    await wh.cb("wh:ok")
    assert await wh.state() is None
    assert wh.session.texts()[-1] == "❗ Mahsulot faol emas"


async def test_bad_quantity_text_reasks(wh):
    product_routes(wh)
    wh.backend.routes[ORDERS] = NOCLIENT_ITEMS
    await wh.cb("wh:o:5")
    await wh.cb("wh:o0")
    await wh.text("abc")
    await wh.text("-2")
    assert await wh.state() == "WhOut:qty"
    assert wh.session.texts()[-1].startswith("Miqdorni raqam bilan")


async def test_kirim_usd_price_and_last_price_button(wh):
    product_routes(wh)
    wh.backend.routes[("GET", "warehouse/products/5/")] = {
        "product": PRODUCT,
        "last_in": {
            "unit_price": "151250.00",
            "currency": "USD",
            "orig_price": "12.10",
            "counterparty": "Kronospan",
            "date": "2026-11-07",
        },
        "recent": [],
    }
    wh.backend.routes[("POST", "warehouse/movements/")] = MOVE
    await wh.cb("wh:i:5")
    await wh.text("2")
    assert "Kurs: 1$ = 12" in wh.session.texts()[-1]  # rate line
    assert "wh:lp" in cbs(wh.session.sent()[-1].reply_markup)
    await wh.cb("wh:lp")
    assert "wh:lc" in cbs(wh.session.sent()[-1].reply_markup)
    await wh.cb("wh:lc")
    await wh.cb("wh:ok")
    (call,) = wh.backend.to("warehouse/movements/")
    assert call[2] == {
        "product": 5,
        "kind": "in",
        "quantity": "2",
        "currency": "USD",
        "orig_price": "12.10",
        "counterparty": "Kronospan",
    }


# ------------------------------------------------------------------ new product
async def test_new_product_full(wh):
    product_routes(wh)
    wh.backend.routes[("POST", "warehouse/products/")] = {"product": {**PRODUCT, "id": 9}}
    await wh.cb("wh:n")
    assert await wh.state() == "WhNew:name"
    await wh.text("Yangi DSP")
    assert await wh.state() == "WhNew:unit"
    await wh.cb("wh:un:list")
    assert await wh.state() == "WhNew:category"
    kb = cbs(wh.session.sent()[-1].reply_markup)
    assert "wh:ct:0" in kb and "wh:ct:1" in kb
    await wh.cb("wh:ct:1")  # by index -> "Furnitura"
    await wh.text("FX-1")
    await wh.text("3")
    (call,) = wh.backend.to("warehouse/products/")
    assert call[2] == {
        "name": "Yangi DSP",
        "unit": "list",
        "category": "Furnitura",
        "code": "FX-1",
        "min_quantity": "3",
    }
    assert await wh.state() == "WhPhoto:wait"


async def test_new_product_skips_and_photo_skip(wh):
    product_routes(wh)
    wh.backend.routes[("POST", "warehouse/products/")] = {"product": {**PRODUCT, "id": 5}}
    await wh.cb("wh:n")
    await wh.text("Mix")
    await wh.cb("wh:un:dona")
    for _ in range(3):  # category, code, min
        await wh.cb("wh:sk")
    (call,) = wh.backend.to("warehouse/products/")
    assert call[2] == {"name": "Mix", "unit": "dona"}
    assert await wh.state() == "WhPhoto:wait"
    await wh.cb("wh:sk")  # skip the photo step
    assert await wh.state() is None
    assert "DSP 18mm" in wh.session.texts()[-1]


async def test_new_product_400_on_code_goes_back(wh):
    product_routes(wh)
    wh.backend.routes[("POST", "warehouse/products/")] = ServiceRefusal("Kod band", 400, "code")
    await wh.cb("wh:n")
    await wh.text("Mix")
    await wh.cb("wh:un:dona")
    await wh.cb("wh:sk")
    await wh.cb("wh:sk")
    await wh.cb("wh:sk")
    assert await wh.state() == "WhNew:code"
    assert "❗ Kod band" in wh.session.texts()[-1]


async def test_new_product_category_index_out_of_range(wh):
    product_routes(wh)
    await wh.cb("wh:n")
    await wh.text("Mix")
    await wh.cb("wh:un:dona")
    await wh.cb("wh:ct:9")
    assert await wh.state() == "WhNew:category"


# ------------------------------------------------------------------ edit
async def test_edit_name_and_clear_code(wh):
    product_routes(wh)
    wh.backend.routes[("PATCH", "warehouse/products/5/")] = {"product": PRODUCT}
    await wh.cb("wh:ef:n:5")
    assert await wh.state() == "WhEdit:value"
    await wh.text("Boshqa nom")
    assert await wh.state() is None
    await wh.cb("wh:ef:c:5")
    await wh.text("-")
    bodies = [c[2] for c in wh.backend.to("warehouse/products/5/") if c[0] == "PATCH"]
    assert bodies == [{"name": "Boshqa nom"}, {"code": ""}]


async def test_edit_min_quantity_and_bad_value(wh):
    product_routes(wh)
    wh.backend.routes[("PATCH", "warehouse/products/5/")] = {"product": PRODUCT}
    await wh.cb("wh:ef:m:5")
    await wh.text("xyz")
    assert await wh.state() == "WhEdit:value"
    await wh.text("0")
    bodies = [c[2] for c in wh.backend.to("warehouse/products/5/") if c[0] == "PATCH"]
    assert bodies == [{"min_quantity": "0"}]


async def test_edit_unit_via_buttons(wh):
    product_routes(wh)
    wh.backend.routes[("PATCH", "warehouse/products/5/")] = {"product": PRODUCT}
    await wh.cb("wh:ef:u:5")
    assert "wh:eu:list:5" in cbs(wh.session.sent()[-1].reply_markup)
    await wh.cb("wh:eu:list:5")
    (call,) = [c for c in wh.backend.calls if c[0] == "PATCH"]
    assert call[2] == {"unit": "list"}


@pytest.mark.parametrize("active, expect", [(True, False), (False, True)])
async def test_active_toggle(wh, active, expect):
    p = {**PRODUCT, "is_active": active}
    wh.backend.routes[("GET", "warehouse/products/5/")] = {
        "product": p,
        "last_in": None,
        "recent": [],
    }
    wh.backend.routes[("PATCH", "warehouse/products/5/")] = {"product": {**p, "is_active": expect}}
    await wh.cb("wh:ea:5")
    (call,) = [c for c in wh.backend.calls if c[0] == "PATCH"]
    assert call[2] == {"is_active": expect}


# ------------------------------------------------------------------ movements undo
HIST = {
    "items": [
        {"number": "K-1", "kind": "in", "quantity": "2.000", "unit_label": "dona",
         "currency": "UZS", "unit_price": "100.00", "date": "2026-11-07", "is_cancelled": False},
        {"number": "K-0", "kind": "out", "quantity": "1.000", "unit_label": "dona",
         "date": "2026-11-06", "is_cancelled": True},
    ],
    "page": 1,
    "pages": 1,
    "total": 2,
}  # fmt: skip


async def test_history_offers_undo_only_for_live_rows(wh):
    product_routes(wh)
    wh.backend.routes[("GET", "warehouse/movements/")] = HIST
    await wh.cb("wh:h:5:1")
    kb = cbs(wh.session.edits()[-1].reply_markup)
    assert "wh:cx:K-1" in kb and "wh:cx:K-0" not in kb
    assert wh.backend.to("warehouse/movements/")[0][3] == {"product": 5, "page": 1}


async def test_cancel_confirm_then_post(wh):
    wh.backend.routes[("POST", "warehouse/movements/K-1/cancel/")] = {
        "movement": {"number": "K-1"},
        "product": PRODUCT,
    }
    await wh.cb("wh:cx:K-1")
    assert wh.backend.to("warehouse/movements/K-1/cancel/") == []
    assert "wh:cy:K-1" in cbs(wh.session.edits()[-1].reply_markup)
    await wh.cb("wh:cy:K-1")
    assert len(wh.backend.to("warehouse/movements/K-1/cancel/")) == 1
    assert "DSP 18mm" in wh.session.texts()[-1]  # fresh card


async def test_cancel_409_is_an_alert(wh):
    wh.backend.routes[("POST", "warehouse/movements/K-1/cancel/")] = Conflict(
        "Allaqachon bekor qilingan", 409
    )
    await wh.cb("wh:cy:K-1")
    a = wh.session.answers()[-1]
    assert a.show_alert and "Allaqachon" in a.text
    assert wh.session.sent() == []


async def test_cancel_400_negative_stock_is_an_alert(wh):
    wh.backend.routes[("POST", "warehouse/movements/K-1/cancel/")] = ServiceRefusal(
        "Qoldiq manfiy bo'ladi", 400, ""
    )
    await wh.cb("wh:cy:K-1")
    a = wh.session.answers()[-1]
    assert a.show_alert and "manfiy" in a.text
