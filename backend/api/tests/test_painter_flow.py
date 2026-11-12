"""Molyar (painter): activation when a type is picked, the painter's task card and «Bajardim»
with an izoh, the production head's deadline (auto after a day), reminders, site API
scoping, the role migration."""

import importlib
from datetime import date, datetime, timedelta

import pytest
from django.apps import apps as global_apps
from django.contrib.auth.models import Group
from djmoney.money import Money

from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from order.painter import services as PS
from order.painter import tasks
from order.painter.models import Painter, PainterPart, PainterType
from order.rover.models import Rover

pytestmark = pytest.mark.django_db

PAINTER_PERMS = ("painter.view_painter",)
HEAD_PERMS = ("oauth.user_production_head", "painter.view_painter")
MANAGER_PERMS = ("assembly.manager", "painter.view_painter", "painter.change_painter")
NOTE = "Fasad bo'yaldi, 8 ta eshik"
TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 12, 0)


@pytest.fixture
def mol(make_staff):
    return make_staff(*PAINTER_PERMS, name="Molyar", telegram_id=1001)


@pytest.fixture
def mol2(make_staff):
    return make_staff(*PAINTER_PERMS, name="Molyar 2", telegram_id=1002)


@pytest.fixture
def head(make_staff):
    return make_staff(*HEAD_PERMS, name="Rahbar", telegram_id=2001)


@pytest.fixture
def manager(make_staff):
    return make_staff(*MANAGER_PERMS, name="Menejer", telegram_id=3001)


@pytest.fixture
def ptype(mol):
    return PainterType.objects.create(name="Glyanets", price=Money(10, "UZS"), user=mol)


@pytest.fixture
def ptype2(mol2):
    return PainterType.objects.create(name="Mat", price=Money(20, "UZS"), user=mol2)


@pytest.fixture
def painter(order_factory):
    return Painter.objects.create(order=order_factory(), square=5)


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setattr(PS, "today", lambda: TODAY)
    monkeypatch.setattr(PS, "now", lambda: NOW)
    monkeypatch.setattr("accounting.text.today", lambda: TODAY)


@pytest.fixture
def no_legacy(monkeypatch):
    from oauth.models import User

    def boom(*a, **k):
        raise AssertionError("legacy bare notification")

    monkeypatch.setattr(User, "send_messages", classmethod(boom))
    monkeypatch.setattr(User, "send_message", boom)


OLD_EVENTS = {
    "painter.task",
    "painter.unassigned",
    "painter.due_ask",
    "painter.due_set",
    "painter.remind",
}


def fresh(p):
    return Painter.objects.get(pk=p.pk)


def at(day, hour):
    return datetime(day.year, day.month, day.day, hour, 0)


def start(painter, ptype, by=None):
    return PS.assign_whole_job(painter, ptype, by=by)


def part(p):
    """The job's only part."""
    return PainterPart.objects.get(painter_id=p.pk)


# --- 1/2. assignment starts the job -------------------------------------------------


def test_assign_starts_job_task_and_due_ask(painter, ptype, head, manager, bot_events, no_legacy):
    p = start(painter, ptype, by=head)
    assert p.started_at is not None and p.rev == 1
    assert p.price == Money(50, "UZS")  # type.price x square
    x = part(p)
    assert x.square == 5 and x.price == Money(50, "UZS") and x.started_at is not None
    task = bot_events.one("painter.part_task")
    assert task["to"] == [1001] and task["part"]["id"] == x.pk and task["reason"] == "assigned"
    assert task["part"]["painter"]["name"] == "Molyar" and task["part"]["painter_id"] == p.pk
    ask = bot_events.one("painter.part_due_ask")
    assert ask["to"] == [2001] and ask["presets"] == [5, 10, 14]
    assert bot_events.of("painter.part_unassigned") == []
    assert bot_events.one("painter.assigned")["to"] == [2001]
    # the old job-level events are gone
    assert not [n for n in bot_events.names() if n in OLD_EVENTS]


def test_assignee_without_telegram_gets_sms_once(
    painter, make_staff, monkeypatch, bot_events, head
):
    sms = []
    monkeypatch.setattr("core.sms.send_bulk_sms", lambda batch: sms.extend(batch))
    no_tg = make_staff(*PAINTER_PERMS, name="Telegramsiz")
    t = PainterType.objects.create(name="X", price=Money(1, "UZS"), user=no_tg)
    start(painter, t)
    assert bot_events.of("painter.part_task") == []
    assert len(bot_events.of("painter.part_due_ask")) == 1
    pid = part(painter).pk
    assert tasks.painter_part_task_sms(pid, no_tg.pk) == 1
    assert f"№{painter.order.order_number}" in sms[0]["text"]
    assert f"/production/painter?open={painter.pk}" in sms[0]["text"]
    assert tasks.painter_part_task_sms(pid, no_tg.pk) == 0  # redelivery
    assert len(sms) == 1


def test_sms_skipped_when_reassigned_done_or_telegram(
    painter, ptype, ptype2, mol, mol2, make_staff, monkeypatch
):
    sms = []
    monkeypatch.setattr("core.sms.send_bulk_sms", lambda batch: sms.extend(batch))
    start(painter, ptype)
    pid = part(painter).pk
    assert tasks.painter_part_task_sms(pid, mol.pk) == 0  # has Telegram
    no_tg = make_staff(*PAINTER_PERMS, name="NoTg")
    t = PainterType.objects.create(name="Y", price=Money(1, "UZS"), user=no_tg)
    start(painter, t)
    start(painter, ptype2)  # reassigned away from no_tg
    assert tasks.painter_part_task_sms(pid, no_tg.pk) == 0
    PainterPart.objects.filter(pk=pid).update(done=True)
    assert tasks.painter_part_task_sms(pid, mol2.pk) == 0
    assert sms == []


# --- 3. reassignment ----------------------------------------------------------------


def test_reassign_unassigns_old_and_tasks_new(painter, ptype, ptype2, head, bot_events):
    p = start(painter, ptype)
    started = part(p).started_at
    pid = part(p).pk
    bot_events.clear()
    p = start(painter, ptype2)
    un = bot_events.one("painter.part_unassigned")
    assert un["to"] == [1001] and un["prev"]["name"] == "Molyar"
    assert un["part"]["painter"]["name"] == "Molyar 2"
    assert bot_events.one("painter.part_task")["to"] == [1002]
    assert bot_events.of("painter.part_due_ask") == []
    x = part(p)
    assert x.pk == pid and x.started_at == started and x.rev == 2 and p.rev == 2


def test_same_user_type_switch_no_events(painter, ptype, mol, bot_events):
    start(painter, ptype)
    other = PainterType.objects.create(name="Boshqa", price=Money(30, "UZS"), user=mol)
    bot_events.clear()
    p = start(painter, other)
    assert bot_events == [] and p.price == Money(150, "UZS")


def test_clear_type_only_unassigned(painter, ptype, head, bot_events):
    start(painter, ptype)
    bot_events.clear()
    p = start(painter, None, by=head)
    assert bot_events.names() == ["painter.part_unassigned", "painter.assigned"]
    assert not PainterPart.objects.filter(painter=p).exists() and p.started_at is not None


def test_type_change_on_done_job_refused(painter, ptype, ptype2, mol, bot_events):
    start(painter, ptype)
    PS.mark_painter_done(painter, by=mol, note=NOTE)
    bot_events.clear()
    with pytest.raises(ServiceConflict):
        start(painter, ptype2)
    assert bot_events.names() == []


# --- 4. guards ----------------------------------------------------------------------


def test_assign_while_rover_unfinished_refused(order_factory, ptype):
    order = order_factory()
    Rover.objects.create(order=order, square=3)
    p = Painter.objects.create(order=order, square=5)
    with pytest.raises(ServiceError):
        start(p, ptype)
    assert fresh(p).started_at is None


def test_type_without_user_refused(painter):
    t = PainterType.objects.create(name="Egasiz", price=Money(1, "UZS"))
    with pytest.raises(ServiceError):
        start(painter, t)


def test_legacy_admin_save_activates(painter, ptype, bot_events, head, no_legacy):
    painter.type = ptype
    painter.save(update_fields=["type"])  # what the frozen admin does
    p = fresh(painter)
    assert p.price == Money(50, "UZS") and p.started_at is not None
    assert part(p).square == 5 and part(p).type == ptype
    assert bot_events.one("painter.part_task")["to"] == [1001]
    assert len(bot_events.of("painter.part_due_ask")) == 1
    # a split job ignores the admin's type edit
    painter.save(update_fields=["type"])
    assert PainterPart.objects.filter(painter=p).count() == 1


# --- 5. rover confirmed -------------------------------------------------------------


def _rover_painter(order_factory):
    order = order_factory()
    rover = Rover.objects.create(order=order, square=3)
    return rover, Painter.objects.create(order=order, square=5)


def test_rover_finished_asks_heads_for_team_and_activates(
    order_factory, ptype, manager, head, bot_events, no_legacy
):
    rover, p = _rover_painter(order_factory)
    Painter.objects.filter(pk=p.pk).update(type=ptype)  # chosen earlier (legacy)
    Rover.objects.filter(pk=rover.pk).update(done=True)
    assert tasks_ready(rover) is True
    ready = bot_events.one("painter.ready")
    assert ready["to"] == [2001]  # the production head, not the assembly manager
    assert [t["name"] for t in ready["types"]] == ["Glyanets"]
    assert bot_events.one("painter.part_task")["to"] == [1001]
    assert len(bot_events.of("painter.part_due_ask")) == 1
    assert tasks_ready(rover) is False  # once
    assert fresh(p).started_at is not None


def tasks_ready(rover):
    from order.rover.tasks import notify_painting_ready_task

    return notify_painting_ready_task(rover.pk)


def test_rover_finished_without_type_only_ready(
    order_factory, manager, head, ptype, mol2, bot_events
):
    PainterType.objects.create(name="Teamless", price=Money(1, "UZS"), user=None)
    PainterType.objects.create(name="Aaa", price=Money(1, "UZS"), user=mol2)
    rover, p = _rover_painter(order_factory)
    Rover.objects.filter(pk=rover.pk).update(done=True)
    tasks_ready(rover)
    assert "painter.part_task" not in bot_events.names()
    ready = bot_events.one("painter.ready")
    assert ready["to"] == [2001]
    assert ready["painter"]["parts"] == [] and ready["painter"]["remainder"] == 5
    assert ready["painter"]["split_url"].endswith(f"?open={p.pk}&split=1")
    # only teams with a user, by name
    assert [t["name"] for t in ready["types"]] == ["Aaa", "Glyanets"]
    assert ready["types"][1] == {
        "id": ptype.pk,
        "name": "Glyanets",
        "user": {"id": ptype.user.pk, "name": "Molyar"},
    }
    assert fresh(p).started_at is None and not PainterPart.objects.filter(painter=p).exists()


def test_rover_finished_no_painter_row_is_noop(order_factory, bot_events):
    rover = Rover.objects.create(order=order_factory(), square=3, done=True)
    assert tasks_ready(rover) is True
    assert bot_events == []


# --- 6. done ------------------------------------------------------------------------


def test_done_by_assignee(painter, ptype, mol, head, manager, bot_events):
    start(painter, ptype)
    price = fresh(painter).price
    bot_events.clear()
    p = PS.mark_painter_done(painter, by=mol, note="  " + NOTE + " ")
    assert p.done and p.note == NOTE and p.done_by == mol and p.done_at is not None
    assert p.rev == 2 and p.price == price and p.state == "done"
    ev = bot_events.one("painter.done")
    assert ev["by_name"] == "Molyar" and ev["heads"] == [2001]
    assert ev["to"] == [2001, 3001] and ev["painters"] == [1001]
    assert ev["painter"]["state"] == "done" and ev["painter"]["note"] == NOTE
    pd = bot_events.one("painter.part_done")
    assert pd["job_done"] is True and pd["part"]["state"] == "done" and pd["painters"] == [1001]


def test_done_by_change_painter_holder(painter, ptype, manager):
    start(painter, ptype)
    assert PS.mark_painter_done(painter, by=manager, note=NOTE).done_by == manager


def test_done_forbidden_for_others(painter, ptype, mol2):
    start(painter, ptype)
    with pytest.raises(ServiceForbidden):
        PS.mark_painter_done(painter, by=mol2, note=NOTE)
    assert fresh(painter).done is False


@pytest.mark.parametrize("bad", ["", "  ab ", "x" * 2001, None, 5])
def test_done_note_rules(painter, ptype, mol, bad):
    start(painter, ptype)
    with pytest.raises(ServiceError) as e:
        PS.mark_painter_done(painter, by=mol, note=bad)
    assert e.value.field == "note"


def test_done_twice_conflict_and_rover_unfinished(painter, ptype, mol, order_factory):
    start(painter, ptype)
    PS.mark_painter_done(painter, by=mol, note=NOTE)
    with pytest.raises(ServiceConflict):
        PS.mark_painter_done(painter, by=mol, note=NOTE)
    order = order_factory()
    Rover.objects.create(order=order, square=3)
    waiting = Painter.objects.create(order=order, square=5)
    PainterPart.objects.create(painter=waiting, type=ptype, square=5)
    with pytest.raises(ServiceError) as e:
        PS.mark_painter_done(fresh(waiting), by=mol, note=NOTE)
    assert not isinstance(e.value, (ServiceForbidden, ServiceConflict))


# --- 8. set due ---------------------------------------------------------------------


def test_set_due_set_then_moved(painter, ptype, head, mol, bot_events, fixed_clock):
    start(painter, ptype)
    bot_events.clear()
    PS.set_painter_due(painter, by=head, days=5)
    x = part(painter)
    assert x.due_date == TODAY + timedelta(days=5) and not x.due_auto and x.due_set_by == head
    ev = bot_events.one("painter.part_due_set")
    assert ev["how"] == "set" and ev["by_name"] == "Rahbar"
    assert ev["to"] == [1001] and ev["heads"] == [2001]
    PS.set_painter_due(painter, by=head, days=10)
    assert bot_events.of("painter.part_due_set")[-1]["how"] == "moved"
    rev = part(painter).rev
    PS.set_painter_due(painter, by=head, days=10)  # same date: no-op
    assert part(painter).rev == rev and len(bot_events.of("painter.part_due_set")) == 2


def test_set_due_rules(painter, ptype, head, mol, fixed_clock):
    start(painter, ptype)
    with pytest.raises(ServiceForbidden):
        PS.set_painter_due(painter, by=mol, days=5)
    for bad in (0, 31, "5", True):
        with pytest.raises(ServiceError) as e:
            PS.set_painter_due(painter, by=head, days=bad)
        assert e.value.field == "due"
    with pytest.raises(ServiceError):
        PS.set_painter_due(painter, by=head, due_date=TODAY - timedelta(days=1))
    with pytest.raises(ServiceError):
        PS.set_painter_due(painter, by=head, due_date=TODAY + timedelta(days=400))
    PS.mark_painter_done(painter, by=mol, note=NOTE)
    with pytest.raises(ServiceConflict):
        PS.set_painter_due(painter, by=head, days=5)


# --- 9. auto deadline ---------------------------------------------------------------


def started_ago(p, **delta):
    PainterPart.objects.filter(painter=p).update(started_at=NOW - timedelta(**delta))


def test_auto_due_window(order_factory, ptype, head, bot_events, fixed_clock):
    ps = [Painter.objects.create(order=order_factory(), square=1) for _ in range(4)]
    for p in ps[:3]:
        start(p, ptype)
    started_ago(ps[0], hours=25)  # due for auto
    started_ago(ps[1], hours=23)  # too fresh
    started_ago(ps[2], days=4)  # too old
    bot_events.clear()  # ps[3] never started: started_at NULL
    assert PS.auto_set_painter_dues(NOW) == 1
    r = part(ps[0])
    assert r.due_auto and r.due_set_by is None and r.due_set_at == NOW
    assert r.due_date == r.started_at.date() + timedelta(days=10)
    assert all(part(p).due_date is None for p in ps[1:3])
    ev = bot_events.one("painter.part_due_set")
    assert ev["how"] == "auto" and ev["by_name"] is None
    assert PS.auto_set_painter_dues(NOW) == 0


def test_auto_due_skips_done_and_dated(order_factory, ptype, head, mol, fixed_clock):
    dated = Painter.objects.create(order=order_factory(), square=1)
    done = Painter.objects.create(order=order_factory(), square=1)
    start(dated, ptype)
    start(done, ptype)
    PS.set_painter_due(dated, by=head, days=3)
    PS.mark_painter_done(done, by=mol, note=NOTE)
    for p in (dated, done):
        started_ago(p, hours=25)
    before = part(dated).due_date
    assert PS.auto_set_painter_dues(NOW) == 0
    assert part(dated).due_date == before and part(done).due_date is None


def test_auto_due_days_setting(painter, ptype, fixed_clock):
    from constance.test import override_config

    start(painter, ptype)
    started_ago(painter, hours=30)
    with override_config(PAINTER_AUTO_DUE_DAYS=2):
        PS.auto_set_painter_dues(NOW)
    p = part(painter)
    assert p.due_date == p.started_at.date() + timedelta(days=2)


# --- 10. reminders ------------------------------------------------------------------


def test_reminders_before_hour_only_auto(painter, ptype, fixed_clock, bot_events):
    start(painter, ptype)
    early = at(TODAY, 8)
    PainterPart.objects.filter(painter=painter).update(started_at=early - timedelta(hours=25))
    assert PS.due_painter_reminders(early) == {"auto": 1, "soon": 0, "overdue": 0}
    assert bot_events.of("painter.part_remind") == []


def test_soon_once_painter_only(painter, ptype, head, fixed_clock, bot_events):
    start(painter, ptype)
    PS.set_painter_due(painter, by=head, days=1)
    bot_events.clear()
    assert PS.due_painter_reminders(at(TODAY, 10))["soon"] == 1
    ev = bot_events.one("painter.part_remind")
    assert ev["what"] == "soon" and ev["to"] == [1001] and ev["heads"] == []
    assert PS.due_painter_reminders(at(TODAY, 11))["soon"] == 0


def test_soon_key_not_burned_without_telegram(painter, make_staff, head, fixed_clock, bot_events):
    no_tg = make_staff(*PAINTER_PERMS, name="NoTg")
    t = PainterType.objects.create(name="Z", price=Money(1, "UZS"), user=no_tg)
    start(painter, t)
    PS.set_painter_due(painter, by=head, days=1)
    bot_events.clear()
    assert PS.due_painter_reminders(at(TODAY, 10))["soon"] == 0
    no_tg.telegram_id = 5555
    no_tg.save()
    assert PS.due_painter_reminders(at(TODAY, 11))["soon"] == 1


def test_overdue_daily_painter_and_heads(painter, ptype, head, fixed_clock, bot_events):
    start(painter, ptype)
    PainterPart.objects.filter(painter=painter).update(due_date=TODAY - timedelta(days=2))
    assert PS.due_painter_reminders(at(TODAY, 10))["overdue"] == 1
    ev = bot_events.of("painter.part_remind")[-1]
    assert ev["what"] == "overdue" and ev["days_late"] == 2
    assert ev["to"] == [1001] and ev["heads"] == [2001]
    assert PS.due_painter_reminders(at(TODAY, 15))["overdue"] == 0
    assert PS.due_painter_reminders(at(TODAY + timedelta(days=1), 10))["overdue"] == 1
    assert bot_events.of("painter.part_remind")[-1]["days_late"] == 3


def test_reminders_skip_done_and_waiting_for_rover(
    order_factory, painter, ptype, mol, fixed_clock, bot_events
):
    start(painter, ptype)
    PS.mark_painter_done(painter, by=mol, note=NOTE)
    waiting_order = order_factory()
    Rover.objects.create(order=waiting_order, square=3)
    waiting = Painter.objects.create(order=waiting_order, square=2)
    PainterPart.objects.create(painter=waiting, type=ptype, square=2)
    old = TODAY - timedelta(days=2)
    PainterPart.objects.filter(painter__in=[painter, waiting]).update(due_date=old)
    bot_events.clear()
    assert PS.due_painter_reminders(at(TODAY, 10)) == {"auto": 0, "soon": 0, "overdue": 0}
    assert bot_events.of("painter.part_remind") == []


def test_property_overdue(painter, ptype, mol):
    from accounting.text import today

    assert painter.overdue is False and painter.days_late == 0
    painter.due_date = today() - timedelta(days=3)
    assert painter.overdue and painter.days_late == 3
    painter.done = True
    assert not painter.overdue and painter.days_late == 0


# --- 11. site API -------------------------------------------------------------------


def test_list_scoping_head_sees_all_painter_own(order_factory, ptype, ptype2, api, mol, mol2):
    a = Painter.objects.create(order=order_factory(), square=1)
    b = Painter.objects.create(order=order_factory(), square=1)
    start(a, ptype)
    start(b, ptype2)
    head_api = api(*HEAD_PERMS)
    assert head_api.get("/api/v1/painters/").data["count"] == 2
    c = api(*PAINTER_PERMS)
    c.force_authenticate(mol)
    got = c.get("/api/v1/painters/").data["results"]
    assert [x["id"] for x in got] == [a.pk]


def test_done_open_to_assignee_without_change_perm(painter, ptype, api, mol, mol2, bot_events):
    start(painter, ptype)
    url = f"/api/v1/painters/{painter.pk}/done/"
    c = api(*PAINTER_PERMS)
    c.force_authenticate(mol)
    data = c.get(f"/api/v1/painters/{painter.pk}/").data
    assert data["actions"]["done"] is True and data["actions"]["due"] is False
    r = c.post(url, {"note": "ab"}, format="json")
    assert r.status_code == 400 and r.data.get("field") == "note"
    r = c.post(url, {"note": NOTE}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["state"] == "done" and r.data["note"] == NOTE
    assert r.data["done_by_detail"]["id"] == mol.pk and r.data["painter_detail"]["id"] == mol.pk
    assert r.data["parts"][0]["done"] is True
    other = api(*PAINTER_PERMS)
    other.force_authenticate(mol2)
    assert other.post(url, {"note": NOTE}, format="json").status_code == 404


def test_done_by_manager_and_actions_flags(painter, ptype, api, manager):
    start(painter, ptype)
    m = api(*MANAGER_PERMS)
    url = f"/api/v1/painters/{painter.pk}/"
    assert m.get(url).data["actions"] == {"edit": False, "done": True, "due": False}
    assert m.post(url + "done/", {"note": NOTE}, format="json").status_code == 200
    assert m.get(url).data["actions"]["done"] is False


def test_assign_via_api_passes_user(painter, ptype, api, bot_events, head):
    h = api(*HEAD_PERMS, "painter.change_painter")
    r = h.patch(f"/api/v1/painters/{painter.pk}/", {"type": ptype.pk}, format="json")
    assert r.status_code == 200 and r.data["painter_detail"]["name"] == "Molyar"
    assert r.data["started_at"] is not None
    assert len(bot_events.of("painter.part_task")) == 1


def test_assign_action_head_only(painter, ptype, api, bot_events, head):
    url = f"/api/v1/painters/{painter.pk}/assign/"
    body = {"type": ptype.pk}
    h = api(*HEAD_PERMS)
    r = h.post(url, body, format="json")
    assert r.status_code == 200 and r.data["type"] == ptype.pk
    assert r.data["actions"]["edit"] is True and r.data["actions"]["done"] is False
    # assembly manager (view only now) and the painter are refused
    assert api(*MANAGER_PERMS).post(url, body, format="json").status_code in (400, 403)
    assert api(*PAINTER_PERMS).post(url, body, format="json").status_code == 403
    m = api(*MANAGER_PERMS)
    assert m.patch(f"/api/v1/painters/{painter.pk}/", body, format="json").status_code in (400, 403)
    # clearing and a missing type
    assert h.post(url, {"type": None}, format="json").status_code == 200
    assert h.post(url, {"type": 99999}, format="json").status_code == 400


def test_service_assign_by_non_head_forbidden(painter, ptype, manager, mol):
    for user in (manager, mol):
        with pytest.raises(ServiceForbidden):
            PS.assign_painter_type(painter, ptype, by=user)
    assert not PainterPart.objects.filter(painter=painter).exists()


def test_same_type_repick_starts_legacy_row(painter, ptype, head, bot_events, no_legacy):
    # legacy: a part that never started
    PainterPart.objects.create(painter=painter, type=ptype, square=5)
    assert part(painter).started_at is None
    start(painter, ptype, by=head)
    assert part(painter).started_at is not None and fresh(painter).started_at is not None
    assert len(bot_events.of("painter.part_task")) == 1
    assert len(bot_events.of("painter.part_due_ask")) == 1
    start(painter, ptype, by=head)  # idempotent
    assert len(bot_events.of("painter.part_task")) == 1


def test_due_ask_skipped_when_due_already_set(painter, ptype, head, bot_events):
    PainterPart.objects.create(painter=painter, type=ptype, square=5, due_date=date(2030, 1, 1))
    start(painter, ptype, by=head)
    assert len(bot_events.of("painter.part_task")) == 1
    assert bot_events.of("painter.part_due_ask") == []


def test_actions_edit_and_done_are_bools(painter, ptype, api, head):
    start(painter, ptype)
    for perms in (HEAD_PERMS, MANAGER_PERMS):
        a = api(*perms).get(f"/api/v1/painters/{painter.pk}/").data["actions"]
        assert all(type(v) is bool for v in a.values()), (perms, a)


def test_panel_due_overdue_filter_and_ordering(painter, ptype, api, head):
    start(painter, ptype)
    h = api(*HEAD_PERMS)
    url = f"/api/v1/painters/{painter.pk}/"
    assert h.get(url).data["actions"]["due"] is True
    assert api(*PAINTER_PERMS).post(url + "due/", {"due_date": "2999-01-01"}).status_code == 403
    from accounting.text import today

    past = (today() - timedelta(days=1)).isoformat()
    r = h.post(url + "due/", {"due_date": past}, format="json")
    assert r.status_code == 400 and r.data.get("field") == "due"
    ok = (today() + timedelta(days=2)).isoformat()
    r = h.post(url + "due/", {"due_date": ok}, format="json")
    assert r.status_code == 200 and r.data["due_date"] == ok and r.data["state"] == "new"
    PainterPart.objects.filter(painter=painter).update(due_date=today() - timedelta(days=2))
    got = h.get("/api/v1/painters/", {"overdue": "1"}).data["results"]
    assert [x["id"] for x in got] == [painter.pk] and got[0]["overdue"] is True
    assert h.get("/api/v1/painters/", {"ordering": "due_date"}).status_code == 200


# --- 12. migration 0009 -------------------------------------------------------------


def _perms(g):
    return {
        f"{p.content_type.app_label}.{p.codename}"
        for p in g.permissions.select_related("content_type")
    }


def test_migration_0009_additive_idempotent_noop():
    mod = importlib.import_module("order.painter.migrations.0009_production_head_view_painter")
    Group.objects.filter(name="Ishlab chiqarish rahbari").delete()
    mod.add_view_painter(global_apps, None)  # no group: nothing is created
    assert not Group.objects.filter(name="Ishlab chiqarish rahbari").exists()
    g = Group.objects.create(name="ishlab  Chiqarish rahbari")
    other = Group.objects.create(name="Boshqa")
    mod.add_view_painter(global_apps, None)
    mod.add_view_painter(global_apps, None)
    assert _perms(g) == {"painter.view_painter"} and other.permissions.count() == 0


# --- 14. schedule + task ------------------------------------------------------------


def test_schedule_has_painter_task():
    from django_celery_beat.models import PeriodicTask

    from accounting.schedule import sync_periodic_tasks

    sync_periodic_tasks()
    pt = PeriodicTask.objects.get(name="molyar: muddat va eslatmalar")
    assert pt.task == "order.painter.tasks.painter_reminders" and pt.enabled


def test_reminders_task_runs(painter):
    assert set(tasks.painter_reminders()) == {"auto", "soon", "overdue"}


def test_migration_0010_additive_idempotent():
    mod = importlib.import_module("order.painter.migrations.0010_production_head_paintertype")
    g, _ = Group.objects.get_or_create(name="Ishlab chiqarish rahbari")
    other = Group.objects.create(name="Boshqa")
    before = _perms(other)
    mod.add_view_paintertype(global_apps, None)
    mod.add_view_paintertype(global_apps, None)
    assert "painter.view_paintertype" in _perms(g)
    assert _perms(other) == before
    Group.objects.all().delete()
    mod.add_view_paintertype(global_apps, None)  # no group: no-op
