"""hr.* /notify renderers: every event of the contract has one and the contract fixtures
render; failures are reported per recipient (incl. blocked)."""

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

import bot.hr  # noqa: F401  (registers the renderers)
from bot.notify import registry

from .conftest import buttons, fixture

HR_EVENTS = [
    "hr.ask_eta", "hr.bot_added_to_group", "hr.day_off_set", "hr.day_report", "hr.employee_left",
    "hr.eta_passed", "hr.holiday_applied", "hr.holiday_ask", "hr.hours_set", "hr.leave_added",
    "hr.live_alert", "hr.missing_list", "hr.month_report", "hr.morning", "hr.off_days_set",
    "hr.off_request", "hr.off_request_answered", "hr.out_reminder", "hr.points_added",
    "hr.winner_announced", "hr.winner_pick",
]  # fmt: skip


def test_every_hr_event_has_a_renderer():
    assert set(HR_EVENTS) <= set(registry.events())


@pytest.mark.parametrize("event", HR_EVENTS)
async def test_contract_fixture_renders(event, tgbot, session):
    env = fixture(f"event.{event}")
    delivered = await registry.dispatch(env, tgbot)
    assert delivered, event
    assert all(d["ok"] for d in delivered)
    assert session.sent()


async def test_ask_eta_uses_dv_keyboard(tgbot, session):
    await registry.dispatch(fixture("event.hr.ask_eta"), tgbot)
    m = session.sent(777001)[0]
    cbs = [b[1] for b in buttons(m.reply_markup)]
    assert cbs and all(c.startswith("dv:") for c in cbs)
    assert "dv:eta:2026-10-27:20" in cbs and "dv:offreq:2026-10-27" in cbs
    assert "dv:cant:2026-10-27" in cbs and "dv:here:2026-10-27" in cbs
    assert "Isha soat" not in m.text and "09:00" in m.text


async def test_ask_eta_repeat_text(tgbot, session):
    env = fixture("event.hr.ask_eta")
    env["data"]["repeat"] = True
    await registry.dispatch(env, tgbot)
    assert "hali ham video-doirachangizni" in session.sent(777001)[0].text


async def test_blocked_dm_is_reported(tgbot, session):
    session.fail[777001] = TelegramForbiddenError(
        method=SendMessage(chat_id=777001, text="x"), message="Forbidden: bot was blocked by the user"
    )
    delivered = await registry.dispatch(fixture("event.hr.ask_eta"), tgbot)
    assert delivered == [
        {"chat_id": 777001, "ok": False, "message_id": None, "error_code": 403, "blocked": True}
    ]


async def test_winner_pick_buttons(tgbot, session):
    await registry.dispatch(fixture("event.hr.winner_pick"), tgbot)
    m = session.sent(555000111)[0]
    assert buttons(m.reply_markup)[0][1] == "dv:ann:m:2026-10:777001"
    assert "Oy xodimi tanlovi" in m.text


async def test_live_alert_late_goes_to_admins(tgbot, session):
    await registry.dispatch(fixture("event.hr.live_alert"), tgbot)
    t = session.texts(555000111)[0]
    assert "kech keldi: 09:40 (+25 daq)" in t and 'href="https://t.me/c/1234567890/55"' in t


async def test_off_request_has_approve_buttons(tgbot, session):
    await registry.dispatch(fixture("event.hr.off_request"), tgbot)
    cbs = [b[1] for b in buttons(session.sent(555000111)[0].reply_markup)]
    assert cbs == ["dv:offok:2026-10-27:777001", "dv:offno:2026-10-27:777001"]


async def test_holiday_applied_tells_admins_and_groups(tgbot, session):
    await registry.dispatch(fixture("event.hr.holiday_applied"), tgbot)
    assert session.sent(555000111) and session.sent(-1001234567890)
