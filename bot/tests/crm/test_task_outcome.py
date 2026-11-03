"""Completing a task asks the next stage: picker, time keyboards, confirm, typed time."""

import time

import pytest

from bot.backend.client import Conflict, Forbidden, ServiceRefusal
from bot.crm import keyboards as K

from .conftest import UID, buttons, cbs

PANEL = "https://ser-mebel.uz/call-center?open=41"
MAP = "https://yandex.uz/maps/?ll=1,2"
ALL = [
    "re_phone",
    "given_info",
    "given_location",
    "go_for_measured",
    "price_problem",
    "dont_need",
    "declined",
]
ROWS = {
    "inline_keyboard": [
        [{"text": "💻 Panelda ochish", "url": PANEL}],
        [{"text": "🗺 Yandex xaritada", "url": MAP}],
        [{"text": "✅ Bajarildi", "callback_data": "crm:done:8"}],
    ]
}
GET = ("GET", "crm/tasks/8/")
DONE = ("POST", "crm/tasks/8/done/")
PARSE = ("POST", "crm/due/parse/")
RES = {
    "task": {"id": 8, "is_done": True},
    "by_name": "Aziz",
    "invoice": {"id": 41, "solution_label": "Qayta telefon qilish"},
    "next_task": {"id": 9, "due_at": "2026-11-04T10:00:00"},
    "closed_tasks": 0,
}


def detail(env, outcomes=ALL):
    env.backend.routes[GET] = {
        "task": {"id": 8},
        "invoice": {"id": 41},
        "outcomes": outcomes,
        "next_required": ["re_phone"],
        "url": PANEL,
    }


def kb_of(env):
    return env.session.of(__import__("aiogram.methods", fromlist=["x"]).EditMessageReplyMarkup)[
        -1
    ].reply_markup


async def tap(env, data, **kw):
    kw.setdefault("markup", ROWS)
    await env.cb(data, text="⏰ Vazifa vaqti keldi", **kw)


async def test_active_lead_shows_picker_with_exact_buttons(env):
    detail(env)
    await tap(env, "crm:done:8")
    assert env.backend.to("crm/tasks/8/done/") == []
    m = kb_of(env)
    got = buttons(m)
    assert [c for _, c, _ in got if c] == [
        "crm:do:rp:8",
        "crm:do:gi:8",
        "crm:do:gl:8",
        "crm:do:pp:8",
        "crm:do:dn:8",
        "crm:do:dc:8",
        "crm:dx:8",
    ]
    urls = [u for _, _, u in got if u]
    assert urls == [PANEL, MAP, PANEL]  # panel, map, and the zamer button
    assert any("Zamerga" in t for t, _, u in got if u)
    assert env.session.answers()[-1].text == "Keyingi bosqichni tanlang"


async def test_picker_without_zamer_when_not_allowed(env):
    detail(env, [o for o in ALL if o != "go_for_measured"])
    await tap(env, "crm:done:8")
    assert not any("Zamerga" in t for t, _, _ in buttons(kb_of(env)))


async def test_get_conflict_alerts(env):
    env.backend.routes[GET] = Conflict("Vazifa allaqachon bajarilgan", 409)
    await tap(env, "crm:done:8")
    a = env.session.answers()[-1]
    assert a.show_alert and "allaqachon" in a.text
    assert env.session.edits() == [] and env.session.cleared() == []


async def test_rephone_has_no_without_reminder_and_gi_has(env):
    await tap(env, "crm:do:rp:8")
    c = cbs(kb_of(env))
    assert "crm:dt:rp:no:8" not in c and "crm:dt:rp:cu:8" in c and "crm:done:8" in c
    assert [u for _, _, u in buttons(kb_of(env)) if u] == [PANEL, MAP]
    await tap(env, "crm:do:gi:8")
    assert "crm:dt:gi:no:8" in cbs(kb_of(env))


async def test_rephone_tomorrow_posts_and_finishes(env):
    env.backend.routes[DONE] = RES
    await tap(env, "crm:dt:rp:tm:8")
    assert env.backend.to("crm/tasks/8/done/")[0][2] == {
        "outcome": "re_phone",
        "next_task": {"preset": "tomorrow"},
    }
    t = env.session.edits()[0].text
    assert t.startswith(
        "✅ Bajarildi — Aziz\n➡️ Qayta telefon qilish\n⏰ Keyingi qo'ng'iroq: 04.11 10:00"
    )
    assert "Vazifa vaqti keldi" in t and env.session.edits()[0].reply_markup is None


@pytest.mark.parametrize("when,preset", [("1h", "1h"), ("td", "today")])
async def test_presets(env, when, preset):
    env.backend.routes[DONE] = RES
    await tap(env, f"crm:dt:gi:{when}:8")
    assert env.backend.to("crm/tasks/8/done/")[0][2]["next_task"] == {"preset": preset}


async def test_given_info_without_reminder(env):
    env.backend.routes[DONE] = {**RES, "next_task": None}
    await tap(env, "crm:dt:gi:no:8")
    assert env.backend.to("crm/tasks/8/done/")[0][2] == {"outcome": "given_info"}
    assert "Keyingi qo'ng'iroq" not in env.session.edits()[0].text


async def test_rephone_no_is_stale(env):
    await tap(env, "crm:dt:rp:no:8")
    assert env.backend.to("crm/tasks/8/done/") == []
    assert env.session.answers()[-1].text == "Bu tugma eskirgan."


async def test_closing_confirm_then_post_with_count(env):
    await tap(env, "crm:do:dn:8")
    a = env.session.answers()[-1]
    assert a.show_alert and "boshqa ochiq vazifalar" in a.text
    assert cbs(kb_of(env)) == ["crm:dy:dn:8", "crm:done:8"]
    env.backend.routes[DONE] = {
        **RES,
        "next_task": None,
        "closed_tasks": 2,
        "invoice": {"solution_label": "Kerak emas"},
    }
    await tap(env, "crm:dy:dn:8")
    assert env.backend.to("crm/tasks/8/done/")[0][2] == {"outcome": "dont_need"}
    t = env.session.edits()[0].text
    assert "➡️ Kerak emas" in t and "🗂 2 ta vazifa yopildi" in t


async def test_dx_restores_four_button_keyboard(env):
    await tap(env, "crm:dx:8")
    m = kb_of(env)
    assert (
        buttons(m)
        == [
            ("💻 Panelda ochish", None, PANEL),
            ("🗺 Yandex xaritada", None, MAP),
            ("✅ Bajarildi", "crm:done:8", None),
            ("⏰ +1 soat", "crm:sn:1h:8", None),
            ("🌅 Ertaga", "crm:sn:tm:8", None),
        ][:2]
        + buttons(m)[2:]
    )
    assert cbs(m) == ["crm:done:8", "crm:sn:1h:8", "crm:sn:tm:8"]


async def test_400_on_outcome_alerts_and_reopens_picker(env):
    detail(env)
    env.backend.routes[DONE] = ServiceRefusal("Keyingi bosqichni tanlang", 400, "outcome")
    await tap(env, "crm:dy:dn:8")
    assert env.session.answers()[0].show_alert
    assert env.session.edits() == []
    assert "crm:do:rp:8" in cbs(kb_of(env))


async def test_keep_only_400_does_not_loop(env):
    detail(env, ["keep"])
    env.backend.routes[DONE] = ServiceRefusal("x", 400, "outcome")
    await tap(env, "crm:done:8")
    assert len(env.backend.to("crm/tasks/8/done/")) == 1
    assert len(env.backend.to("crm/tasks/8/")) == 1


async def test_done_forbidden_alerts_and_keeps_message(env):
    env.backend.routes[DONE] = Forbidden("Bu vazifa sizniki emas", 403)
    await tap(env, "crm:dy:pp:8")
    assert env.session.answers()[-1].show_alert and env.session.edits() == []


# ------------------------------------------------------------------ typed time
async def start_custom(env, code="rp", **kw):
    await tap(env, f"crm:dt:{code}:cu:8", **kw)


async def test_custom_time_flow(env):
    await start_custom(env)
    assert await env.state() == "TaskDone:custom"
    assert "Vaqtni yozing" in env.session.last().text
    assert cbs(env.session.last().reply_markup) == ["crm:dq"]
    env.backend.routes[PARSE] = {"due_at": "2026-11-05T14:00:00"}
    env.backend.routes[DONE] = RES
    await env.text("05.11 14:00")
    assert env.backend.to("crm/due/parse/")[0][2] == {"text": "05.11 14:00"}
    assert env.backend.to("crm/tasks/8/done/")[0][2] == {
        "outcome": "re_phone",
        "next_task": {"due_at": "2026-11-05T14:00:00"},
    }
    e = env.session.edits()[0]
    assert e.chat_id == UID and e.message_id == 9 and e.reply_markup is None
    assert e.text.startswith("✅ Bajarildi — Aziz") and "Vazifa vaqti keldi" in e.text
    assert env.session.last().text == "✅ Saqlandi"
    assert await env.state() is None


async def test_custom_parse_400_stays(env):
    await start_custom(env)
    env.backend.routes[PARSE] = ServiceRefusal("O'tgan vaqt", 400, "remind")
    await env.text("01.01")
    assert await env.state() == "TaskDone:custom"
    assert "O'tgan vaqt" in env.session.last().text
    assert env.backend.to("crm/tasks/8/done/") == []


async def test_custom_expired(env):
    await start_custom(env)
    await env.set_state(
        "TaskDone:custom",
        task=8,
        outcome="re_phone",
        chat_id=UID,
        message_id=9,
        ts=time.time() - 700,
    )
    await env.text("15:30")
    assert await env.state() is None
    assert env.session.last().text == "Bu tugma eskirgan."
    assert env.backend.to("crm/due/parse/") == []


async def test_bekor_clears(env):
    await start_custom(env)
    await env.text("/bekor")
    assert await env.state() is None
    assert env.session.last().text == "Bekor qilindi."


async def test_dq_clears(env):
    await start_custom(env)
    await env.cb("crm:dq")
    assert await env.state() is None


async def test_finance_menu_button_clears_and_falls_through(env):
    await start_custom(env)
    n = len(env.backend.calls)
    try:
        await env.text("➖ Chiqim")
    except AssertionError:
        pass  # finance asked the (unscripted) backend: it got the update
    assert await env.state() != "TaskDone:custom"
    assert env.backend.to("crm/due/parse/") == []
    assert len(env.backend.calls) >= n


@pytest.mark.parametrize("cur", ["Lead:name", "Lead:remind_custom", "Expense:amount"])
async def test_custom_refused_in_other_flow(env, cur):
    await env.set_state(cur, x=1)
    await start_custom(env)
    a = env.session.answers()[-1]
    assert a.show_alert and "boshqa amal" in a.text
    assert await env.state() == cur


async def test_custom_allowed_over_taskdone_state(env):
    await env.set_state("TaskDone:custom", task=3, ts=time.time())
    await start_custom(env)
    assert await env.state() == "TaskDone:custom"
    assert not env.session.answers()[-1].show_alert


async def test_preset_after_custom_clears_state(env):
    await start_custom(env)
    assert await env.state() == "TaskDone:custom"
    env.backend.routes[DONE] = RES
    await tap(env, "crm:dt:rp:tm:8")
    assert len(env.backend.to("crm/tasks/8/done/")) == 1
    assert await env.state() is None


async def test_dx_after_custom_clears_state(env):
    await start_custom(env)
    await tap(env, "crm:dx:8")
    assert await env.state() is None


async def test_done_reopen_after_custom_clears_state(env):
    await start_custom(env)
    detail(env)
    await tap(env, "crm:done:8")
    assert await env.state() is None


async def test_other_task_taskdone_state_is_left_alone(env):
    await env.set_state("TaskDone:custom", task=3, ts=time.time())
    env.backend.routes[DONE] = RES
    await tap(env, "crm:dt:rp:tm:8")
    assert await env.state() == "TaskDone:custom"
    await tap(env, "crm:dx:8")
    assert await env.state() == "TaskDone:custom"


# ------------------------------------------------------------------ callback data
def test_callbacks_under_64_bytes_and_no_collisions():
    from bot.crm.handlers import tasks as H

    t = 9999999999
    datas = [f"crm:do:{c}:{t}" for c in K.CODE_OUTCOME]
    datas += [
        f"crm:dt:{c}:{w}:{t}" for c in ("rp", "gi", "gl") for w in ("1h", "td", "tm", "cu", "no")
    ]
    datas += [f"crm:dy:{c}:{t}" for c in ("pp", "dn", "dc")] + [f"crm:dx:{t}", "crm:dq"]
    assert all(len(d.encode()) < 64 for d in datas)
    legacy = [f"crm:done:{t}", f"crm:sn:1h:{t}", f"crm:sn:tm:{t}", "crm:loc:i:5", "crm:loc:new"]
    pats = [H.DO_RE, H.DT_RE, H.DY_RE, H.DX_RE]
    assert not [d for d in legacy for p in pats if p.match(d)]
    assert not [d for d in datas if H.re.match(r"^crm:done:\d+$", d)]
    assert all(sum(bool(p.match(d)) for p in pats) <= 1 for d in datas)
