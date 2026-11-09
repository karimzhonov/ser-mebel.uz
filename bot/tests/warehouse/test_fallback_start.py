"""Fallback router (search / stray photo), the /start variants and the menu button."""

from bot.common.rds import get_redis
from bot.warehouse import photos as P

from .conftest import PRODUCT, cbs, fx

FIN = fx("dto.member.1")
LISTING = {
    "items": [
        {**PRODUCT, "id": 5},
        {**PRODUCT, "id": 6, "name": "DSP 16mm"},
    ],
    "page": 1,
    "pages": 1,
    "total": 2,
}


def products(wh):
    wh.backend.routes[("GET", "warehouse/products/")] = LISTING
    wh.backend.routes[("GET", "warehouse/products/5/")] = {
        "product": PRODUCT,
        "last_in": None,
        "recent": [],
    }


def searched(wh):
    return wh.backend.to("warehouse/products/")


STRAY = {"photo": [{"file_id": "STRAYFID", "file_unique_id": "s", "width": 9, "height": 9}]}


# ------------------------------------------------------------------ free text -> search
async def test_keeper_free_text_searches(wh):
    products(wh)
    await wh.text("dsp")
    (call,) = searched(wh)
    assert call[3] == {"q": "dsp", "page": 1}
    kb = cbs(wh.session.sent()[-1].reply_markup)
    assert "wh:p:5" in kb and "wh:p:6" in kb


async def test_finance_member_keeper_text_is_not_searched(wh):
    products(wh)
    wh.backend.who["finance_member"] = FIN
    await wh.text("dsp")
    assert searched(wh) == []


async def test_finance_state_of_a_member_keeper_still_reaches_finance(wh):
    products(wh)
    wh.backend.who["finance_member"] = FIN
    await wh.set_state("Tx:amount", t="expense", amount=None)
    await wh.text("5000")
    assert searched(wh) == []
    assert not any(c.startswith("wh:") for s in wh.session.sent() for c in cbs(s.reply_markup))
    assert wh.session.sent()  # finance reacted (asked for the next step)


async def test_hr_answer_of_an_employee_keeper_is_not_stolen(wh):
    products(wh)
    wh.backend.who["hr"] = {"employee": {"telegram_id": 555, "name": "A"}, "is_admin": False}
    from bot.backend.client import backend as real

    orig = real.request

    async def hr_handles(method, path, **kw):
        if path == "hr/private-text/":
            wh.backend.calls.append((method, path, kw.get("json"), None))
            return {"handled": True, "outcome": "late_comment", "data": {}}
        return await orig(method, path, **kw)

    import pytest

    mp = pytest.MonkeyPatch()
    mp.setattr(real, "request", hr_handles)
    try:
        await wh.text("kech qolaman")
    finally:
        mp.undo()
    assert len(wh.backend.to("hr/private-text/")) == 1
    assert searched(wh) == []


async def test_employee_keeper_unhandled_hr_text_falls_to_search(wh):
    products(wh)
    wh.backend.who["hr"] = {"employee": {"telegram_id": 555, "name": "A"}, "is_admin": False}
    await wh.text("dsp")  # HR says handled=false -> warehouse search
    assert len(wh.backend.to("hr/private-text/")) == 1
    assert len(searched(wh)) == 1


async def test_non_keeper_text_is_silent(wh):
    wh.backend.who["warehouse"] = {"is_keeper": False}
    await wh.text("dsp")
    assert wh.session.sent() == []
    assert searched(wh) == []


async def test_commands_and_forwards_are_not_searched(wh):
    products(wh)
    await wh.text("/something")
    await wh.forward("dsp")
    assert searched(wh) == []


# ------------------------------------------------------------------ stray photo
async def test_stray_photo_offer_then_upload(wh):
    products(wh)
    wh.backend.routes[("POST", "warehouse/products/5/photos/")] = lambda j, p: {"product": PRODUCT}
    await P.set_current(555, 5)
    await wh.feed(message=wh._msg(**STRAY))
    assert wh.session.texts()[-1] == "Bu rasmni «DSP 18mm» ga qo'shaymi?"
    assert set(cbs(wh.session.sent()[-1].reply_markup)) == {"wh:at:5", "wh:atn"}
    assert await get_redis().get("wh:pend:555") == b"STRAYFID"
    await wh.cb("wh:at:5")
    ((path, js, files),) = wh.uploads
    assert path == "warehouse/products/5/photos/"
    assert js == {"tg_file_id": "STRAYFID"} and files["file"][1] == b"TGBYTES"
    assert await get_redis().get("wh:pend:555") is None


async def test_stray_photo_no_is_forgotten(wh):
    products(wh)
    await P.set_current(555, 5)
    await wh.feed(message=wh._msg(**STRAY))
    await wh.cb("wh:atn")
    assert await get_redis().get("wh:pend:555") is None
    assert wh.uploads == []


async def test_stray_photo_attach_expired(wh):
    await wh.cb("wh:at:5")
    assert wh.uploads == []
    assert wh.session.answers()[-1].show_alert


async def test_stray_photo_without_current_product_is_silent(wh):
    products(wh)
    await wh.feed(message=wh._msg(**STRAY))
    assert wh.session.sent() == []


async def test_finance_member_keeper_photo_is_not_offered(wh):
    products(wh)
    wh.backend.who["finance_member"] = FIN
    await P.set_current(555, 5)
    await wh.feed(message=wh._msg(**STRAY))
    assert not any("qo'shaymi" in (t or "") for t in wh.session.texts())
    assert await get_redis().get("wh:pend:555") is None


# ------------------------------------------------------------------ /start
async def test_start_keeper_only(wh):
    await wh.text("/start")
    first, second = wh.session.sent()[:2]
    assert [b.text for r in first.reply_markup.keyboard for b in r] == ["📦 Ombor"]
    assert "wh:q" in cbs(second.reply_markup)


async def test_start_keeper_and_finance_member(wh):
    wh.backend.who["finance_member"] = FIN
    wh.backend.routes[("GET", "finance/members/555/balance/")] = {"balance": "0"}
    await wh.text("/start")
    last = wh.session.sent()[-1]
    assert last.text == "📦 Ombor: /ombor"
    assert cbs(last.reply_markup) == ["wh:m"]


async def test_start_non_keeper_has_no_ombor(wh):
    wh.backend.who["warehouse"] = {"is_keeper": False}
    await wh.text("/start")
    assert not any("Ombor" in (t or "") for t in wh.session.texts())
    assert not any(c.startswith("wh:") for s in wh.session.sent() for c in cbs(s.reply_markup))


async def test_start_old_whoami_without_warehouse_key(wh):
    wh.backend.who.pop("warehouse")
    await wh.text("/start")
    assert not any(c.startswith("wh:") for s in wh.session.sent() for c in cbs(s.reply_markup))


# ------------------------------------------------------------------ menu button clears other FSM
async def test_menu_button_clears_other_modules_state(wh):
    await wh.set_state("OfferDue:custom")
    await wh.text("📦 Ombor")
    assert await wh.state() is None
    assert any("Ombor" in (t or "") for t in wh.session.texts())


async def test_menu_button_clears_finance_state_of_member_keeper(wh):
    wh.backend.who["finance_member"] = FIN
    await wh.set_state("Tx:amount", t="expense", amount=None)
    await wh.text("📦 Ombor")
    assert await wh.state() is None
    assert "wh:q" in cbs(wh.session.sent()[-1].reply_markup)


async def test_ombor_command(wh):
    await wh.text("/ombor")
    assert "wh:sm:d" in cbs(wh.session.sent()[-1].reply_markup)
