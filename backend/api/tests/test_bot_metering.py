"""Bot channel of the zamer: the measurer's three actions, the events and the contract
fixtures (docs/bot_contract/*metering*)."""

from datetime import datetime

import pytest
from phonenumber_field.phonenumber import PhoneNumber

from api.tests.botkit import load_fixture
from call_center import services as CC
from call_center.constants import SolutionChoice
from metering import dto
from metering import services as M
from metering.models import Metering

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 3, 12, 0)
WHEN = datetime(2026, 11, 4, 10, 0)
MEASURER_PERMS = ("oauth.user_metering", "metering.view_metering")
OPERATOR_PERMS = (
    "call_center.view_invoice",
    "call_center.add_invoice",
    "call_center.change_invoice",
    "metering.view_metering",
    "metering.change_metering",
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(M, "_now", lambda: NOW)
    monkeypatch.setattr(CC, "_now", lambda: NOW)
    monkeypatch.setattr("metering.tasks.assignment_sms.delay", lambda *a: None)


@pytest.fixture
def ali(make_staff):
    return make_staff(*MEASURER_PERMS, name="Ali Zamerchi", telegram_id=555000333)


@pytest.fixture
def operator(make_staff):
    return make_staff(*OPERATOR_PERMS, name="Dilfuza", telegram_id=555000222)


@pytest.fixture
def booked(ali, operator):
    inv = CC.create_invoice(
        fio="Ali Valiyev",
        phone=PhoneNumber.from_string("+998901112244", region="UZ"),
        author=operator,
    )
    return M.create_metering(
        client=inv.client, date_time=WHEN, invoice=inv, author=operator, address="Chilonzor"
    )


def test_measured(bot_client, ali, booked, bot_events):
    bot_events.clear()
    r = bot_client.post(f"meterings/{booked.pk}/measured/", actor=555000333)
    assert r.status_code == 200, r.content
    assert set(r.data) == {"metering", "url"} and r.data["url"].endswith(f"/meterings/{booked.pk}")
    assert r.data["metering"]["status"] == "metering_done" and r.data["metering"]["rev"] == 1
    ev = bot_events.one("metering.changed")  # emitted for a bot-initiated action too
    assert ev["how"] == "measured" and ev["to"] == [555000333]
    again = bot_client.post(f"meterings/{booked.pk}/measured/", actor=555000333)
    assert again.status_code == 409


def test_measured_unlinked_403_and_out_of_scope_404(bot_client, make_staff, ali, booked):
    make_staff(*MEASURER_PERMS, telegram_id=555000444)
    assert (
        bot_client.post(f"meterings/{booked.pk}/measured/", actor=555000444).status_code == 404
    )  # out of scope
    r = bot_client.post(f"meterings/{booked.pk}/measured/", actor=999)  # not linked
    assert r.status_code == 403 and "ulanmagan" in r.data["detail"]
    assert bot_client.post("meterings/99999/measured/", actor=555000333).status_code == 404


def test_reschedule(bot_client, ali, operator, booked, bot_events):
    bot_events.clear()
    r = bot_client.post(
        f"meterings/{booked.pk}/reschedule/", actor=555000333, data={"preset": "tomorrow"}
    )
    assert r.status_code == 200, r.content
    assert r.data["metering"]["date_time"] == "2026-11-04T10:00:00"  # +1 day: same clock
    assert r.data["metering"]["status"] == "other_day"
    ev = bot_events.one("metering.changed")
    assert ev["how"] == "rescheduled" and ev["watchers"] == [555000222]
    r = bot_client.post(
        f"meterings/{booked.pk}/reschedule/", actor=555000333, data={"text": "25.12 09:30"}
    )
    assert r.data["metering"]["date_time"] == "2026-12-25T09:30:00"
    for bad in (
        {},
        {"text": "zzz"},
        {"text": "11:00"},
        {"preset": "9y"},
        {"preset": "1h", "text": "14:00"},
    ):
        r = bot_client.post(f"meterings/{booked.pk}/reschedule/", actor=555000333, data=bad)
        assert r.status_code == 400 and r.data["field"] == "time", bad


def test_cancel(bot_client, ali, operator, booked, bot_events):
    for bad in ({}, {"reason": "ab"}, {"reason": 5}):
        r = bot_client.post(f"meterings/{booked.pk}/cancel/", actor=555000333, data=bad)
        assert r.status_code == 400 and r.data["field"] == "reason", bad
    bot_events.clear()
    req = load_fixture("misc.metering_cancel_request.json")
    r = bot_client.post(f"meterings/{booked.pk}/cancel/", actor=555000333, data=req)
    assert r.status_code == 200, r.content
    fixture = load_fixture("misc.metering_cancel_response.json")
    assert set(r.data) == set(fixture) and set(r.data["metering"]) == set(fixture["metering"])
    assert r.data["lead_returned"] is True and r.data["metering"]["status"] == "dont_need"
    assert booked.invoice.__class__.objects.get(pk=booked.invoice_id).solution == (
        SolutionChoice.re_phone
    )
    assert bot_events.one("metering.changed")["how"] == "cancelled"
    again = bot_client.post(f"meterings/{booked.pk}/cancel/", actor=555000333, data=req)
    assert again.status_code == 409


def test_reschedule_request_fixture_is_accepted(bot_client, ali, booked):
    req = load_fixture("misc.metering_reschedule_request.json")
    r = bot_client.post(f"meterings/{booked.pk}/reschedule/", actor=555000333, data=req)
    assert r.status_code == 200


def test_brief_and_events_match_the_fixtures(booked, bot_events):
    fixture = load_fixture("dto.metering_brief.1.json")
    brief = dto.metering_brief(Metering.objects.get(pk=booked.pk))
    assert set(brief) == set(fixture)
    assert set(brief["client"]) == set(fixture["client"])
    assert set(brief["measurer"]) == set(fixture["measurer"])
    M.due_metering_reminders(datetime(2026, 11, 3, 20, 0))
    digest = bot_events.one("metering.digest")
    assert set(digest) == set(load_fixture("event.metering.digest.json")["data"])
    assert set(digest["items"][0]) == set(fixture)
    for name in ("assigned", "reminder", "changed", "digest"):
        env = load_fixture(f"event.metering.{name}.json")
        assert env["event"] == f"metering.{name}" and env["id"]


def test_assigned_and_changed_payloads_match_fixtures(ali, operator, bot_events):
    inv = CC.create_invoice(
        fio="X", phone=PhoneNumber.from_string("+998901112255", region="UZ"), author=operator
    )
    m = M.create_metering(client=inv.client, date_time=WHEN, invoice=inv, author=operator)
    assert set(bot_events.one("metering.assigned")) == set(
        load_fixture("event.metering.assigned.json")["data"]
    )
    M.reschedule_metering(m, by=ali, preset="2d")
    assert set(bot_events.one("metering.changed")) == set(
        load_fixture("event.metering.changed.json")["data"]
    )
    bot_events.clear()
    M.due_metering_reminders(datetime(2026, 11, 4, 9, 0))
    rem = bot_events.of("metering.reminder")
    assert rem == [] or set(rem[0]) == set(load_fixture("event.metering.reminder.json")["data"])
