"""crm.task_closed / crm.task_moved: the bot tidies the reminder it already sent when the
task is finished / moved / reassigned somewhere else (docs/BOT_CONTRACT.md, "CRM")."""

from datetime import datetime

import pytest
from django.db import transaction

from api.tests.botkit import load_fixture
from api.tests.test_crm import NOW, PERMS, lead
from call_center import services as CC
from call_center.constants import SolutionChoice

pytestmark = pytest.mark.django_db

CLOSED, MOVED = "crm.task_closed", "crm.task_moved"


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(CC, "_now", lambda: NOW)


@pytest.fixture
def seller(make_staff):
    return make_staff(*PERMS, name="Dilfuza", telegram_id=4001)


def new_task(inv, by, **kw):
    return CC.create_task(inv, text="t", due_at=NOW, by=by, **kw)


def panel(api, seller):
    c = api(*PERMS)
    c.force_authenticate(seller)
    return c


def test_panel_done_emits_once_with_payload(api, seller, bot_events):
    inv = lead(seller)
    t = new_task(inv, seller)
    r = panel(api, seller).post(
        f"/api/v1/invoice-tasks/{t.pk}/done/",
        {"outcome": "re_phone", "next_task": {"preset": "tomorrow"}},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert bot_events.names() == [CLOSED]
    assert bot_events.one(CLOSED) == {
        "task": {"id": t.pk},
        "how": "done",
        "by_name": "Dilfuza",
        "solution_label": "Qayta qo'ng'iroq qilish",
        "next_due": "2026-11-04T10:00:00",
        "to": [4001],
    }


def test_panel_done_without_next_task(seller, bot_events):
    inv = lead(seller)
    t = new_task(inv, seller)
    CC.complete_task(t, by=seller, outcome="given_info")
    data = bot_events.one(CLOSED)
    assert data["next_due"] is None and data["how"] == "done"


def test_bot_done_emits_nothing_for_that_task(bot_client, seller, bot_events):
    inv = lead(seller)
    t = new_task(inv, seller)
    r = bot_client.post(f"crm/tasks/{t.pk}/done/", actor=4001, data={"outcome": "given_info"})
    assert r.status_code == 200, r.content
    assert bot_events.of(CLOSED) == []


def test_closing_outcome_auto_closes_other_tasks_from_panel(seller, bot_events):
    inv = lead(seller)
    a, b, c = (new_task(inv, seller) for _ in range(3))
    CC.complete_task(a, by=seller, outcome="declined")
    assert {(e["task"]["id"], e["how"]) for e in bot_events.of(CLOSED)} == {
        (a.pk, "done"),
        (b.pk, "auto"),
        (c.pk, "auto"),
    }
    auto = [e for e in bot_events.of(CLOSED) if e["how"] == "auto"]
    assert len(auto) == 2
    assert all(e["solution_label"] and e["next_due"] is None and e["to"] == [4001] for e in auto)


def test_closing_outcome_from_bot_still_emits_auto_for_others(bot_client, seller, bot_events):
    inv = lead(seller)
    a, b = new_task(inv, seller), new_task(inv, seller)
    r = bot_client.post(f"crm/tasks/{a.pk}/done/", actor=4001, data={"outcome": "declined"})
    assert r.status_code == 200, r.content
    events = bot_events.of(CLOSED)
    assert [(e["task"]["id"], e["how"]) for e in events] == [(b.pk, "auto")]
    assert events[0]["by_name"] == "Dilfuza"


def test_board_drag_to_closing_column_emits_auto(api, seller, bot_events):
    inv = lead(seller)
    a, b = new_task(inv, seller), new_task(inv, seller)
    r = panel(api, seller).post(
        f"/api/v1/invoices/{inv.pk}/solution/",
        {"solution": int(SolutionChoice.declined)},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert {(e["task"]["id"], e["how"]) for e in bot_events.of(CLOSED)} == {
        (a.pk, "auto"),
        (b.pk, "auto"),
    }


def test_non_closing_answer_emits_nothing(seller, bot_events):
    inv = lead(seller)
    new_task(inv, seller)
    CC.set_invoice_solution(inv, SolutionChoice.given_info, author=seller)
    assert bot_events == []


def test_panel_reschedule_emits_rescheduled(api, seller, bot_events):
    inv = lead(seller)
    t = new_task(inv, seller)
    r = panel(api, seller).post(
        f"/api/v1/invoice-tasks/{t.pk}/reschedule/", {"preset": "tomorrow"}, format="json"
    )
    assert r.status_code == 200, r.content
    assert bot_events.one(MOVED) == {
        "task": {"id": t.pk, "due_at": "2026-11-04T10:00:00"},
        "how": "rescheduled",
        "by_name": "Dilfuza",
        "to_name": None,
        "to": [4001],
    }


def test_bot_snooze_emits_nothing(bot_client, seller, bot_events):
    inv = lead(seller)
    t = new_task(inv, seller)
    r = bot_client.post(f"crm/tasks/{t.pk}/snooze/", actor=4001, data={"preset": "1h"})
    assert r.status_code == 200, r.content
    assert bot_events == []


def test_reassign_emits_reassigned_for_each_moved_task(seller, make_staff, bot_events):
    other = make_staff(*PERMS, name="Zafar", telegram_id=4002)
    boss = make_staff("call_center.manage_invoice", *PERMS, name="Boss")
    inv = lead(seller)
    a, b = new_task(inv, seller), new_task(inv, seller)
    done = new_task(inv, seller)
    CC.complete_task(done, by=seller, outcome="given_info")
    bot_events.clear()
    CC.update_lead(inv, by=boss, assigned_to=other)
    events = bot_events.of(MOVED)
    assert sorted(e["task"]["id"] for e in events) == sorted([a.pk, b.pk])
    for e in events:
        assert e["how"] == "reassigned" and e["to_name"] == "Zafar" and e["by_name"] == "Boss"
        assert e["to"] == [4001]  # the previous owner holds the stale reminder


def test_no_event_when_the_transaction_rolls_back(
    seller, monkeypatch, django_capture_on_commit_callbacks
):
    sent = []
    monkeypatch.setattr("core.tasks.notify_bot.delay", lambda env: sent.append(env))
    inv = lead(seller)
    t = new_task(inv, seller)
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                CC.complete_task(t, by=seller, outcome="declined")
                raise RuntimeError("boom")
    assert callbacks == [] and sent == []


def test_events_match_the_contract_fixtures(seller, bot_events):
    inv = lead(seller)
    t = new_task(inv, seller)
    CC.complete_task(t, by=seller, outcome="re_phone", next_task={"preset": "tomorrow"})
    t2 = new_task(inv, seller)
    CC.reschedule_task(t2, by=seller, due_at=datetime(2026, 11, 5, 10, 0))

    def shape(v):
        if isinstance(v, dict):
            return {k: shape(x) for k, x in v.items()}
        return type(v).__name__ if v is not None else None

    for name, got in ((CLOSED, bot_events.one(CLOSED)), (MOVED, bot_events.one(MOVED))):
        want = load_fixture(f"event.{name}.json")["data"]
        assert set(got) == set(want)
        assert set(got["task"]) == set(want["task"])


def test_reassigned_reminded_task_reminds_the_new_owner(seller, make_staff):
    from datetime import datetime, timedelta

    from call_center import services as CC
    from call_center.models import Invoice, InvoiceTask

    other = make_staff("call_center.view_invoice", "call_center.change_invoice", telegram_id=7777)
    inv = CC.create_invoice(fio="R", phone="+998901112299", source="phone", author=seller)
    t = CC.create_task(inv, text="t", due_at=datetime.now() - timedelta(hours=1), by=seller)
    InvoiceTask.objects.filter(pk=t.pk).update(notified_at=datetime.now())
    CC.update_lead(Invoice.objects.get(pk=inv.pk), by=seller, assigned_to=other)
    t.refresh_from_db()
    assert t.assigned_to_id == other.pk and t.notified_at is None and t.remind_seq == 1
