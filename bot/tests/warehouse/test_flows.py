"""Keeper menu + kirim flow through the real dispatcher (scripted backend)."""

from .conftest import PRODUCT, cbs

MOVE = {"movement": {"number": "K-1"}, "product": PRODUCT}


def keeper(env, member=None):
    env.backend.who = {
        "finance_member": member,
        "hr": {"employee": None, "is_admin": False},
        "crm": {},
        "warehouse": {"is_keeper": True},
    }


async def test_menu_button_for_keeper(env):
    keeper(env)
    await env.text("📦 Ombor")
    assert "wh:q" in cbs(env.session.sent()[-1].reply_markup) or any(
        "wh:q" in cbs(c.reply_markup) for c in env.session.sent()
    )


async def test_not_keeper_gets_nothing_from_ombor(env):
    await env.text("📦 Ombor")
    assert env.session.texts() == ["Ombor faqat omborchi uchun."]


async def test_kirim_flow_posts_movement(env):
    keeper(env)
    env.backend.routes[("GET", "warehouse/products/5/")] = {
        "product": PRODUCT,
        "last_in": None,
        "recent": [],
    }
    env.backend.routes[("GET", "warehouse/meta/")] = {
        "usd_rate": "12650.0000",
        "units": [],
        "categories": [],
    }
    env.backend.routes[("POST", "warehouse/movements/")] = MOVE
    await env.cb("wh:i:5")
    assert await env.state() == "WhIn:qty"
    await env.text("2,5")
    await env.text("120 000 so'm")
    await env.text("O'tkazib")  # supplier
    assert await env.state() == "WhIn:confirm"
    await env.cb("wh:ok")
    (call,) = env.backend.to("warehouse/movements/")
    assert call[2] == {
        "product": 5,
        "kind": "in",
        "quantity": "2.5",
        "currency": "UZS",
        "unit_price": "120000.00",
        "counterparty": "O'tkazib",
    }
    assert await env.state() is None


async def test_other_flow_open_blocks_wh_button(env):
    keeper(env)
    await env.set_state("OfferDue:custom")
    await env.cb("wh:m")
    assert any("Avval" in (a.text or "") for a in env.session.answers())
