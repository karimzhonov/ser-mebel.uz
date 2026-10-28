"""The JSON fixtures in docs/bot_contract/ (shared with the bot's test suite) describe what the
backend really produces. Skipped where the repo-level docs/ folder is not mounted."""

import re
from datetime import date
from pathlib import Path

import pytest

from accounting import dto
from accounting import services as S
from api.tests.botkit import CONTRACT_DIR, load_fixture
from hr import services as HS

pytestmark = pytest.mark.django_db
BACKEND = Path(__file__).resolve().parents[2]


def shape(value):
    """Key structure of a JSON value (lists by their first element)."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return None


def keys(obj):
    return set(obj)


def test_every_emitted_event_has_a_fixture_and_vice_versa():
    if not CONTRACT_DIR.exists():
        pytest.skip("docs/bot_contract is not available (mount ./docs at /docs)")
    emitted = set()
    for f in ("accounting/events.py", "hr/events.py"):
        emitted |= set(
            re.findall(
                r'(?:emit|send_event_sync)\(\s*"([a-z_.]+)"',
                (BACKEND / f).read_text(encoding="utf-8"),
            )
        )
    fixtures = {p.name[len("event.") : -len(".json")] for p in CONTRACT_DIR.glob("event.*.json")}
    assert emitted == fixtures, emitted ^ fixtures
    for name in fixtures:
        env = load_fixture(f"event.{name}.json")
        assert env["event"] == name and env["id"] and isinstance(env["data"], dict)


def test_finance_dtos_match_the_fixtures(members, site_order):
    boss, ali, _ = members
    op = S.create_operation(
        member=ali,
        author=ali,
        kind="expense",
        amount=1000,
        category_code="material",
        order_ref="406",
    )
    assert shape(dto.member_dto(ali)) == shape(load_fixture("dto.member.1.json"))
    assert shape(dto.category_dto(op.category)) == shape(load_fixture("dto.category.1.json"))
    assert shape(dto.operation_dto(op)) == shape(load_fixture("dto.operation.1.json"))
    info = S.order_info("406")
    stats = S.order_stats("406")
    staff_card = dto.order_card_dto(info, stats, full=False)
    assert keys(staff_card) == keys(load_fixture("dto.order_card_staff.1.json"))
    assert keys(staff_card["stats"]) == keys(load_fixture("dto.order_card_staff.1.json")["stats"])
    admin_card = dto.order_card_dto(info, stats, full=True)
    assert keys(admin_card) == keys(load_fixture("dto.order_card_admin.1.json"))
    assert shape(dto.order_brief_dto(info)) == shape(load_fixture("dto.order_brief.1.json"))
    req = S.create_request(ali, {"amount": 1000, "cur": "UZS"}, "x")
    fixture_req = load_fixture("dto.money_request.1.json")
    assert keys(dto.request_dto(req)) == keys(fixture_req)
    assert keys(dto.request_dto(req)["member"]) == keys(fixture_req["member"])
    task = S.site_entry_create("406", "K", "1", "Ali", "0")
    assert shape(dto.task_dto(task)) == shape(load_fixture("dto.site_entry_task.1.json"))
    w = S.warranty_ensure("406", "K", date.today())
    assert shape(dto.warranty_dto(w)) == shape(load_fixture("dto.warranty.1.json"))
    fb = S.feedback_schedule(info, date.today())
    assert shape(dto.feedback_dto(fb)) == shape(load_fixture("dto.feedback.1.json"))
    mo = S.create_manual_order("SM-001", "K")
    assert shape(dto.manual_order_dto(mo)) == shape(load_fixture("dto.manual_order.1.json"))
    bn = S.bonus_start(info, date.today())[0]
    assert shape(dto.bonus_dto(bn)) == shape(load_fixture("dto.bonus.1.json"))
    assert shape(dto.money_state_dto(S.money_state(bn))) == shape(
        load_fixture("dto.money_state.1.json")
    )
    sm = S.month_summary(ali, "2026-10")
    assert shape(dto.month_summary_dto(sm)) == shape(load_fixture("dto.month_summary.1.json"))
    assert shape(dto.day_summary_dto(S.summary(None, None))) == shape(
        load_fixture("dto.day_summary.1.json")
    )


def test_hr_dtos_and_reports_match_the_fixtures(group, clock):
    from datetime import datetime

    from hr import report_data as RD

    e, _ = HS.upsert_emp({"id": 500, "first_name": "Jasur"}, group)
    assert keys(HS.employee_dto(e)) == keys(load_fixture("dto.employee.1.json"))
    assert keys(HS.employee_dto(e)["group"]) == keys(load_fixture("dto.employee.1.json")["group"])
    assert shape(HS.group_dto(group)) == shape(load_fixture("dto.work_group.1.json"))
    now_d = datetime(2026, 10, 26, 12, 0)
    # same keys as the fixture for every list the text builders walk
    live = RD.day_report_data(now_d.date(), now_d)
    assert keys(live) == keys(load_fixture("dto.day_report_data.1.json"))
    assert keys(RD.past_day_report_data(date(2026, 10, 1))) <= keys(
        load_fixture("dto.day_report_data.2.json")
    )
    HS.set_att(now_d.date(), e, in_time=HS.to_time(600), status="late", late_min=60)
    HS.finalize_day(now_d.date())
    past = RD.past_day_report_data(now_d.date())
    assert keys(past) == keys(load_fixture("dto.day_report_data.2.json"))
    period = RD.period_report_data(date(2026, 10, 1), date(2026, 10, 31), now_d)
    assert keys(period) == keys(load_fixture("dto.period_report_data.1.json"))
    assert keys(period["rows"][0]) == keys(load_fixture("dto.period_report_data.1.json")["rows"][0])
    assert keys(HS.ranking_rows("2026-10")[0]) == keys(load_fixture("dto.ranking_row.1.json"))


def test_misc_fixtures_match_real_responses(bot_client, group, clock):
    who = bot_client.post("whoami/", actor=100, data={"user": {"id": 100}})
    assert keys(who.data) == keys(load_fixture("misc.whoami_response.json"))
    assert keys(who.data["hr"]) == keys(load_fixture("misc.whoami_response.json")["hr"])
    req = load_fixture("misc.hr_group_message_request.json")
    req["chat"]["id"] = group.chat_id
    req["from"]["id"] = 777001
    r = bot_client.post("hr/group-message/", actor=777001, data=req)
    assert keys(r.data) == keys(load_fixture("misc.hr_group_message_response.json"))
    assert keys(r.data["dm"]) == keys(load_fixture("misc.hr_group_message_response.json")["dm"])
    text = bot_client.post("hr/private-text/", actor=777001, data={"text": "salom"})
    assert keys(text.data) == keys(load_fixture("misc.hr_private_text_response.json"))
    cb = bot_client.post(
        "hr/callback/", actor=777001, data={"action": "uni", "day": "2026-10-26", "arg": "1"}
    )
    assert keys(cb.data) == keys(load_fixture("misc.hr_callback_response.json"))
    assert keys(cb.data["reply"]) == keys(load_fixture("misc.hr_callback_response.json")["reply"])
    bad = bot_client.post(
        "finance/operations/",
        actor=100,
        data={"kind": "expense", "amount": "0", "category": "ovqat"},
    )
    assert bad.status_code == 400 and keys(bad.data) == keys(load_fixture("misc.error_400.json"))
