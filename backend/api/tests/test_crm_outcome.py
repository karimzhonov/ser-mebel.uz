"""Completing a task asks which stage the lead goes to (call_center.services.complete_task)."""

from datetime import datetime, timedelta

import pytest

from api.tests.botkit import load_fixture
from api.tests.test_crm import NOW, PERMS, lead
from call_center import services as CC
from call_center.constants import NoteKind, SolutionChoice
from call_center.models import InvoiceTask
from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden

pytestmark = pytest.mark.django_db

S = SolutionChoice
ACTIVE_ORDER = [
    "re_phone",
    "given_info",
    "given_location",
    "go_for_measured",
    "price_problem",
    "dont_need",
    "declined",
]
TOMORROW = datetime(2026, 11, 4, 10, 0)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(CC, "_now", lambda: NOW)


@pytest.fixture
def seller(make_staff):
    return make_staff(*PERMS, name="Dilfuza", telegram_id=4001)


@pytest.fixture
def met_seller(make_staff):
    return make_staff(*PERMS, "metering.add_metering", name="Zamerchi", telegram_id=4020)


def new_task(inv, by, **kw):
    return CC.create_task(inv, text="t", due_at=NOW, by=by, **kw)


def field_of(exc):
    return exc.value.field


# ------------------------------------------------------------------ task_outcomes
@pytest.mark.parametrize("solution", [None, S.re_phone, S.given_info, S.given_location])
def test_outcomes_active_lead(seller, met_seller, solution):
    inv = lead(seller)
    inv.solution = solution
    assert CC.task_outcomes(inv, met_seller) == ACTIVE_ORDER
    assert CC.task_outcomes(inv, seller) == [x for x in ACTIVE_ORDER if x != "go_for_measured"]


@pytest.mark.parametrize(
    "solution",
    [S.sold_out, S.go_for_measured, S.price_problem, S.dont_need, S.declined],
)
def test_outcomes_closed_lead_is_keep_only(seller, met_seller, solution):
    inv = lead(seller)
    inv.solution = solution
    assert CC.task_outcomes(inv, met_seller) == ["keep"]


def test_outcomes_view_only_user_is_keep_only(seller, make_staff):
    viewer = make_staff("call_center.view_invoice")
    assert CC.task_outcomes(lead(seller), viewer) == ["keep"]


# ------------------------------------------------------------------ complete_task
def test_re_phone_with_tomorrow_preset_creates_reminder_for_owner(seller, make_staff):
    boss = make_staff("call_center.manage_invoice", *PERMS)
    inv = lead(seller)
    t = new_task(inv, seller)
    res = CC.complete_task(
        t, by=boss, outcome="re_phone", next_task={"preset": "tomorrow"}, note="Javob bermadi"
    )
    assert res.task.done_at == NOW and res.task.done_by == boss and res.task.invoice == inv
    assert res.next_task.due_at == TOMORROW
    assert res.next_task.assigned_to == seller  # the lead's owner, not the actor
    assert res.next_task.text == CC.DEFAULT_TASK_TEXT
    assert res.invoice.solution == S.re_phone and res.closed_tasks == 0
    inv.refresh_from_db()
    assert inv.solution == S.re_phone
    assert inv.notes.filter(kind=NoteKind.note, task=t, text="Javob bermadi").exists()
    sol = inv.notes.get(kind=NoteKind.solution)
    assert sol.meta == {"from": None, "to": 1}


def test_re_phone_with_exact_due_at_and_text(seller):
    inv = lead(seller)
    due = NOW + timedelta(days=3)
    res = CC.complete_task(
        new_task(inv, seller),
        by=seller,
        outcome="re_phone",
        next_task={"due_at": due, "text": "Narx haqida"},
    )
    assert res.next_task.due_at == due and res.next_task.text == "Narx haqida"


def test_validation_errors_roll_everything_back(seller):
    inv = lead(seller)
    t = new_task(inv, seller)
    cases = [
        (dict(), "outcome"),  # missing on an active lead
        (dict(outcome="keep"), "outcome"),  # keep is not offered on an active lead
        (dict(outcome="go_for_measured"), "outcome"),
        (dict(outcome="nonsense"), "outcome"),
        (dict(outcome="re_phone"), "next_task"),  # time is mandatory
        (dict(outcome="re_phone", next_task={"due_at": NOW}), "next_task"),  # not future
        (dict(outcome="re_phone", next_task={"due_at": NOW - timedelta(hours=1)}), "next_task"),
        (
            dict(outcome="re_phone", next_task={"preset": "1h", "due_at": NOW + timedelta(1)}),
            "next_task",
        ),
        (dict(outcome="re_phone", next_task={}), "next_task"),
        (dict(outcome="re_phone", next_task={"preset": "later"}), "next_task"),
        (dict(outcome="declined", next_task={"preset": "1h"}), "next_task"),
        (dict(outcome="dont_need", next_task={"preset": "1h"}), "next_task"),
    ]
    for kw, field in cases:
        with pytest.raises(ServiceError) as exc:
            CC.complete_task(t, by=seller, note="x", **kw)
        assert field_of(exc) == field, kw
    t.refresh_from_db()
    inv.refresh_from_db()
    assert t.done_at is None and inv.solution is None and not inv.notes.filter(text="x").exists()
    assert InvoiceTask.objects.filter(invoice=inv).count() == 1


def test_given_info_with_and_without_next_task(seller):
    inv = lead(seller)
    r = CC.complete_task(new_task(inv, seller), by=seller, outcome="given_info")
    assert r.next_task is None and r.invoice.solution == S.given_info
    r = CC.complete_task(
        new_task(inv, seller), by=seller, outcome="given_location", next_task={"preset": "1h"}
    )
    assert r.next_task.due_at == datetime(2026, 11, 3, 13, 0)
    assert r.invoice.solution == S.given_location


def test_closing_outcome_closes_other_open_tasks_and_logs_count(seller):
    inv = lead(seller, desc="Asl izoh")
    t = new_task(inv, seller)
    others = [new_task(inv, seller) for _ in range(2)]
    res = CC.complete_task(t, by=seller, outcome="price_problem")
    assert res.closed_tasks == 2 and res.next_task is None
    assert not inv.tasks.filter(done_at__isnull=True).exists()
    assert all(InvoiceTask.objects.get(pk=o.pk).done_by == seller for o in others)
    inv.refresh_from_db()
    assert inv.solution == S.price_problem and inv.desc == "Asl izoh"  # no note per closed task
    assert inv.notes.get(kind=NoteKind.solution).meta == {"from": None, "to": 4, "closed_tasks": 2}
    # no other tasks left: the count is not written
    inv2 = lead(seller, phone="+998901119999")
    CC.complete_task(new_task(inv2, seller), by=seller, outcome="declined")
    assert inv2.notes.get(kind=NoteKind.solution).meta == {"from": None, "to": -1}


def test_same_stage_writes_no_history_line(seller):
    inv = lead(seller)
    CC.set_invoice_solution(inv, 2, author=seller)
    before = inv.notes.filter(kind=NoteKind.solution).count()
    CC.complete_task(new_task(inv, seller), by=seller, outcome="given_info")
    assert inv.notes.filter(kind=NoteKind.solution).count() == before


def test_keep_on_served_lead(seller, met_seller):
    inv = lead(seller)
    CC.set_invoice_solution(inv, 4, author=seller)  # closed: keep only
    t = new_task(inv, seller)
    with pytest.raises(ServiceError) as exc:
        CC.complete_task(t, by=seller, outcome="re_phone", next_task={"preset": "1h"})
    assert field_of(exc) == "outcome"
    with pytest.raises(ServiceError) as exc:
        CC.complete_task(t, by=seller, outcome="keep", next_task={"preset": "1h"})
    assert field_of(exc) == "next_task"
    res = CC.complete_task(t, by=seller, outcome="keep", note="Yopildi")
    assert res.invoice.solution == S.price_problem and res.next_task is None
    # omitted outcome on a keep-only lead is the same as keep
    assert CC.complete_task(new_task(inv, seller), by=seller).task.done_at == NOW


def test_conflict_and_forbidden_come_before_validation(seller, make_staff):
    stranger = make_staff(*PERMS)
    inv = lead(seller)
    t = new_task(inv, seller)
    with pytest.raises(ServiceForbidden):
        CC.complete_task(t, by=stranger)  # no outcome, but 403 first
    CC.complete_task(t, by=seller, outcome="given_info")
    with pytest.raises(ServiceConflict):
        CC.complete_task(t, by=seller)  # no outcome, but 409 first


def test_set_invoice_solution_closing_closes_tasks_but_re_phone_does_not(seller):
    inv = lead(seller)
    new_task(inv, seller)
    CC.set_invoice_solution(inv, 1, author=seller)
    assert inv.tasks.filter(done_at__isnull=True).count() == 1
    CC.set_invoice_solution(inv, 0, author=seller)
    assert inv.tasks.filter(done_at__isnull=True).count() == 0
    assert inv.notes.filter(kind=NoteKind.solution).latest("pk").meta["closed_tasks"] == 1


def test_new_reminder_fires_once(seller, bot_events):
    inv = lead(seller)
    CC.complete_task(
        new_task(inv, seller), by=seller, outcome="re_phone", next_task={"preset": "1h"}
    )
    later = NOW + timedelta(hours=2)
    assert CC.due_task_reminders(later) == 1
    assert CC.due_task_reminders(later) == 0


# ------------------------------------------------------------------ site API
def test_site_api_done_shape_and_errors(api, seller):
    inv = lead(seller)
    t = new_task(inv, seller)
    c = api(*PERMS)
    c.force_authenticate(seller)
    url = f"/api/v1/invoice-tasks/{t.pk}/done/"
    r = c.post(url, {"note": "x"}, format="json")
    assert r.status_code == 400 and r.data == {
        "detail": "Keyingi bosqichni tanlang",
        "field": "outcome",
    }
    r = c.post(url, {"outcome": "re_phone"}, format="json")
    assert r.status_code == 400 and r.data["field"] == "next_task"
    r = c.post(url, {"outcome": "bogus"}, format="json")
    assert r.status_code == 400
    r = c.post(
        url,
        {"outcome": "re_phone", "next_task": {"preset": "1h", "due_at": "2030-01-01T10:00:00"}},
        format="json",
    )
    assert r.status_code == 400
    r = c.post(
        url, {"outcome": "re_phone", "next_task": {"due_at": "2020-01-01T10:00:00"}}, format="json"
    )
    assert r.status_code == 400 and r.data["field"] == "next_task"
    r = c.post(url, {"outcome": "re_phone", "next_task": {"preset": "tomorrow"}}, format="json")
    assert r.status_code == 400 and r.data["field"] == "note"  # a panel result needs a comment
    r = c.post(
        url,
        {"note": "ertaga", "outcome": "re_phone", "next_task": {"preset": "tomorrow"}},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert r.data["id"] == t.pk and r.data["is_done"] is True
    assert r.data["next_task"]["due_at"].startswith("2026-11-04T10:00:00")
    assert r.data["next_task"]["invoice"]["solution"] == 1
    assert r.data["invoice"]["solution"] == 1 and r.data["closed_tasks"] == 0
    assert "address" in r.data["invoice"] and r.data["invoice"]["has_point"] is False


def test_site_api_closing_reports_closed_tasks(api, seller):
    inv = lead(seller)
    t = new_task(inv, seller)
    new_task(inv, seller)
    c = api()
    c.force_authenticate(seller)
    r = c.post(f"/api/v1/invoice-tasks/{t.pk}/done/", {"note": "kerak emas", "outcome": "dont_need"}, format="json")
    assert r.status_code == 200 and r.data["closed_tasks"] == 1 and r.data["next_task"] is None
    assert r.data["invoice"]["solution"] == 0


def test_site_api_go_for_measured_refused(api, met_seller, seller):
    inv = lead(seller)
    t = new_task(inv, met_seller, assigned_to=met_seller)
    c = api()
    c.force_authenticate(met_seller)
    r = c.post(f"/api/v1/invoice-tasks/{t.pk}/done/", {"outcome": "go_for_measured"}, format="json")
    assert r.status_code == 400 and r.data["field"] == "outcome"
    assert "O'lchov yarating" in r.data["detail"]


def test_site_api_view_only_assignee_needs_no_outcome(api, seller, make_staff):
    viewer = make_staff("call_center.view_invoice")
    t = new_task(lead(seller), seller, assigned_to=viewer, check=False)
    c = api()
    c.force_authenticate(viewer)
    r = c.post(f"/api/v1/invoice-tasks/{t.pk}/done/", {}, format="json")
    assert r.status_code == 200 and r.data["invoice"]["solution"] is None


def test_site_task_serializer_has_address_and_point(api, seller):
    inv = lead(seller, lat=41.3, lon=69.2, address="Chilonzor")
    new_task(inv, seller)
    c = api()
    c.force_authenticate(seller)
    rows = c.get("/api/v1/invoice-tasks/agenda/").data
    item = next(i for bucket in rows.values() for i in bucket)
    assert item["invoice"]["address"] == "Chilonzor" and item["invoice"]["has_point"] is True


# ------------------------------------------------------------------ bot API
def test_bot_task_detail_fixture_shape_and_errors(bot_client, seller, make_staff):
    inv = lead(seller)
    t = new_task(inv, seller)
    r = bot_client.get(f"crm/tasks/{t.pk}/", actor=4001)
    assert r.status_code == 200, r.content
    fx = load_fixture("misc.crm_task_detail_response.json")
    assert set(r.data) == set(fx)
    assert set(r.data["task"]) == set(fx["task"]) and set(r.data["invoice"]) == set(fx["invoice"])
    assert r.data["outcomes"] == [x for x in ACTIVE_ORDER if x != "go_for_measured"]
    assert r.data["next_required"] == ["re_phone"]
    assert r.data["url"].endswith(f"/call-center?open={inv.pk}")
    # a lead that is closed: keep only
    # (closing the lead through the solution would also close the task: set it directly)
    type(inv).objects.filter(pk=inv.pk).update(solution=4)
    assert bot_client.get(f"crm/tasks/{t.pk}/", actor=4001).data["outcomes"] == ["keep"]
    make_staff(*PERMS, telegram_id=4030)
    assert bot_client.get(f"crm/tasks/{t.pk}/", actor=4030).status_code == 403
    assert bot_client.get("crm/tasks/99999/", actor=4001).status_code == 404
    CC.complete_task(t, by=seller)
    assert bot_client.get(f"crm/tasks/{t.pk}/", actor=4001).status_code == 409
    assert bot_client.get(f"crm/tasks/{t.pk}/", actor=999).status_code == 403


def test_bot_done_fixture_roundtrip(bot_client, seller):
    inv = lead(seller)
    t = new_task(inv, seller)
    req = load_fixture("misc.crm_task_done_request.json")
    r = bot_client.post(f"crm/tasks/{t.pk}/done/", actor=4001, data=req)
    assert r.status_code == 200, r.content
    fx = load_fixture("misc.crm_task_done_response.json")
    assert set(r.data) == set(fx)
    assert set(r.data["invoice"]) == set(fx["invoice"])
    assert set(r.data["next_task"]) == set(fx["next_task"]) and set(r.data["task"]) == set(
        fx["task"]
    )
    assert r.data["next_task"]["due_at"] == "2026-11-04T10:00:00"
    assert r.data["invoice"]["solution"] == 1 and r.data["closed_tasks"] == 0


def test_bot_done_errors_carry_field(bot_client, seller):
    inv = lead(seller)
    t = new_task(inv, seller)
    url = f"crm/tasks/{t.pk}/done/"
    r = bot_client.post(url, actor=4001, data={})
    assert r.status_code == 400 and r.data["field"] == "outcome"
    r = bot_client.post(url, actor=4001, data={"outcome": "re_phone"})
    assert r.status_code == 400 and r.data["field"] == "next_task"
    r = bot_client.post(url, actor=4001, data={"outcome": "re_phone", "next_task": "tomorrow"})
    assert r.status_code == 400 and r.data["field"] == "next_task"
    r = bot_client.post(
        url, actor=4001, data={"outcome": "re_phone", "next_task": {"due_at": "garbage"}}
    )
    assert r.status_code == 400 and r.data["field"] == "next_task"
    r = bot_client.post(url, actor=4001, data={"outcome": 5})
    assert r.status_code == 400 and r.data["field"] == "outcome"
    r = bot_client.post(
        url,
        actor=4001,
        data={"outcome": "given_info", "next_task": {"due_at": "2026-11-05T09:30:00"}},
    )
    assert r.status_code == 200 and r.data["next_task"]["due_at"] == "2026-11-05T09:30:00"


def test_bot_due_parse_permissions(bot_client, seller, make_staff):
    make_staff("call_center.view_invoice", telegram_id=4031)
    make_staff(telegram_id=4032)
    ok = bot_client.post("crm/due/parse/", actor=4031, data={"text": "23:59"})
    assert ok.status_code == 200 and ok.data["due_at"] == "2026-11-03T23:59:00"
    assert bot_client.post("crm/due/parse/", actor=4032, data={"text": "23:59"}).status_code == 403
    assert bot_client.post("crm/due/parse/", actor=4001, data={"text": "23:59"}).status_code == 200


# ------------------------------------------------------------------ extra gaps
@pytest.mark.parametrize("outcome", ["re_phone", "given_info", "given_location"])
def test_new_lead_leaves_yangi(seller, outcome):
    inv = lead(seller)
    assert inv.solution is None
    kw = {"next_task": {"preset": "1h"}} if outcome == "re_phone" else {}
    CC.complete_task(new_task(inv, seller), by=seller, outcome=outcome, **kw)
    inv.refresh_from_db()
    assert inv.solution == S[outcome].value


def test_new_lead_cannot_stay_yangi(seller):
    inv = lead(seller)
    with pytest.raises(ServiceError) as e:
        CC.complete_task(new_task(inv, seller), by=seller, outcome="keep")
    assert field_of(e) == "outcome"
    inv.refresh_from_db()
    assert inv.solution is None and inv.tasks.filter(done_at__isnull=True).count() == 1


def test_board_solution_endpoint_to_dont_need_closes_tasks(api, seller):
    inv = lead(seller)
    new_task(inv, seller)
    new_task(inv, seller)
    c = api(*PERMS)
    c.force_authenticate(seller)
    r = c.post(f"/api/v1/invoices/{inv.pk}/solution/", {"solution": 0, "comment": "x"}, format="json")
    assert r.status_code == 200, r.content
    assert inv.tasks.filter(done_at__isnull=True).count() == 0
    assert inv.notes.filter(kind=NoteKind.solution).latest("pk").meta["closed_tasks"] == 2


def test_board_solution_response_has_no_closed_tasks(api, seller):
    inv = lead(seller)
    new_task(inv, seller)
    c = api(*PERMS)
    c.force_authenticate(seller)
    r = c.post(f"/api/v1/invoices/{inv.pk}/solution/", {"solution": 0, "comment": "x"}, format="json")
    assert r.status_code == 200, r.content
    assert r.data["open_tasks"] == 0


def test_bot_done_aware_due_at_and_bad_text(bot_client, seller):
    inv = lead(seller)
    t = new_task(inv, seller)
    url = f"crm/tasks/{t.pk}/done/"
    r = bot_client.post(
        url,
        actor=4001,
        data={"outcome": "re_phone", "next_task": {"preset": "1h", "text": 5}},
    )
    assert r.status_code == 400 and r.data["field"] == "next_task"
    r = bot_client.post(
        url,
        actor=4001,
        data={"outcome": "given_info", "next_task": {"due_at": "2026-11-05T09:30:00+05:00"}},
    )
    assert r.status_code == 200, r.content
    assert r.data["next_task"]["due_at"] == "2026-11-05T09:30:00"


def test_lock_order_invoice_before_task(seller, monkeypatch):
    """complete_task and update_lead both lock the invoice row before any task row."""
    from django.db.models.query import QuerySet

    inv = lead(seller)
    t = new_task(inv, seller)
    order = []
    orig = QuerySet.select_for_update

    def spy(self, *a, **kw):
        order.append(self.model.__name__)
        return orig(self, *a, **kw)

    monkeypatch.setattr(QuerySet, "select_for_update", spy)
    CC.complete_task(t, by=seller, outcome="given_info")
    assert order[:2] == ["Invoice", "InvoiceTask"]
    order.clear()
    CC.update_lead(inv, by=seller, source="instagram")
    assert order[0] == "Invoice"
