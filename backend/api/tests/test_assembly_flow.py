"""Yig'ish/O'rnatish (assembly): the heads pick the team when the order goes to «Сборка», the
assembler's task card and «O'rnatildi» with an izoh, the heads' deadline (auto after a day),
reminders, site API scoping, the role migration."""

import importlib
from datetime import date, datetime, timedelta

import pytest
from django.apps import apps as global_apps
from django.contrib.auth.models import Group

from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from core.sms import format_phone
from order.assembly import services as AS
from order.assembly import tasks
from order.assembly.models import Assembly
from order.constants import OrderStatus
from order.models import Order
from order.services import advance_order_status, send_order_to_assembly

pytestmark = pytest.mark.django_db

ASM_PERMS = ("oauth.user_assembly", "assembly.view_assembly")
HEAD_PERMS = ("oauth.user_production_head", "assembly.view_assembly")
MANAGER_PERMS = ("assembly.manager", "assembly.view_assembly", "assembly.change_assembly")
NOTE = "Oshxona yig'ildi va o'rnatildi, 4 eshik"
TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 12, 0)


@pytest.fixture
def asm(make_staff):
    return make_staff(*ASM_PERMS, name="Yig'uvchi A", telegram_id=1001)


@pytest.fixture
def asm2(make_staff):
    return make_staff(*ASM_PERMS, name="Yig'uvchi B", telegram_id=1002)


@pytest.fixture
def head(make_staff):
    return make_staff(*HEAD_PERMS, name="Rahbar", telegram_id=2001)


@pytest.fixture
def manager(make_staff):
    return make_staff(*MANAGER_PERMS, name="Menejer", telegram_id=3001)


@pytest.fixture
def sms(monkeypatch):
    """Collects every SMS (status broadcasts and the task SMS); nothing hits the network."""
    batches = []
    monkeypatch.setattr("oauth.services.send_bulk_sms", lambda b: batches.extend(b))
    monkeypatch.setattr("core.sms.send_bulk_sms", lambda b: batches.extend(b))
    monkeypatch.setattr("order.assembly.tasks.assembly_task_sms.delay", lambda *a: None)
    return batches


@pytest.fixture
def no_telegram_msgs(monkeypatch):
    from oauth.models import User

    def boom(*a, **k):
        raise AssertionError("legacy bare Telegram message")

    monkeypatch.setattr(User, "send_message", boom)


def _order(order_factory, status=OrderStatus.WORKING):
    order = order_factory()
    Order.objects.filter(pk=order.pk).update(status=status)
    return Order.objects.get(pk=order.pk)


@pytest.fixture
def assembly(order_factory, sms):
    """A row of an order still in «Xomashyo buyurtmasi» (WORKING)."""
    return Assembly.objects.create(order=_order(order_factory), square=5)


@pytest.fixture
def live(order_factory, sms):
    """A row of an order already in «Сборка»."""
    return Assembly.objects.create(order=_order(order_factory, OrderStatus.ASSEMBLY), square=5)


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setattr(AS, "today", lambda: TODAY)
    monkeypatch.setattr(AS, "now", lambda: NOW)
    monkeypatch.setattr("accounting.text.today", lambda: TODAY)


@pytest.fixture
def order_ready(monkeypatch, bot_events):  # also makes on_commit run at once
    calls = []
    monkeypatch.setattr("accounting.tasks.order_ready.delay", lambda ref: calls.append(ref))
    return calls


def fresh(a):
    return Assembly.objects.get(pk=a.pk)


def at(day, hour):
    return datetime(day.year, day.month, day.day, hour, 0)


def go_assembly(a):
    return send_order_to_assembly(Order.objects.get(pk=a.order_id))


# --- 1. the trigger -----------------------------------------------------------------


def test_go_to_assembly_asks_heads_to_pick_team(
    assembly, asm, asm2, head, manager, make_staff, bot_events, sms, no_telegram_msgs
):
    inactive = make_staff(*ASM_PERMS, name="A-nofaol", telegram_id=1003)
    inactive.is_active = False
    inactive.save()
    no_tg_viewer = make_staff("assembly.view_assembly", name="Telegramsiz")
    go_assembly(assembly)
    ready = bot_events.one("assembly.ready")
    assert ready["to"] == [2001]  # heads only, not the manager
    assert [u["name"] for u in ready["assemblers"]] == ["Yig'uvchi A", "Yig'uvchi B"]
    assert ready["assembly"]["id"] == assembly.pk and ready["assembly"]["assembler"] is None
    assert ready["assembly"]["state"] == "new" and "amount" not in str(ready["assembly"])
    # SMS only for view_assembly holders WITHOUT Telegram
    phones = {m["phone"] for m in sms}
    assert phones == {format_phone(no_tg_viewer.phone)}
    assert bot_events.of("assembly.task") == []


def test_next_status_working_to_assembly_also_triggers(assembly, head, bot_events, sms):
    advance_order_status(Order.objects.get(pk=assembly.order_id))
    assert Order.objects.get(pk=assembly.order_id).status == OrderStatus.ASSEMBLY
    assert len(bot_events.of("assembly.ready")) == 1


def test_ready_without_assembler_row_and_without_head_telegram(
    order_factory, head, bot_events, sms
):
    order = _order(order_factory)  # no Assembly row at all: nothing breaks
    order.change_status(OrderStatus.ASSEMBLY)
    assert bot_events == []
    a = Assembly.objects.create(order=_order(order_factory), square=1)
    head.telegram_id = None
    head.save()
    go_assembly(a)
    assert bot_events.of("assembly.ready") == []


def test_ready_once_per_job(assembly, head, bot_events, sms):
    go_assembly(assembly)
    AS.on_order_assembly(Order.objects.get(pk=assembly.order_id))
    assert len(bot_events.of("assembly.ready")) == 1


def test_other_status_broadcasts_unchanged(order_factory, make_staff, monkeypatch):
    from oauth.models import User

    calls = []
    monkeypatch.setattr(User, "send_messages", classmethod(lambda cls, *a, **k: calls.append(k)))
    for status in (OrderStatus.DETAILING, OrderStatus.WORKING, OrderStatus.INSTALLING):
        _order(order_factory, OrderStatus.CREATED).change_status(status)
    assert len(calls) == 3
    assert all("telegram" not in k and "sms_only_without_telegram" not in k for k in calls)
    _order(order_factory, OrderStatus.WORKING).change_status(OrderStatus.ASSEMBLY)
    assert calls[-1]["telegram"] is False and calls[-1]["sms_only_without_telegram"] is True


# --- 2. creating the row sends nothing -----------------------------------------------


def test_assembly_creation_sends_nothing(order_factory, monkeypatch, bot_events):
    from oauth.models import User

    def boom(*a, **k):
        raise AssertionError("legacy broadcast on creation")

    monkeypatch.setattr(User, "send_messages", classmethod(boom))
    monkeypatch.setattr(User, "send_message", boom)
    a = Assembly.objects.create(order=order_factory(), square=2)
    assert a.pk and bot_events == []


# --- 3. the head picks the assembler --------------------------------------------------


def test_assign_after_assembly_starts_job(live, asm, head, bot_events, sms):
    a = AS.assign_assembler(live, asm, by=head)
    assert a.started_at is not None and a.rev == 1 and a.user == asm
    task = bot_events.one("assembly.task")
    assert task["to"] == [1001] and task["assembly"]["assembler"]["name"] == "Yig'uvchi A"
    ask = bot_events.one("assembly.due_ask")
    assert ask["to"] == [2001] and ask["presets"] == [5, 10, 14]
    assert bot_events.of("assembly.unassigned") == []


def test_assign_via_site_api(live, asm, head, api, bot_events):
    h = api(*HEAD_PERMS)
    r = h.post(f"/api/v1/assemblies/{live.pk}/assign/", {"user": asm.pk}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["user_detail"]["id"] == asm.pk and r.data["started_at"]
    assert r.data["actions"]["edit"] is True and r.data["state"] == "new"


def test_assignee_without_telegram_gets_sms_once(live, make_staff, head, bot_events, sms):
    no_tg = make_staff(*ASM_PERMS, name="Telegramsiz")
    AS.assign_assembler(live, no_tg, by=head)
    assert bot_events.of("assembly.task") == []
    assert len(bot_events.of("assembly.due_ask")) == 1
    assert tasks.assembly_task_sms(live.pk, no_tg.pk) == 1
    text = sms[-1]["text"]
    assert f"№{live.order.order_number}" in text and "Test address" in text
    assert f"/production/assembly?open={live.pk}" in text
    assert tasks.assembly_task_sms(live.pk, no_tg.pk) == 0  # redelivery
    assert len([m for m in sms if "Yig'ish/O'rnatish" in m["text"]]) == 1


def test_sms_skipped_when_reassigned_finished_or_telegram(
    live, asm, asm2, make_staff, head, order_ready, sms
):
    AS.assign_assembler(live, asm, by=head)
    assert tasks.assembly_task_sms(live.pk, asm.pk) == 0  # has Telegram
    no_tg = make_staff(*ASM_PERMS, name="NoTg")
    AS.assign_assembler(live, no_tg, by=head)
    AS.assign_assembler(live, asm2, by=head)  # away from no_tg
    assert tasks.assembly_task_sms(live.pk, no_tg.pk) == 0
    AS.finish_assembly(live, by=asm2, note=NOTE)
    assert tasks.assembly_task_sms(live.pk, asm2.pk) == 0  # finished_at set (checking): no task SMS
    assert not [m for m in sms if "Yig'ish/O'rnatish" in m["text"]]


def test_reassign_in_checking_is_refused(live, asm, asm2, head, order_ready, bot_events, sms):
    AS.assign_assembler(live, asm, by=head)
    live = AS.finish_assembly(live, by=asm, note=NOTE)
    assert live.finished_at is not None and not live.installing_done
    n_task = len(bot_events.of("assembly.task"))
    n_un = len(bot_events.of("assembly.unassigned"))
    sms.clear()
    with pytest.raises(ServiceConflict):
        AS.assign_assembler(live, asm2, by=head)
    with pytest.raises(ServiceConflict):
        AS.assign_assembler(live, None, by=head)
    with pytest.raises(ServiceConflict):
        AS.assign_assembler(live, asm, by=head)
    live.refresh_from_db()
    assert live.user_id == asm.pk
    assert len(bot_events.of("assembly.task")) == n_task
    assert len(bot_events.of("assembly.unassigned")) == n_un
    assert sms == []


# --- 4. pre-assignment / legacy rows ------------------------------------------------


def test_preassignment_while_working_then_trigger(assembly, asm, head, bot_events, sms):
    a = AS.assign_assembler(assembly, asm, by=head)
    assert a.user == asm and a.started_at is None
    assert bot_events == []
    go_assembly(assembly)
    assert len(bot_events.of("assembly.ready")) == 1
    assert bot_events.one("assembly.task")["to"] == [1001]
    assert len(bot_events.of("assembly.due_ask")) == 1
    assert fresh(assembly).started_at is not None


def test_same_user_repick_starts_legacy_row(live, asm, head, bot_events):
    Assembly.objects.filter(pk=live.pk).update(user=asm)
    assert fresh(live).started_at is None
    a = AS.assign_assembler(live, asm, by=head)
    assert a.started_at is not None
    assert len(bot_events.of("assembly.task")) == 1
    AS.assign_assembler(live, asm, by=head)  # idempotent
    assert len(bot_events.of("assembly.task")) == 1


def test_due_ask_skipped_when_due_already_set(live, asm, head, bot_events):
    Assembly.objects.filter(pk=live.pk).update(due_date=date(2030, 1, 1))
    AS.assign_assembler(live, asm, by=head)
    assert len(bot_events.of("assembly.task")) == 1
    assert bot_events.of("assembly.due_ask") == []


# --- 5. reassign / clear / guards ---------------------------------------------------


def test_reassign_unassigns_old_and_tasks_new(live, asm, asm2, head, bot_events):
    a = AS.assign_assembler(live, asm, by=head)
    started = a.started_at
    bot_events.clear()
    a = AS.assign_assembler(live, asm2, by=head)
    un = bot_events.one("assembly.unassigned")
    assert un["to"] == [1001] and un["prev"]["name"] == "Yig'uvchi A"
    assert un["assembly"]["assembler"]["name"] == "Yig'uvchi B"
    assert bot_events.one("assembly.task")["to"] == [1002]
    assert bot_events.of("assembly.due_ask") == []
    assert a.started_at == started and a.rev == 2


def test_clear_assembler_only_unassigned(live, asm, head, bot_events):
    AS.assign_assembler(live, asm, by=head)
    bot_events.clear()
    a = AS.assign_assembler(live, None, by=head)
    assert bot_events.names() == ["assembly.unassigned"]
    assert a.user_id is None and a.started_at is not None


def test_user_change_on_finished_job_no_events(live, asm, asm2, head, order_ready, bot_events):
    AS.assign_assembler(live, asm, by=head)
    AS.finish_assembly(live, by=asm, note=NOTE)
    AS.confirm_assembly(live, by=head)
    bot_events.clear()
    with pytest.raises(ServiceConflict):
        AS.assign_assembler(live, asm2, by=head)
    assert fresh(live).user_id == asm.pk and bot_events == []


def test_non_assembler_refused(live, make_staff, head):
    plain = make_staff("assembly.view_assembly", name="Oddiy")
    with pytest.raises(ServiceError) as e:
        AS.assign_assembler(live, plain, by=head)
    assert e.value.field == "user"
    gone = make_staff(*ASM_PERMS, name="Ketgan")
    gone.is_active = False
    gone.save()
    with pytest.raises(ServiceError):
        AS.assign_assembler(live, gone, by=head)
    assert fresh(live).user_id is None


def test_assign_before_detailing_refused(order_factory, asm, head):
    a = Assembly.objects.create(order=_order(order_factory, OrderStatus.DETAILING), square=1)
    with pytest.raises(ServiceError):
        AS.assign_assembler(a, asm, by=head)


def test_keep_started_refuses_other_assembler(live, asm, asm2, head):
    AS.assign_assembler(live, asm, by=head)
    with pytest.raises(ServiceConflict):
        AS.assign_assembler(live, asm2, by=head, keep_started=True)
    assert fresh(live).user_id == asm.pk


# --- 6. permissions -----------------------------------------------------------------


def test_assign_action_head_only(live, asm, api, bot_events, head):
    url = f"/api/v1/assemblies/{live.pk}/assign/"
    body = {"user": asm.pk}
    assert api(*HEAD_PERMS).post(url, body, format="json").status_code == 200
    assert api(*MANAGER_PERMS).post(url, body, format="json").status_code == 403
    assert api(*ASM_PERMS).post(url, body, format="json").status_code in (403, 404)
    m = api(*MANAGER_PERMS)
    assert m.patch(f"/api/v1/assemblies/{live.pk}/", body, format="json").status_code == 403
    h = api(*HEAD_PERMS, "assembly.change_assembly")
    assert (
        h.patch(f"/api/v1/assemblies/{live.pk}/", {"user": asm.pk}, format="json").status_code
        == 200
    )
    assert h.post(url, {"user": None}, format="json").status_code == 200
    r = h.post(url, {"user": 99999}, format="json")
    assert r.status_code == 400 and r.data.get("field") == "user"


def test_assemblers_list_perms(api, asm, make_staff):
    gone = make_staff(*ASM_PERMS, name="Nofaol")
    gone.is_active = False
    gone.save()
    assert api("assembly.view_assembly").get("/api/v1/assemblies/assemblers/").status_code == 403
    for perms in (HEAD_PERMS, MANAGER_PERMS):
        r = api(*perms).get("/api/v1/assemblies/assemblers/")
        assert r.status_code == 200
        assert [u["id"] for u in r.data] == [asm.pk]


def test_service_assign_by_non_head_forbidden(live, asm, manager):
    for user in (manager, asm):
        with pytest.raises(ServiceForbidden):
            AS.assign_assembler(live, asm, by=user)
    assert fresh(live).user_id is None


# --- 7. «Yig'ildi» / «O'rnatildi» on the site ---------------------------------------


def test_installing_done_panel(live, asm, asm2, head, manager, api, bot_events, order_ready):
    AS.assign_assembler(live, asm, by=head)
    c = api(*ASM_PERMS)
    c.force_authenticate(asm)
    url = f"/api/v1/assemblies/{live.pk}/"
    data = c.get(url).data
    assert data["actions"]["done"] is True and data["actions"]["installing_done"] is False
    r = c.post(url + "installing-done/")  # no note
    assert r.status_code == 400 and r.data.get("field") == "note"
    r = c.post(url + "installing-done/", {"note": NOTE}, format="json")
    assert r.status_code == 400 and "yig'ishni" in r.data["detail"]  # before «Yig'ildi»
    r = c.post(url + "done/")
    assert r.status_code == 200 and r.data["state"] == "assembled"
    assert Order.objects.get(pk=live.order_id).status == OrderStatus.INSTALLING
    other = api(*ASM_PERMS)
    other.force_authenticate(asm2)
    assert other.post(url + "installing-done/", {"note": NOTE}, format="json").status_code in (
        403,
        404,
    )
    bot_events.clear()
    r = c.post(url + "installing-done/", {"note": NOTE}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["state"] == "checking" and r.data["note"] == NOTE
    assert r.data["finished_by_detail"]["id"] == asm.pk and r.data["finished_at"]
    assert r.data["confirmed_at"] is None and r.data["actions"]["installing_done"] is False
    # NOT «Готов» yet: the head has not confirmed
    assert Order.objects.get(pk=live.order_id).status == OrderStatus.INSTALLING
    assert order_ready == []
    ev = bot_events.one("assembly.done")
    assert ev["by_name"] == "Yig'uvchi A" and ev["heads"] == [2001]
    assert ev["to"] == [2001, 3001] and ev["assemblers"] == [1001]
    assert ev["assembly"]["state"] == "checking"
    # the assembler cannot confirm; the head can (site)
    assert c.post(url + "confirm/").status_code == 403
    h = api(*HEAD_PERMS)
    h.force_authenticate(head)
    assert h.get(url).data["actions"]["confirm"] is True
    bot_events.clear()
    r = h.post(url + "confirm/")
    assert r.status_code == 200, r.data
    assert r.data["state"] == "done" and r.data["confirmed_by_detail"]["id"] == head.pk
    assert r.data["confirmed_at"] and r.data["actions"]["confirm"] is False
    assert Order.objects.get(pk=live.order_id).status == OrderStatus.DONE
    assert order_ready == [str(live.order.order_number)]
    ev = bot_events.one("assembly.confirmed")
    assert ev["by_name"] == head.name and ev["heads"] == [2001]
    assert ev["to"] == [2001, 3001] and ev["assemblers"] == [1001]
    assert ev["assembly"]["state"] == "done"
    assert h.post(url + "confirm/").status_code == 400  # already done (site: all 400)


def test_done_by_other_user_forbidden(live, asm, asm2, head):
    AS.assign_assembler(live, asm, by=head)
    with pytest.raises(ServiceForbidden):
        AS.mark_assembly_done(live, by=asm2)
    assert fresh(live).done is False
    assert AS.mark_assembly_done(live, by=asm).done is True


def test_manager_can_finish_any_job(live, asm, head, manager, order_ready):
    AS.assign_assembler(live, asm, by=head)
    AS.mark_assembly_done(live, by=manager)
    assert AS.mark_installing_done(live, by=manager, note=NOTE).finished_by == manager


def test_done_side_effects_only_at_confirm(live, asm, head, manager, order_ready, bot_events):
    """The DONE chain (order status + accounting order_ready) fires at the head's confirm,
    not at the assembler's finish."""
    AS.assign_assembler(live, asm, by=head)
    a = AS.finish_assembly(live, by=asm, note=NOTE)
    assert a.state == "checking" and not a.installing_done and a.done
    assert Order.objects.get(pk=a.order_id).status == OrderStatus.INSTALLING
    assert order_ready == []
    with pytest.raises(ServiceForbidden):  # a manager is not a head
        AS.confirm_assembly(a, by=manager)
    with pytest.raises(ServiceForbidden):  # nor the assembler
        AS.confirm_assembly(a, by=asm)
    assert order_ready == []
    with pytest.raises(ServiceConflict):  # a second «O'rnatildi» while checking
        AS.finish_assembly(a, by=asm, note=NOTE)
    a = AS.confirm_assembly(a, by=head)
    assert a.state == "done" and a.installing_done and a.confirmed_by == head
    assert a.confirmed_at and a.rev == fresh(a).rev
    assert Order.objects.get(pk=a.order_id).status == OrderStatus.DONE
    assert order_ready == [str(a.order.order_number)]
    with pytest.raises(ServiceConflict):
        AS.confirm_assembly(a, by=head)
    assert len(order_ready) == 1


def test_confirm_before_finish_is_refused(live, asm, head, order_ready):
    AS.assign_assembler(live, asm, by=head)
    with pytest.raises(ServiceError):
        AS.confirm_assembly(live, by=head)
    assert order_ready == [] and not fresh(live).installing_done


def test_confirm_when_order_already_done_closes_row_only(
    order_factory, asm, head, order_ready, sms
):
    a = Assembly.objects.create(order=_order(order_factory, OrderStatus.DONE), square=3, user=asm)
    a = AS.finish_assembly(a, by=asm, note=NOTE)
    assert a.state == "checking"
    AS.confirm_assembly(a, by=head)
    assert fresh(a).installing_done and order_ready == []


def test_checking_stops_reminders_and_overdue(live, asm, head, fixed_clock, bot_events):
    AS.assign_assembler(live, asm, by=head)
    AS.set_assembly_due(live, by=head, days=1)
    AS.finish_assembly(live, by=asm, note=NOTE)
    bot_events.clear()
    assert AS.due_assembly_reminders(at(TODAY + timedelta(days=3), 12)) == {
        "auto": 0,
        "soon": 0,
        "overdue": 0,
    }
    assert bot_events.of("assembly.remind") == []
    assert fresh(live).overdue is False


# --- 8. finish_assembly (bot one-shot) ----------------------------------------------


@pytest.mark.parametrize("status", [OrderStatus.ASSEMBLY, OrderStatus.INSTALLING])
def test_finish_from_assembly_or_installing(order_factory, asm, status, order_ready, sms):
    a = Assembly.objects.create(order=_order(order_factory, status), square=3, user=asm)
    a = AS.finish_assembly(a, by=asm, note=NOTE)
    assert a.done and not a.installing_done and a.note == NOTE and a.finished_by == asm
    assert a.state == "checking" and a.rev == 1
    assert Order.objects.get(pk=a.order_id).status == OrderStatus.INSTALLING
    assert order_ready == []


def test_finish_rules(order_factory, asm, asm2, order_ready, sms):
    a = Assembly.objects.create(order=_order(order_factory), square=3, user=asm)
    with pytest.raises(ServiceError) as e:  # order still WORKING
        AS.finish_assembly(a, by=asm, note=NOTE)
    assert e.value.field is None
    Order.objects.filter(pk=a.order_id).update(status=OrderStatus.ASSEMBLY)
    with pytest.raises(ServiceForbidden):
        AS.finish_assembly(a, by=asm2, note=NOTE)
    for bad in ("", "  ab ", "x" * 2001, None, 5):
        with pytest.raises(ServiceError) as e:
            AS.finish_assembly(a, by=asm, note=bad)
        assert e.value.field == "note"
    AS.finish_assembly(a, by=asm, note="  " + NOTE + " ")
    assert fresh(a).note == NOTE
    with pytest.raises(ServiceConflict):
        AS.finish_assembly(a, by=asm, note=NOTE)


def test_finish_when_order_already_done_does_not_resave_order(order_factory, asm, order_ready, sms):
    a = Assembly.objects.create(order=_order(order_factory, OrderStatus.DONE), square=3, user=asm)
    AS.finish_assembly(a, by=asm, note=NOTE)
    assert fresh(a).state == "checking" and order_ready == []


def test_finish_is_atomic(order_factory, asm, monkeypatch, order_ready, sms):
    a = Assembly.objects.create(
        order=_order(order_factory, OrderStatus.ASSEMBLY), square=3, user=asm
    )

    def boom(self, *args, **kwargs):
        raise RuntimeError("order save failed")

    monkeypatch.setattr(Order, "save", boom)
    with pytest.raises(RuntimeError):
        AS.finish_assembly(a, by=asm, note=NOTE)
    monkeypatch.undo()
    b = fresh(a)
    assert not b.installing_done and not b.done and b.note == "" and b.rev == 0


# --- 10. panel due ------------------------------------------------------------------


def test_set_due_set_then_moved(live, asm, head, bot_events, fixed_clock):
    AS.assign_assembler(live, asm, by=head)
    bot_events.clear()
    a = AS.set_assembly_due(live, by=head, days=5)
    assert a.due_date == TODAY + timedelta(days=5) and not a.due_auto and a.due_set_by == head
    ev = bot_events.one("assembly.due_set")
    assert ev["how"] == "set" and ev["by_name"] == "Rahbar"
    assert ev["to"] == [1001] and ev["heads"] == [2001]
    AS.set_assembly_due(live, by=head, days=10)
    assert bot_events.of("assembly.due_set")[-1]["how"] == "moved"
    rev = fresh(live).rev
    AS.set_assembly_due(live, by=head, days=10)  # same date: no-op
    assert fresh(live).rev == rev and len(bot_events.of("assembly.due_set")) == 2


def test_set_due_rules(live, asm, head, fixed_clock, order_ready):
    AS.assign_assembler(live, asm, by=head)
    with pytest.raises(ServiceForbidden):
        AS.set_assembly_due(live, by=asm, days=5)
    for bad in (0, 31, "5", True):
        with pytest.raises(ServiceError) as e:
            AS.set_assembly_due(live, by=head, days=bad)
        assert e.value.field == "due"
    with pytest.raises(ServiceError):
        AS.set_assembly_due(live, by=head, due_date=TODAY - timedelta(days=1))
    with pytest.raises(ServiceError):
        AS.set_assembly_due(live, by=head, due_date=TODAY + timedelta(days=400))
    AS.finish_assembly(live, by=asm, note=NOTE)
    with pytest.raises(ServiceConflict):
        AS.set_assembly_due(live, by=head, days=5)


def test_panel_due_endpoint(live, asm, api, head):
    AS.assign_assembler(live, asm, by=head)
    url = f"/api/v1/assemblies/{live.pk}/due/"
    assert api(*MANAGER_PERMS).post(url, {"due_date": "2999-01-01"}).status_code == 403
    h = api(*HEAD_PERMS)
    from accounting.text import today

    r = h.post(url, {"due_date": (today() - timedelta(days=1)).isoformat()}, format="json")
    assert r.status_code == 400 and r.data.get("field") == "due"
    ok = (today() + timedelta(days=2)).isoformat()
    r = h.post(url, {"due_date": ok}, format="json")
    assert r.status_code == 200 and r.data["due_date"] == ok and r.data["actions"]["due"] is True


# --- 11. auto deadline --------------------------------------------------------------


def started_ago(a, **delta):
    Assembly.objects.filter(pk=a.pk).update(started_at=NOW - timedelta(**delta))


def test_auto_due_window(order_factory, asm, head, bot_events, fixed_clock, sms):
    rows = [
        Assembly.objects.create(order=_order(order_factory, OrderStatus.ASSEMBLY), square=1)
        for _ in range(4)
    ]
    for a in rows[:3]:
        AS.assign_assembler(a, asm, by=head)
    started_ago(rows[0], hours=25)  # due for auto
    started_ago(rows[1], hours=23)  # too fresh
    started_ago(rows[2], days=4)  # too old
    bot_events.clear()  # rows[3] never started: started_at NULL
    assert AS.auto_set_assembly_dues(NOW) == 1
    r = fresh(rows[0])
    assert r.due_auto and r.due_set_by is None and r.due_set_at == NOW
    assert r.due_date == r.started_at.date() + timedelta(days=10)
    assert all(fresh(a).due_date is None for a in rows[1:])
    ev = bot_events.one("assembly.due_set")
    assert ev["how"] == "auto" and ev["by_name"] is None
    assert AS.auto_set_assembly_dues(NOW) == 0


def test_auto_due_skips_finished_and_dated(order_factory, asm, head, fixed_clock, order_ready, sms):
    dated = Assembly.objects.create(order=_order(order_factory, OrderStatus.ASSEMBLY), square=1)
    done = Assembly.objects.create(order=_order(order_factory, OrderStatus.ASSEMBLY), square=1)
    AS.assign_assembler(dated, asm, by=head)
    AS.assign_assembler(done, asm, by=head)
    AS.set_assembly_due(dated, by=head, days=3)
    AS.finish_assembly(done, by=asm, note=NOTE)
    for a in (dated, done):
        started_ago(a, hours=25)
    before = fresh(dated).due_date
    assert AS.auto_set_assembly_dues(NOW) == 0
    assert fresh(dated).due_date == before and fresh(done).due_date is None


def test_auto_due_days_setting(live, asm, head, fixed_clock):
    from constance.test import override_config

    AS.assign_assembler(live, asm, by=head)
    started_ago(live, hours=30)
    with override_config(ASSEMBLY_AUTO_DUE_DAYS=2):
        AS.auto_set_assembly_dues(NOW)
    a = fresh(live)
    assert a.due_date == a.started_at.date() + timedelta(days=2)


# --- 12. reminders ------------------------------------------------------------------


def test_reminders_before_hour_only_auto(live, asm, head, fixed_clock, bot_events):
    AS.assign_assembler(live, asm, by=head)
    early = at(TODAY, 8)
    Assembly.objects.filter(pk=live.pk).update(started_at=early - timedelta(hours=25))
    assert AS.due_assembly_reminders(early) == {"auto": 1, "soon": 0, "overdue": 0}
    assert bot_events.of("assembly.remind") == []


def test_soon_once_assembler_only(live, asm, head, fixed_clock, bot_events):
    AS.assign_assembler(live, asm, by=head)
    AS.set_assembly_due(live, by=head, days=1)
    bot_events.clear()
    assert AS.due_assembly_reminders(at(TODAY, 10))["soon"] == 1
    ev = bot_events.one("assembly.remind")
    assert ev["what"] == "soon" and ev["to"] == [1001] and ev["heads"] == []
    assert AS.due_assembly_reminders(at(TODAY, 11))["soon"] == 0


def test_soon_key_not_burned_without_telegram(live, make_staff, head, fixed_clock, bot_events):
    no_tg = make_staff(*ASM_PERMS, name="NoTg")
    AS.assign_assembler(live, no_tg, by=head)
    AS.set_assembly_due(live, by=head, days=1)
    bot_events.clear()
    assert AS.due_assembly_reminders(at(TODAY, 10))["soon"] == 0
    no_tg.telegram_id = 5555
    no_tg.save()
    assert AS.due_assembly_reminders(at(TODAY, 11))["soon"] == 1


def test_overdue_daily_assembler_and_heads(live, asm, head, fixed_clock, bot_events):
    AS.assign_assembler(live, asm, by=head)
    Assembly.objects.filter(pk=live.pk).update(due_date=TODAY - timedelta(days=2))
    assert AS.due_assembly_reminders(at(TODAY, 10))["overdue"] == 1
    ev = bot_events.of("assembly.remind")[-1]
    assert ev["what"] == "overdue" and ev["days_late"] == 2
    assert ev["to"] == [1001] and ev["heads"] == [2001]
    assert AS.due_assembly_reminders(at(TODAY, 15))["overdue"] == 0
    assert AS.due_assembly_reminders(at(TODAY + timedelta(days=1), 10))["overdue"] == 1
    assert bot_events.of("assembly.remind")[-1]["days_late"] == 3


def test_reminders_skip_finished_done_orders_keep_assembled(
    order_factory, asm, head, fixed_clock, bot_events, order_ready, sms
):
    old = TODAY - timedelta(days=2)
    finished = Assembly.objects.create(order=_order(order_factory, OrderStatus.ASSEMBLY), square=1)
    AS.assign_assembler(finished, asm, by=head)
    AS.finish_assembly(finished, by=asm, note=NOTE)
    pushed = Assembly.objects.create(
        order=_order(order_factory, OrderStatus.DONE), square=1, user=asm
    )
    assembled = Assembly.objects.create(
        order=_order(order_factory, OrderStatus.INSTALLING), square=1, user=asm, done=True
    )
    Assembly.objects.filter(pk__in=[finished.pk, pushed.pk, assembled.pk]).update(due_date=old)
    bot_events.clear()
    out = AS.due_assembly_reminders(at(TODAY, 10))
    assert out["overdue"] == 1
    assert bot_events.of("assembly.remind")[0]["assembly"]["id"] == assembled.pk


def test_property_overdue(live):
    from accounting.text import today

    assert live.overdue is False and live.days_late == 0
    live.due_date = today() - timedelta(days=3)
    assert live.overdue and live.days_late == 3
    live.installing_done = True
    assert not live.overdue and live.days_late == 0


# --- 13. site list ------------------------------------------------------------------


def test_list_scoping_and_filters(order_factory, asm, asm2, head, api, sms):
    a = Assembly.objects.create(order=_order(order_factory, OrderStatus.ASSEMBLY), square=1)
    b = Assembly.objects.create(order=_order(order_factory, OrderStatus.ASSEMBLY), square=1)
    AS.assign_assembler(a, asm, by=head)
    AS.assign_assembler(b, asm2, by=head)
    for perms in (HEAD_PERMS, MANAGER_PERMS):
        assert api(*perms).get("/api/v1/assemblies/").data["count"] == 2
    c = api(*ASM_PERMS)
    c.force_authenticate(asm)
    assert [x["id"] for x in c.get("/api/v1/assemblies/").data["results"]] == [a.pk]
    h = api(*HEAD_PERMS)
    Assembly.objects.filter(pk=a.pk).update(due_date=date(2020, 1, 1))
    got = h.get("/api/v1/assemblies/", {"overdue": "1"}).data["results"]
    assert [x["id"] for x in got] == [a.pk] and got[0]["overdue"] is True
    assert h.get("/api/v1/assemblies/", {"ordering": "due_date"}).status_code == 200
    assert [x["id"] for x in h.get("/api/v1/assemblies/", {"user": asm2.pk}).data["results"]] == [
        b.pk
    ]


def test_actions_are_bools(live, asm, head, api):
    AS.assign_assembler(live, asm, by=head)
    for perms in (HEAD_PERMS, MANAGER_PERMS, ASM_PERMS):
        c = api(*perms)
        if perms is ASM_PERMS:
            c.force_authenticate(asm)
        a = c.get(f"/api/v1/assemblies/{live.pk}/").data["actions"]
        assert set(a) == {"edit", "done", "installing_done", "confirm", "due"}
        assert all(type(v) is bool for v in a.values()), (perms, a)


# --- 14. migration 0013 + schedule --------------------------------------------------


def _perms(g):
    return {
        f"{p.content_type.app_label}.{p.codename}"
        for p in g.permissions.select_related("content_type")
    }


def test_migration_0013_additive_idempotent_noop():
    mod = importlib.import_module("order.assembly.migrations.0013_production_head_view_assembly")
    Group.objects.filter(name="Ishlab chiqarish rahbari").delete()
    mod.add_view_assembly(global_apps, None)  # no group: nothing is created
    assert not Group.objects.filter(name="Ishlab chiqarish rahbari").exists()
    g = Group.objects.create(name="ishlab  Chiqarish rahbari")
    other = Group.objects.create(name="Boshqa")
    mod.add_view_assembly(global_apps, None)
    mod.add_view_assembly(global_apps, None)
    assert _perms(g) == {"assembly.view_assembly"} and other.permissions.count() == 0


def test_schedule_has_assembly_task():
    from django_celery_beat.models import PeriodicTask

    from accounting.schedule import sync_periodic_tasks

    sync_periodic_tasks()
    pt = PeriodicTask.objects.get(name="yig'ish: muddat va eslatmalar")
    assert pt.task == "order.assembly.tasks.assembly_reminders" and pt.enabled


def test_reminders_task_runs(live):
    assert set(tasks.assembly_reminders()) == {"auto", "soon", "overdue"}
