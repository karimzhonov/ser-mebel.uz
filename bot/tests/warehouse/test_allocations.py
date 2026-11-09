"""Chiqim for several client IDs: toggles, typed IDs, per-ID quantity, confirm, save."""

from bot.backend.client import ServiceRefusal
from bot.finance.texts import cat_label
from bot.warehouse import keyboards as K
from bot.warehouse import texts as T

from .conftest import PRODUCT, cbs
from .test_move_edit import MOVE, ORDERS, product_routes

R406 = {"ref": "406", "client": "Karimov", "bucket": "jarayonda", "status_label": "Jarayonda"}
R410 = {"ref": "410", "client": "Aliyev", "bucket": "yangi", "status_label": "Yangi"}
SM3 = {"ref": "SM-003", "client": "Usta", "bucket": "jarayonda", "status_label": "Jarayonda"}
MOV = ("POST", "warehouse/movements/")
RESOLVE = ("POST", "warehouse/orders/resolve/")


def setup(wh, items=(R406, R410, SM3)):
    product_routes(wh)
    wh.backend.routes[ORDERS] = {"items": list(items)}
    wh.backend.routes[MOV] = MOVE


def last_texts(wh):
    return wh.session.texts()[-1]


async def test_toggles_continue_per_ref_quantity_confirm_and_post(wh):
    setup(wh)
    await wh.cb("wh:o:5")
    assert await wh.state() == "WhOut:refs"
    kb = cbs(wh.session.sent()[-1].reply_markup)
    assert {"wh:ot:0:0", "wh:ot:0:1", "wh:ot:0:2", "wh:on", "wh:o0"} <= set(kb)
    await wh.cb("wh:ot:0:0")
    await wh.cb("wh:ot:0:2")
    await wh.cb("wh:ot:0:1")
    await wh.cb("wh:ot:0:1")  # toggled off again
    await wh.cb("wh:on")
    assert await wh.state() == "WhOut:alloc"
    assert "406" in last_texts(wh) and "qoldi: 10" in last_texts(wh)
    await wh.text("4")
    assert "SM-003" in last_texts(wh) and "qoldi: 6" in last_texts(wh)
    await wh.text("2")
    assert await wh.state() == "WhOut:party"
    await wh.cb("wh:sk")
    text = last_texts(wh)
    assert "406 Karimov — 4 dona ≈ 400 000 so'm" in text
    assert "SM-003 Usta — 2 dona" in text and "Jami: <b>6 dona</b>" in text
    await wh.cb("wh:ok")
    (call,) = wh.backend.to("warehouse/movements/")
    assert call[2] == {
        "product": 5,
        "kind": "out",
        "allocations": [
            {"ref": "406", "quantity": "4"},
            {"ref": "SM-003", "quantity": "2"},
        ],
    }
    assert "quantity" not in call[2]
    assert await wh.state() is None


async def test_typed_ids_resolve_selects_found_and_reports_unknown(wh):
    setup(wh, items=())
    wh.backend.routes[RESOLVE] = {"items": [R406, SM3], "unknown": ["999"]}
    await wh.cb("wh:o:5")
    await wh.text("406 SM-003 999")
    (call,) = wh.backend.to("warehouse/orders/resolve/")
    assert call[2] == {"text": "406 SM-003 999"}
    out = last_texts(wh)
    assert "Topilmadi: 999" in out and "Tanlangan: 406, SM-003" in out
    kb = cbs(wh.session.sent()[-1].reply_markup)
    assert "wh:ot:0:0" in kb and "wh:ot:0:1" in kb  # visible as toggles
    await wh.cb("wh:on")
    assert await wh.state() == "WhOut:alloc"


async def test_typed_name_searches_candidates(wh):
    setup(wh)
    await wh.cb("wh:o:5")
    wh.backend.routes[ORDERS] = {"items": [R410]}
    await wh.text("aliyev")
    assert wh.backend.to("warehouse/orders/")[-1][3] == {"q": "aliyev"}
    assert not wh.backend.to("warehouse/orders/resolve/")
    kb = wh.session.sent()[-1].reply_markup
    assert "410 · Aliyev" in [b.text for row in kb.inline_keyboard for b in row]


async def test_sum_over_stock_is_refused_locally(wh):
    setup(wh)
    await wh.cb("wh:o:5")
    await wh.cb("wh:ot:0:0")
    await wh.cb("wh:ot:0:1")
    await wh.cb("wh:on")
    await wh.text("8")
    await wh.text("3")  # only 2 left
    assert await wh.state() == "WhOut:alloc"
    assert "Omborda yetarli emas (qoldi: 2 dona)" in last_texts(wh)
    assert not wh.backend.to("warehouse/movements/")


async def test_davom_without_selection_alerts(wh):
    setup(wh)
    await wh.cb("wh:o:5")
    await wh.cb("wh:on")
    assert any(a.show_alert and "ID" in (a.text or "") for a in wh.session.answers())
    assert await wh.state() == "WhOut:refs"


async def test_no_client_path(wh):
    setup(wh)
    await wh.cb("wh:o:5")
    await wh.cb("wh:o0")
    assert await wh.state() == "WhOut:qty"
    await wh.text("2")
    await wh.cb("wh:sk")
    await wh.cb("wh:ok")
    (call,) = wh.backend.to("warehouse/movements/")
    assert call[2] == {"product": 5, "kind": "out", "quantity": "2"}


async def test_400_on_allocations_goes_back_to_refs_keeping_selection(wh):
    setup(wh)
    wh.backend.routes[MOV] = ServiceRefusal("«406» ID topilmadi.", 400, "allocations")
    await wh.cb("wh:o:5")
    await wh.cb("wh:ot:0:0")
    await wh.cb("wh:on")
    await wh.text("1")
    await wh.cb("wh:sk")
    await wh.cb("wh:ok")
    assert await wh.state() == "WhOut:refs"
    assert "❗ «406» ID topilmadi." in last_texts(wh) and "Tanlangan: 406" in last_texts(wh)


async def test_400_on_quantity_goes_back_to_first_alloc(wh):
    setup(wh)
    wh.backend.routes[MOV] = ServiceRefusal("Omborda yetarli emas", 400, "quantity")
    await wh.cb("wh:o:5")
    await wh.cb("wh:ot:0:0")
    await wh.cb("wh:on")
    await wh.text("1")
    await wh.cb("wh:sk")
    await wh.cb("wh:ok")
    assert await wh.state() == "WhOut:alloc"
    assert "406" in last_texts(wh) and "qoldi: 10" in last_texts(wh)


def test_callbacks_fit_64_bytes_with_cyrillic_manual_ref():
    cands = [{"ref": "СМ-" + "ё" * 28, "client": "Клиент " * 10} for _ in range(20)] + [R406]
    for page in (0, 1, 2):
        kb = K.orders_kb({"cands": cands, "sel": [cands[0]], "page": page})
        for row in kb.inline_keyboard:
            for b in row:
                assert len(b.callback_data.encode()) <= 64 and b.callback_data.startswith("wh:")


# ------------------------------------------------------------------ rendering
def test_move_line_renders_allocations():
    m = {
        "number": "C-1",
        "kind": "out",
        "quantity": "6.000",
        "unit_label": "dona",
        "date": "2026-11-09",
        "allocations": [
            {"ref": "406", "client": "Karimov", "quantity": "4.000", "total": "400000.00"},
            {"ref": "410", "client": "", "quantity": "2.000", "total": "200000.00"},
        ],
    }
    assert "406×4, 410×2" in T.move_line(m)
    assert "buyurtma" not in T.move_line({**m, "allocations": []})


def test_cat_label_renders_ombor_pseudo_category():
    assert cat_label({"code": "_ombor", "name": "Furnitura (ombor)", "emoji": "📦"}) == (
        "📦 Furnitura (ombor)"
    )
    assert cat_label("_ombor") == "📦 Furnitura (ombor)"


async def test_finance_order_card_shows_ombor_line_and_category():
    from bot.finance.handlers.views import render_order_card

    sent = []

    class FakeCtx:
        admin = False

        async def send(self, text, kb=None, **kw):
            sent.append(text)

    def card(wh):
        return {
            "ref": "406",
            "client": "Karimov",
            "bucket": "jarayonda",
            "price_uzs": "0",
            "stats": {
                "spent": "700000",
                "collected": "0",
                "warehouse": wh,
                "cats": [
                    {"code": "_ombor", "name": "Furnitura (ombor)", "emoji": "📦", "sum": "600000"}
                ],
                "last_ops": [],
            },
        }

    await render_order_card(FakeCtx(), card("600000"))
    assert "Ombordan" not in sent[-1]
    assert "📦 Furnitura (ombor) — 600 000" in sent[-1]


async def test_old_buttons_are_stale_after_a_search_replaces_candidates(wh):
    setup(wh)
    await wh.cb("wh:o:5")
    wh.backend.routes[ORDERS] = {"items": [R410]}
    await wh.text("aliyev")  # candidates replaced -> version 1
    kb = cbs(wh.session.sent()[-1].reply_markup)
    assert "wh:ot:1:0" in kb and "wh:ot:0:0" not in kb
    before = len(wh.session.answers())
    await wh.cb("wh:ot:0:0")  # button of the OLD list
    alerts = [a for a in wh.session.answers()[before:] if a.show_alert]
    assert alerts and alerts[-1].text == T.GONE
    await wh.cb("wh:op:0:0")
    assert [a for a in wh.session.answers() if a.show_alert][-1].text == T.GONE
    await wh.cb("wh:on")  # nothing was toggled
    assert [a for a in wh.session.answers() if a.show_alert][-1].text == T.NO_REFS


async def test_quantity_reask_refreshes_stock(wh):
    setup(wh)
    wh.backend.routes[MOV] = ServiceRefusal("Omborda yetarli emas", 400, "quantity")
    await wh.cb("wh:o:5")
    await wh.cb("wh:ot:0:0")
    await wh.cb("wh:on")
    await wh.text("1")
    await wh.cb("wh:sk")
    wh.backend.routes[("GET", "warehouse/products/5/")] = {
        "product": {**PRODUCT, "quantity": "0.500"},
        "last_in": None,
        "recent": [],
    }
    await wh.cb("wh:ok")
    assert "qoldi: 0.5" in last_texts(wh)
