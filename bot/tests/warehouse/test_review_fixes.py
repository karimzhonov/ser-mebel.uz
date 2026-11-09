"""Review round 1: start/menu keyboards, album tail, HTML-safe card, order number,
finance `_flow` key, ex-keeper refusal."""

import html
import re
from unittest.mock import AsyncMock

from aiogram.fsm.storage.base import StorageKey
from aiogram.types import InlineKeyboardMarkup

from bot.warehouse import texts as T

from .conftest import PRODUCT, cbs, photo, with_photos
from .test_photo_flow import UP, script, tg_photo


def inline_only(msgs):
    return all(isinstance(m.reply_markup, InlineKeyboardMarkup) for m in msgs if m.reply_markup)


# ------------------------------------------------------------------ /start branches
async def test_start_blocked_keeper_is_silent(wh):
    wh.backend.who["finance_member"] = {"role": "blocked", "is_active_member": False}
    await wh.text("/start")
    assert wh.session.sent() == []


async def test_start_employee_keeper_gets_employee_start_and_inline_hint(wh, monkeypatch):
    import bot.common.start as st

    es = AsyncMock(return_value=True)
    monkeypatch.setattr(st, "employee_start", es)
    wh.backend.who["hr"] = {"employee": {"id": 1}, "is_admin": False}
    await wh.text("/start")
    es.assert_awaited_once()
    (msg,) = wh.session.sent()
    assert "wh:m" in cbs(msg.reply_markup) and inline_only([msg])


async def test_start_crm_keeper_gets_crm_menu_and_inline_hint(wh):
    wh.backend.who["crm"] = {"can_add_lead": True}
    await wh.text("/start")
    last = wh.session.sent()[-1]
    assert "wh:m" in cbs(last.reply_markup) and inline_only([last])


async def test_menu_does_not_replace_hr_or_crm_keyboard(wh):
    wh.backend.who["crm"] = {"can_add_lead": True}
    await wh.text("📦 Ombor")
    assert inline_only(wh.session.sent())
    wh.session.calls.clear()
    wh.backend.who["crm"] = {}
    wh.backend.who["hr"] = {"employee": {"id": 1}, "is_admin": False}
    await wh.text("/ombor")
    assert inline_only(wh.session.sent())


# ------------------------------------------------------------------ album tail
async def test_album_tail_after_fifth_is_swallowed_once(wh):
    script(wh)
    full = with_photos(*[photo(i, i, "t" if i == 0 else "") for i in range(5)])
    wh.backend.routes[UP] = lambda j, p: {"photo": photo(4, 4), "product": full}
    await wh.cb("wh:ph:5")
    await wh.feed(message=wh._msg(media_group_id="g1", **tg_photo()))
    assert await wh.state() is None
    wh.session.calls.clear()
    wh.backend.calls.clear()
    for _ in range(2):
        await wh.feed(message=wh._msg(media_group_id="g1", **tg_photo()))
    limits = [t for t in wh.session.texts() if "5 tadan" in t]
    assert len(limits) == 1
    assert not wh.backend.to("warehouse/products/5/photos/")
    assert not wh.session.photos()


async def test_other_group_photo_is_not_swallowed(wh):
    from bot.common.rds import get_redis

    await get_redis().set("wh:mg:555", "g1", ex=60)
    wh.session.calls.clear()
    await wh.feed(message=wh._msg(media_group_id="other", **tg_photo()))
    assert not any("5 tadan" in t for t in wh.session.texts())


# ------------------------------------------------------------------ texts
def test_card_never_cuts_inside_entity():
    p = {**PRODUCT, "name": "&<" * 500, "code": "&" * 300, "category": "<" * 300}
    text = T.card(p)
    assert len(text) <= 1024
    assert re.findall(r"&(?!amp;|lt;|gt;)", text) == []
    assert text.count("<b>") == text.count("</b>") == 2
    html.unescape(text)


# ------------------------------------------------------------------ finance _flow key
async def test_menu_keeps_finance_flow_key(wh):
    key = StorageKey(bot_id=wh.bot.id, chat_id=555, user_id=555)
    await wh.dp.storage.set_data(key, {"_flow": "x"})
    await wh.text("📦 Ombor")
    assert await wh.dp.storage.get_data(key) == {"_flow": "x"}


async def test_begin_keeps_finance_flow_key(wh):
    key = StorageKey(bot_id=wh.bot.id, chat_id=555, user_id=555)
    await wh.dp.storage.set_data(key, {"_flow": "x"})
    wh.backend.routes[("GET", "warehouse/meta/")] = {"units": [], "categories": []}
    await wh.cb("wh:n")
    assert (await wh.dp.storage.get_data(key))["_flow"] == "x"


# ------------------------------------------------------------------ ex-keeper
async def test_ex_keeper_in_wh_state_is_cleared_and_told(wh):
    wh.backend.who["warehouse"] = {}
    await wh.set_state("WhIn:qty")
    await wh.text("5")
    assert wh.session.texts()[-1] == T.NOT_KEEPER
    assert await wh.state() is None


async def test_ex_keeper_button_is_refused(wh):
    wh.backend.who["warehouse"] = {}
    await wh.cb("wh:m")
    assert any(a.text == T.NOT_KEEPER for a in wh.session.answers())


async def test_non_keeper_other_text_untouched(wh):
    wh.backend.who["warehouse"] = {}
    await wh.text("salom")
    assert T.NOT_KEEPER not in wh.session.texts()
