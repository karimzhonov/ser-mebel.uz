# ruff: noqa: F811
"""Bot channel of stage 2 (dizayn va narx): the deadline and answer endpoints, the events
and the contract fixtures (docs/bot_contract/*offer*)."""

from datetime import datetime

import pytest

from api.tests.botkit import load_fixture
from api.tests.offerkit import design_file
from api.tests.test_offer_stage2 import (  # noqa: F401 - the shared fixtures
    NOW,
    ali,
    approved_design,
    clock,
    designer,
    finished,
    flow,
    lead,
    manager,
    operator,
    pricer,
    ready_design,
)
from metering import dto
from metering import services as M
from metering.design import services as DS
from metering.models import Metering
from metering.price import services as PS

pytestmark = pytest.mark.django_db


def keys(obj):
    return set(obj)


def test_due_with_preset_and_text(bot_client, flow, bot_events):
    d = flow.design
    bot_events.clear()
    r = bot_client.post(f"offers/design/{d.pk}/due/", actor=9001, data={"preset": "2d"})
    assert r.status_code == 200, r.content
    assert set(r.data) == {"task"} and r.data["task"]["due_at"] == "2026-11-07T18:00:00"
    ev = bot_events.one("offer.changed")  # also for a bot-initiated move
    assert ev["how"] == "due_moved" and ev["to"] == [9001] and ev["watchers"] == [9003]
    r = bot_client.post(f"offers/design/{d.pk}/due/", actor=9001, data={"text": "25.12 09:30"})
    assert r.data["task"]["due_at"] == "2026-12-25T09:30:00"
    for bad in (
        {},
        {"text": "zzz"},
        {"text": "11:00"},
        {"preset": "9y"},
        {"preset": "1d", "text": "14:00"},
        {"text": 5},
    ):
        r = bot_client.post(f"offers/design/{d.pk}/due/", actor=9001, data=bad)
        assert r.status_code == 400 and r.data["field"] == "due", bad
    assert (
        bot_client.post(
            f"offers/design/{d.pk}/due/",
            actor=9001,
            data=load_fixture("misc.offer_due_request.json"),
        ).status_code
        == 200
    )


def test_due_errors(bot_client, flow, designer, manager, make_staff, pricer):
    d = flow.design
    url = f"offers/design/{d.pk}/due/"
    # the manager is in scope but is not the designer: 403
    r = bot_client.post(url, actor=9003, data={"preset": "1d"})
    assert r.status_code == 403
    # a stranger: out of scope
    make_staff("design.view_design", telegram_id=9099)
    assert bot_client.post(url, actor=9099, data={"preset": "1d"}).status_code == 404
    assert bot_client.post(url, actor=999, data={"preset": "1d"}).status_code == 403  # not linked
    assert (
        bot_client.post("offers/other/1/due/", actor=9001, data={"preset": "1d"}).status_code == 404
    )
    assert (
        bot_client.post("offers/design/99999/due/", actor=9001, data={"preset": "1d"}).status_code
        == 404
    )
    ready_design(flow, designer)
    assert bot_client.post(url, actor=9001, data={"preset": "1d"}).status_code == 409


def test_answer_design(bot_client, flow, designer, manager, bot_events):
    d = flow.design
    url = f"offers/design/{d.pk}/answer/"
    assert (
        bot_client.post(url, actor=9003, data={"answer": "approved"}).status_code == 400
    )  # not ready
    ready_design(flow, designer)
    for bad, field in (
        ({}, "answer"),
        ({"answer": "x"}, "answer"),
        ({"answer": "changes"}, "comment"),
        ({"answer": "declined", "comment": "a"}, "comment"),
        ({"answer": "changes", "comment": 5}, "comment"),
    ):
        r = bot_client.post(url, actor=9003, data=bad)
        assert r.status_code == 400 and r.data["field"] == field, bad
    assert (
        bot_client.post(url, actor=9001, data={"answer": "approved"}).status_code == 403
    )  # the designer
    bot_events.clear()
    req = load_fixture("misc.offer_answer_request.json")
    r = bot_client.post(url, actor=9003, data=req)
    assert r.status_code == 200, r.content
    fixture = load_fixture("misc.offer_answer_response.json")
    assert keys(r.data) == keys(fixture) and keys(r.data["task"]) == keys(fixture["task"])
    assert r.data["closed_tasks"] == 0 and r.data["task"]["round"] == 2
    assert r.data["task"]["stage"] == "work"
    assert bot_events.one("offer.changed")["how"] == "answered"
    assert bot_events.one("offer.assigned")["how"] == "changes"
    # ask again: 409 once approved
    ready_design(Metering.objects.get(pk=flow.pk), designer)
    assert bot_client.post(url, actor=9003, data={"answer": "approved"}).status_code == 200
    assert bot_client.post(url, actor=9003, data={"answer": "approved"}).status_code == 409


def test_answer_design_declined_reports_closed_tasks(bot_client, flow, designer, manager, operator):
    from call_center import services as CC

    CC.create_task(flow.invoice, text="Qo'ng'iroq", due_at=NOW, by=operator, assigned_to=operator)
    ready_design(flow, designer)
    r = bot_client.post(
        f"offers/design/{flow.design.pk}/answer/",
        actor=9003,
        data={"answer": "declined", "comment": "Yoqmadi"},
    )
    assert r.status_code == 200 and r.data["closed_tasks"] == 1
    assert r.data["task"]["stage"] == "declined"


def test_answer_price_and_scope(
    bot_client, flow, designer, manager, pricer, make_staff, bot_events
):
    make_staff("order.add_order", telegram_id=9061)
    m = approved_design(flow, designer, manager)
    PS.mark_price_done(m.price, by=pricer)
    url = f"offers/price/{m.price.pk}/answer/"
    assert (
        bot_client.post(url, actor=9003, data={"answer": "changes", "comment": "xxx"}).status_code
        == 400
    )
    r = bot_client.post(url, actor=9003, data={"answer": "recalc", "comment": "Arzonroq"})
    assert (
        r.status_code == 200 and r.data["task"]["kind"] == "price" and r.data["task"]["round"] == 2
    )
    PS.mark_price_done(Metering.objects.get(pk=m.pk).price, by=pricer)
    bot_events.clear()
    r = bot_client.post(url, actor=9003, data={"answer": "approved"})
    assert r.status_code == 200
    assert bot_events.one("offer.order_ready")["task"]["kind"] == "price"
    assert Metering.objects.get(pk=m.pk).client_result == "agreed"
    make_staff("price.view_price", telegram_id=9098)
    assert bot_client.post(url, actor=9098, data={"answer": "approved"}).status_code == 404


def test_task_dto_and_events_match_the_fixtures(flow, designer, manager, bot_events):
    fixture = load_fixture("dto.offer_task.1.json")
    task = dto.offer_task(Metering.objects.get(pk=flow.pk).design, "design")
    assert keys(task) == keys(fixture)
    assert keys(task["client"]) == keys(fixture["client"])
    assert keys(task["assignee"]) == keys(fixture["assignee"])
    assert task["present_url"].endswith(f"/presentations?open=d{flow.design.pk}")
    assert task["url"].endswith(f"/designs/{flow.design.pk}") and task["stage_label"] == "Ishda"
    for name in ("assigned", "reminder", "present", "changed", "order_ready"):
        env = load_fixture(f"event.offer.{name}.json")
        assert env["event"] == f"offer.{name}" and env["id"]
        assert keys(env["data"]["task"]) == keys(fixture)


def test_event_payloads_match_the_fixtures(
    operator, ali, designer, pricer, manager, make_staff, bot_events, clock
):
    make_staff("order.add_order", telegram_id=9060)
    m = finished(operator, ali, designer, pricer, manager)
    assigned = bot_events.of("offer.assigned")[0]
    assert keys(assigned) == keys(load_fixture("event.offer.assigned.json")["data"])
    clock["v"] = datetime(2026, 11, 4, 9, 0)
    M.due_offer_reminders(clock["v"])
    rem = bot_events.of("offer.reminder")[0]
    assert keys(rem) == keys(load_fixture("event.offer.reminder.json")["data"])
    design_file(m.design)
    DS.mark_design_done(m.design, by=designer)
    present = bot_events.one("offer.present")
    assert keys(present) == keys(load_fixture("event.offer.present.json")["data"])
    changed = [e for e in bot_events.of("offer.changed")][-1]
    assert keys(changed) == keys(load_fixture("event.offer.changed.json")["data"])
    DS.record_design_answer(m.design, by=manager, answer="approved")
    PS.mark_price_done(Metering.objects.get(pk=m.pk).price, by=pricer)
    PS.record_price_answer(Metering.objects.get(pk=m.pk).price, by=manager, answer="approved")
    ready = bot_events.one("offer.order_ready")
    assert keys(ready) == keys(load_fixture("event.offer.order_ready.json")["data"])
