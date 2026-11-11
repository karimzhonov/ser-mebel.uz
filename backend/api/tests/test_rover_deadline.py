"""Rover task card in the bot, the worker's note and the production head's deadline:
events on creation, submit note rules, set/auto/remind services, bot + panel endpoints,
role migration and contract fixtures."""

import importlib
from datetime import date, datetime, timedelta

import pytest
from django.apps import apps as global_apps
from django.contrib.auth.models import Group
from djmoney.money import Money

from api.tests.botkit import load_fixture
from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from order.rover import services as RS
from order.rover import tasks
from order.rover.dto import rover_task
from order.rover.models import Rover

pytestmark = pytest.mark.django_db

WORKER = ("oauth.user_rover", "rover.view_rover", "rover.change_rover")
CHECKER = ("oauth.user_rover_checker", "rover.view_rover")
HEAD = ("oauth.user_production_head", "rover.view_rover")
NOTE = "Fasad frezerlandi, 8 ta eshik"
TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 12, 0)


def money(n="150000"):
    return Money(n, "UZS")


@pytest.fixture
def worker(make_staff):
    return make_staff(*WORKER, name="Usta", telegram_id=1001)


@pytest.fixture
def head(make_staff):
    return make_staff(*HEAD, name="Rahbar", telegram_id=2001)


@pytest.fixture
def checker(make_staff):
    return make_staff(*CHECKER, name="Tekshiruvchi", telegram_id=3001)


@pytest.fixture
def rover(order_factory):
    return Rover.objects.create(order=order_factory(), square=4, price=money("40000"))


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setattr(RS, "today", lambda: TODAY)
    monkeypatch.setattr(RS, "now", lambda: NOW)


def age(rover, **delta):
    """created_at is auto_now_add: move it back with an UPDATE."""
    Rover.objects.filter(pk=rover.pk).update(created_at=NOW - timedelta(**delta))
    return Rover.objects.get(pk=rover.pk)


# --- announce on creation ---------------------------------------------------------


def test_new_rover_task_and_due_ask_no_legacy_messages(
    order_factory, worker, head, make_staff, bot_events, monkeypatch
):
    from oauth.models import User

    def boom(*a, **k):
        raise AssertionError("legacy bare notification")

    monkeypatch.setattr(User, "send_messages", classmethod(boom))
    monkeypatch.setattr(User, "send_message", boom)
    make_staff(*WORKER, name="Telegramsiz")  # no telegram: not in `to`
    order = order_factory()
    r = RS.sync_rover_from_detailing(order, 3)
    task = bot_events.one("rover.task")
    assert task["to"] == [1001] and task["rover"]["id"] == r.pk
    ask = bot_events.one("rover.due_ask")
    assert ask["to"] == [2001] and ask["presets"] == [3, 5, 7]
    assert task["rover"]["due_date"] is None and task["rover"]["rev"] == 0


def test_no_workers_no_task_event(order_factory, head, bot_events):
    RS.sync_rover_from_detailing(order_factory(), 3)
    assert bot_events.of("rover.task") == []
    assert len(bot_events.of("rover.due_ask")) == 1


def test_sms_only_for_workers_without_telegram_and_idempotent(
    rover, worker, make_staff, monkeypatch
):
    sms = []
    monkeypatch.setattr("core.sms.send_bulk_sms", lambda batch: sms.extend(batch))
    no_tg = make_staff(*WORKER, name="Telegramsiz")
    assert tasks.rover_task_sms(rover.pk) == 1
    assert len(sms) == 1 and f"№{rover.order.order_number}" in sms[0]["text"]
    assert f"/production/rover?open={rover.pk}" in sms[0]["text"]
    assert no_tg.name in sms[0]["text"]
    assert tasks.rover_task_sms(rover.pk) == 0  # redelivery
    assert len(sms) == 1


# --- submit note ------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "  ", "ab", None, 5])
def test_submit_note_required(rover, worker, bad):
    with pytest.raises(ServiceError) as e:
        RS.submit_rover(rover, by=worker, price=money(), note=bad)
    assert e.value.field == "note"
    assert Rover.objects.get(pk=rover.pk).state == "new"


def test_submit_note_too_long(rover, worker):
    with pytest.raises(ServiceError) as e:
        RS.submit_rover(rover, by=worker, price=money(), note="x" * 2001)
    assert e.value.field == "note"


def test_submit_stores_note_bumps_rev_and_event_carries_it(rover, worker, checker, bot_events):
    before = rover.rev
    r = RS.submit_rover(rover, by=worker, price=money(), note=f"  {NOTE}  ")
    assert r.note == NOTE and Rover.objects.get(pk=rover.pk).rev == before + 1
    data = bot_events.one("rover.check")
    assert data["rover"]["note"] == NOTE and data["workers"] == [1001]
    r = RS.confirm_rover(r, by=checker)
    assert r.rev == before + 2
    assert bot_events.one("rover.checked")["workers"] == [1001]


def test_panel_done_requires_note(rover, api):
    c = api(*WORKER)
    payload = {"price": {"amount": "1000", "currency": "UZS"}}
    r = c.post(f"/api/v1/rovers/{rover.pk}/done/", payload, format="json")
    assert r.status_code == 400
    r = c.post(f"/api/v1/rovers/{rover.pk}/done/", {**payload, "note": "ab"}, format="json")
    assert r.status_code == 400 and r.data.get("field") == "note"
    r = c.post(f"/api/v1/rovers/{rover.pk}/done/", {**payload, "note": NOTE}, format="json")
    assert r.status_code == 200 and r.data["note"] == NOTE


# --- bot: submit ------------------------------------------------------------------


def test_bot_submit_endpoint(rover, worker, checker, bot_client, bot_events):
    path = f"rovers/{rover.pk}/submit/"
    good = {"amount": "250000", "note": NOTE}
    assert bot_client.post("rovers/999999/submit/", actor=1001, data=good).status_code == 404
    assert bot_client.post(path, actor=777, data=good).status_code == 403
    assert bot_client.post(path, actor=3001, data=good).status_code == 403  # checker only
    for bad in ("abc", 0, -5, "", None, True, "1e30", "12345678901", "999999999999"):
        r = bot_client.post(path, actor=1001, data={"amount": bad, "note": NOTE})
        assert r.status_code == 400 and r.json()["field"] == "amount", bad
    for bad in (None, 5, "", "ab"):
        r = bot_client.post(path, actor=1001, data={"amount": "1000", "note": bad})
        assert r.status_code == 400 and r.json()["field"] == "note", bad
    assert Rover.objects.get(pk=rover.pk).state == "new"
    ok = bot_client.post(path, actor=1001, data=good)
    assert ok.status_code == 200
    body = ok.json()["rover"]
    assert body["state"] == "checking" and body["amount"] == "250000.00" and body["note"] == NOTE
    assert len(bot_events.of("rover.check")) == 1
    assert bot_client.post(path, actor=1001, data=good).status_code == 409


# --- set_rover_due ----------------------------------------------------------------


def test_set_due_permissions(rover, worker, checker, head, make_staff, fixed_clock):
    for u in (worker, checker):
        with pytest.raises(ServiceForbidden):
            RS.set_rover_due(rover, by=u, days=3)
    root = make_staff(superuser=True)
    assert RS.set_rover_due(rover, by=root, days=3).due_date == TODAY + timedelta(days=3)
    assert RS.set_rover_due(rover, by=head, days=5).due_date == TODAY + timedelta(days=5)


def test_set_due_by_days_and_date_and_fields(rover, head, fixed_clock, bot_events):
    r = RS.set_rover_due(rover, by=head, days=5)
    assert r.due_date == TODAY + timedelta(days=5)
    assert r.due_auto is False and r.due_set_by == head and r.due_set_at == NOW and r.rev == 1
    ev = bot_events.one("rover.due_set")
    assert ev["how"] == "set" and ev["by_name"] == "Rahbar" and ev["heads"] == [2001]
    r = RS.set_rover_due(rover, by=head, due_date=TODAY)  # today is allowed
    assert r.due_date == TODAY
    assert bot_events.of("rover.due_set")[-1]["how"] == "moved"


@pytest.mark.parametrize(
    "kw",
    [
        {},
        {"days": 3, "due_date": TODAY},
        {"days": 0},
        {"days": 31},
        {"days": "3"},
        {"days": True},
        {"due_date": TODAY - timedelta(days=1)},
        {"due_date": TODAY + timedelta(days=366)},
    ],
)
def test_set_due_validation(rover, head, fixed_clock, kw):
    with pytest.raises(ServiceError) as e:
        RS.set_rover_due(rover, by=head, **kw)
    assert e.value.field == "due"
    assert Rover.objects.get(pk=rover.pk).due_date is None


def test_set_due_done_conflict(rover, worker, checker, head, fixed_clock):
    RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    RS.confirm_rover(rover, by=checker)
    with pytest.raises(ServiceConflict):
        RS.set_rover_due(rover, by=head, days=3)


def test_set_same_date_twice_one_event(rover, head, fixed_clock, bot_events):
    RS.set_rover_due(rover, by=head, days=3)
    r = RS.set_rover_due(rover, by=head, days=3)
    assert r.rev == 1 and len(bot_events.of("rover.due_set")) == 1


def test_manual_set_replaces_auto(rover, head, fixed_clock, bot_events):
    age(rover, hours=25)
    RS.auto_set_rover_dues(NOW)
    r = Rover.objects.get(pk=rover.pk)
    assert r.due_auto
    due = r.due_date
    # the same date confirmed by a person clears the auto mark and is announced
    days = (due - TODAY).days
    r = RS.set_rover_due(rover, by=head, days=days) if 1 <= days <= 30 else r
    assert r.due_auto is False and r.due_set_by == head
    assert bot_events.of("rover.due_set")[-1]["how"] == "moved"


# --- bot / panel due endpoints ----------------------------------------------------


def test_bot_due_endpoint(rover, worker, head, bot_client, bot_events):
    path = f"rovers/{rover.pk}/due/"
    assert bot_client.post("rovers/999999/due/", actor=2001, data={"days": 5}).status_code == 404
    assert bot_client.post(path, actor=777, data={"days": 5}).status_code == 403
    assert bot_client.post(path, actor=1001, data={"days": 5}).status_code == 403
    for bad in (0, "x", 31, None, 2.5, True):
        r = bot_client.post(path, actor=2001, data={"days": bad})
        assert r.status_code == 400 and r.json()["field"] == "due", bad
    ok = bot_client.post(path, actor=2001, data={"days": 5})
    assert ok.status_code == 200
    got = ok.json()["rover"]
    assert got["due_date"] and got["due_set_by"]["name"] == "Rahbar" and got["rev"] == 1
    assert len(bot_events.of("rover.due_set")) == 1


def test_bot_due_done_conflict(rover, worker, checker, head, bot_client):
    RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    RS.confirm_rover(rover, by=checker)
    r = bot_client.post(f"rovers/{rover.pk}/due/", actor=2001, data={"days": 5})
    assert r.status_code == 409


def test_panel_due_and_actions_and_overdue(rover, worker, head, api, make_staff):
    url = f"/api/v1/rovers/{rover.pk}/"
    assert api(*WORKER).get(url).data["actions"]["due"] is False
    h = api(*HEAD)
    assert h.get(url).data["actions"]["due"] is True
    assert api(*WORKER).post(url + "due/", {"due_date": "2999-01-01"}).status_code == 403
    from accounting.text import today

    past = (today() - timedelta(days=1)).isoformat()
    r = h.post(url + "due/", {"due_date": past}, format="json")
    assert r.status_code == 400 and r.data.get("field") == "due"
    ok = (today() + timedelta(days=2)).isoformat()
    r = h.post(url + "due/", {"due_date": ok}, format="json")
    assert r.status_code == 200
    assert r.data["due_date"] == ok and r.data["due_auto"] is False and r.data["overdue"] is False
    assert r.data["due_set_by_detail"]["id"] == h.user.pk
    # overdue: the date passed while the job is still new
    Rover.objects.filter(pk=rover.pk).update(due_date=today() - timedelta(days=2))
    data = h.get(url).data
    assert data["overdue"] is True
    got = h.get("/api/v1/rovers/", {"overdue": "1"}).data["results"]
    assert [x["id"] for x in got] == [rover.pk]
    assert h.get("/api/v1/rovers/", {"ordering": "due_date"}).status_code == 200


# --- auto deadline ----------------------------------------------------------------


def test_auto_due_window(order_factory, bot_events, fixed_clock):
    old = Rover.objects.create(order=order_factory(), square=1)
    fresh = Rover.objects.create(order=order_factory(), square=1)
    ancient = Rover.objects.create(order=order_factory(), square=1)
    age(old, hours=25)
    age(fresh, hours=23)
    age(ancient, days=4)
    assert RS.auto_set_rover_dues(NOW) == 1
    r = Rover.objects.get(pk=old.pk)
    assert r.due_auto and r.due_set_by is None and r.due_set_at == NOW and r.rev == 1
    assert r.due_date == r.created_at.date() + timedelta(days=5)
    assert Rover.objects.get(pk=fresh.pk).due_date is None
    assert Rover.objects.get(pk=ancient.pk).due_date is None
    assert len(bot_events.of("rover.due_set")) == 1
    ev = bot_events.of("rover.due_set")[0]
    assert ev["how"] == "auto" and ev["by_name"] is None
    assert RS.auto_set_rover_dues(NOW) == 0  # second run
    assert len(bot_events.of("rover.due_set")) == 1


def test_auto_due_skips_dated_submitted_done(order_factory, worker, head, fixed_clock):
    dated = Rover.objects.create(order=order_factory(), square=1)
    sub = Rover.objects.create(order=order_factory(), square=1)
    done = Rover.objects.create(order=order_factory(), square=1)
    for r in (dated, sub, done):
        age(r, hours=25)
    RS.set_rover_due(dated, by=head, days=3)
    RS.submit_rover(sub, by=worker, price=money(), note=NOTE)
    Rover.objects.filter(pk=done.pk).update(done=True)
    before = Rover.objects.get(pk=dated.pk).due_date
    assert RS.auto_set_rover_dues(NOW) == 0
    assert Rover.objects.get(pk=dated.pk).due_date == before


def test_auto_due_days_setting(rover, fixed_clock):
    from constance.test import override_config

    age(rover, hours=30)
    with override_config(ROVER_AUTO_DUE_DAYS=2):
        RS.auto_set_rover_dues(NOW)
    r = Rover.objects.get(pk=rover.pk)
    assert r.due_date == r.created_at.date() + timedelta(days=2)


# --- reminders --------------------------------------------------------------------


def at(day, hour):
    return datetime(day.year, day.month, day.day, hour, 0)


def test_reminders_before_hour_only_auto(rover, worker, fixed_clock, bot_events):
    early = at(TODAY, 8)
    Rover.objects.filter(pk=rover.pk).update(created_at=early - timedelta(hours=25))
    out = RS.due_rover_reminders(early)
    assert out == {"auto": 1, "soon": 0, "overdue": 0}
    assert bot_events.of("rover.remind") == []


def test_soon_once_and_rearmed_after_move(rover, worker, head, fixed_clock, bot_events):
    RS.set_rover_due(rover, by=head, days=1)  # due TODAY+1
    bot_events.clear()
    assert RS.due_rover_reminders(at(TODAY, 10))["soon"] == 1
    ev = bot_events.one("rover.remind")
    assert (
        ev["what"] == "soon" and ev["to"] == [1001] and ev["heads"] == [] and ev["days_late"] == 0
    )
    assert RS.due_rover_reminders(at(TODAY, 11))["soon"] == 0
    # moved to another date: a new once-key, fires the day before the new date
    RS.set_rover_due(rover, by=head, days=4)
    d = TODAY + timedelta(days=3)
    assert RS.due_rover_reminders(at(d, 10))["soon"] == 1
    assert len(bot_events.of("rover.remind")) == 2


def test_overdue_daily_with_heads(rover, worker, head, fixed_clock, bot_events):
    Rover.objects.filter(pk=rover.pk).update(due_date=TODAY - timedelta(days=2))
    out = RS.due_rover_reminders(at(TODAY, 10))
    assert out["overdue"] == 1
    ev = bot_events.one("rover.remind")
    assert ev["what"] == "overdue" and ev["days_late"] == 2
    assert ev["to"] == [1001] and ev["heads"] == [2001]
    assert RS.due_rover_reminders(at(TODAY, 15))["overdue"] == 0
    nxt = TODAY + timedelta(days=1)
    assert RS.due_rover_reminders(at(nxt, 10))["overdue"] == 1
    assert bot_events.of("rover.remind")[-1]["days_late"] == 3


def test_no_reminders_for_submitted(rover, worker, fixed_clock, bot_events):
    Rover.objects.filter(pk=rover.pk).update(due_date=TODAY - timedelta(days=2))
    RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    bot_events.clear()
    assert RS.due_rover_reminders(at(TODAY, 10)) == {"auto": 0, "soon": 0, "overdue": 0}
    assert bot_events.of("rover.remind") == []


def test_overdue_property(rover):
    from accounting.text import today

    assert rover.overdue is False and rover.days_late == 0
    rover.due_date = today() - timedelta(days=3)
    assert rover.overdue and rover.days_late == 3
    rover.submitted_at = NOW
    assert not rover.overdue and rover.days_late == 0


def test_schedule_has_rover_task():
    from django_celery_beat.models import PeriodicTask

    from accounting.schedule import sync_periodic_tasks

    sync_periodic_tasks()
    pt = PeriodicTask.objects.get(name="rover: muddat va eslatmalar")
    assert pt.task == "order.rover.tasks.rover_reminders" and pt.enabled


def test_reminders_task_runs(rover):
    out = tasks.rover_reminders()
    assert set(out) == {"auto", "soon", "overdue"}


# --- role + migration -------------------------------------------------------------


def _perms(g):
    return {
        f"{p.content_type.app_label}.{p.codename}"
        for p in g.permissions.select_related("content_type")
    }


def test_migration_0017_group_perms_idempotent_and_existing_untouched():
    mod = importlib.import_module("oauth.migrations.0017_production_head")
    Group.objects.filter(name="Ishlab chiqarish rahbari").delete()
    mod.create_group(global_apps, None)
    g = Group.objects.get(name="Ishlab chiqarish rahbari")
    assert _perms(g) == {"oauth.user_production_head", "rover.view_rover", "order.view_order"}
    mod.create_group(global_apps, None)
    assert Group.objects.filter(name="Ishlab chiqarish rahbari").count() == 1
    g.delete()
    custom = Group.objects.create(name="ishlab  Chiqarish rahbari")
    before = Group.objects.count()
    mod.create_group(global_apps, None)
    assert Group.objects.count() == before and custom.permissions.count() == 0


def test_access_flag_production_head_round_trip():
    from oauth import access as A

    g = Group.objects.create(name="Test rahbar")
    A.set_group_access(g, {"flag_production_head": "view"})
    assert g.permissions.filter(codename="user_production_head").exists()
    A.set_group_access(g, {"flag_production_head": "none"})
    assert not g.permissions.filter(codename="user_production_head").exists()


# --- contract fixtures ------------------------------------------------------------


def test_new_fixtures_match_real_payloads(
    order_factory, worker, head, checker, bot_client, bot_events, fixed_clock
):
    r = RS.sync_rover_from_detailing(order_factory(), 3)
    fx = load_fixture("dto.rover_task.1.json")
    assert set(rover_task(r)) == set(fx)
    for name in ("rover.task", "rover.due_ask"):
        real = bot_events.one(name)
        fixture = load_fixture(f"event.{name}.json")["data"]
        assert set(real) == set(fixture), name
        assert set(real["rover"]) == set(fx)
    RS.set_rover_due(r, by=head, days=5)
    real, fixture = (
        bot_events.one("rover.due_set"),
        load_fixture("event.rover.due_set.json")["data"],
    )
    assert set(real) == set(fixture)
    Rover.objects.filter(pk=r.pk).update(due_date=TODAY - timedelta(days=2))
    RS.due_rover_reminders(at(TODAY, 10))
    real = bot_events.one("rover.remind")
    assert set(real) == set(load_fixture("event.rover.remind.json")["data"])
    RS.submit_rover(r, by=worker, price=money(), note=NOTE)
    assert set(bot_events.one("rover.check")) == set(load_fixture("event.rover.check.json")["data"])
    RS.confirm_rover(r, by=checker)
    assert set(bot_events.one("rover.checked")) == set(
        load_fixture("event.rover.checked.json")["data"]
    )
    for name in ("misc.rover_submit_response.json", "misc.rover_due_response.json"):
        assert set(load_fixture(name)["rover"]) == set(fx)
    assert set(load_fixture("misc.rover_submit_request.json")) == {"amount", "note"}
    assert load_fixture("misc.rover_due_request.json") == {"days": 5}


# --- worker card: design folder link ---------------------------------------------


def test_design_folder_url_points_to_the_design_folder(settings):
    from types import SimpleNamespace

    from filer.models import Folder

    from order.rover.dto import design_folder_url

    settings.ADMIN_BASE_URL = "https://test.ser-mebel.uz"
    root = Folder.objects.create(name="Замеры")
    design = Folder.objects.create(name="Дизайн", parent=root)
    order_folder = Folder.objects.create(name="Заказ")
    order = SimpleNamespace(metering=SimpleNamespace(folder_id=root.pk), folder_id=order_folder.pk)
    assert design_folder_url(order) == f"https://test.ser-mebel.uz/files/{design.pk}"
    # no «Дизайн» folder → None (no fallback to the order folder)
    order.metering = SimpleNamespace(folder_id=None)
    assert design_folder_url(order) is None
    order.folder_id = None
    assert design_folder_url(order) is None


def test_rover_task_has_design_folder_key(rover):
    assert "design_folder_url" in rover_task(rover)
