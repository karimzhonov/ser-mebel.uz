"""Assembly bot API: the assembler's «O'rnatildi», the heads' deadline and assembler buttons,
plus the contract fixtures (docs/bot_contract/*assembly*)."""

from datetime import timedelta

import pytest

from api.tests.botkit import load_fixture
from order.assembly import services as AS
from order.assembly.dto import assembly_task
from order.assembly.models import Assembly
from order.constants import OrderStatus
from order.models import Order

pytestmark = pytest.mark.django_db

NOTE = "Oshxona yig'ildi va o'rnatildi, 4 eshik"


@pytest.fixture(autouse=True)
def _quiet(monkeypatch, bot_events):
    monkeypatch.setattr("oauth.services.send_bulk_sms", lambda b: None)
    monkeypatch.setattr("core.sms.send_bulk_sms", lambda b: None)
    monkeypatch.setattr("order.assembly.tasks.assembly_task_sms.delay", lambda *a: None)
    monkeypatch.setattr("accounting.tasks.order_ready.delay", lambda ref: None)


@pytest.fixture
def asm(make_staff):
    return make_staff(
        "oauth.user_assembly", "assembly.view_assembly", name="Yig'uvchi ustasi", telegram_id=1001
    )


@pytest.fixture
def asm2(make_staff):
    return make_staff(
        "oauth.user_assembly", "assembly.view_assembly", name="Boshqa yig'uvchi", telegram_id=1002
    )


@pytest.fixture
def head(make_staff):
    return make_staff(
        "oauth.user_production_head", "assembly.view_assembly", name="Rahbar", telegram_id=2001
    )


@pytest.fixture
def manager(make_staff):
    return make_staff(
        "assembly.manager",
        "assembly.view_assembly",
        "assembly.change_assembly",
        name="Menejer",
        telegram_id=3001,
    )


def _row(order_factory, status=OrderStatus.ASSEMBLY, **kw):
    order = order_factory()
    Order.objects.filter(pk=order.pk).update(status=status)
    return Assembly.objects.create(order=Order.objects.get(pk=order.pk), square=5, **kw)


@pytest.fixture
def job(order_factory, asm, head):
    return AS.assign_assembler(_row(order_factory), asm, by=head)


@pytest.fixture
def blank(order_factory):
    return _row(order_factory)


# --- finish -------------------------------------------------------------------------


def test_bot_finish(job, asm, head, manager, make_staff, bot_client, bot_events):
    path = f"assemblies/{job.pk}/finish/"
    other = make_staff("oauth.user_assembly", "assembly.view_assembly", telegram_id=1009)
    assert (
        bot_client.post("assemblies/999999/finish/", actor=1001, data={"note": NOTE}).status_code
        == 404
    )
    assert bot_client.post(path, actor=777, data={"note": NOTE}).status_code == 403  # not linked
    assert bot_client.post(path, actor=other.telegram_id, data={"note": NOTE}).status_code == 403
    for bad in ("ab", "", "x" * 2001, None, 5):
        r = bot_client.post(path, actor=1001, data={"note": bad})
        assert r.status_code == 400 and r.json()["field"] == "note", bad
    assert bot_client.post(path, actor=1001, data=[1]).status_code == 400
    bot_events.clear()
    ok = bot_client.post(path, actor=1001, data=load_fixture("misc.assembly_finish_request.json"))
    assert ok.status_code == 200, ok.content
    got = ok.json()["assembly"]
    assert got["state"] == "done" and got["note"] == NOTE and got["finished_by"]["id"] == asm.pk
    assert Order.objects.get(pk=job.order_id).status == OrderStatus.DONE
    assert len(bot_events.of("assembly.done")) == 1
    assert bot_client.post(path, actor=1001, data={"note": NOTE}).status_code == 409


def test_bot_finish_manager_ok_and_order_not_in_assembly(order_factory, asm, manager, bot_client):
    early = _row(order_factory, OrderStatus.WORKING, user=asm)
    path = f"assemblies/{early.pk}/finish/"
    assert bot_client.post(path, actor=1001, data={"note": NOTE}).status_code == 400
    Order.objects.filter(pk=early.order_id).update(status=OrderStatus.INSTALLING)
    assert bot_client.post(path, actor=3001, data={"note": NOTE}).status_code == 200


# --- due ----------------------------------------------------------------------------


def test_bot_due(job, asm, head, bot_client, bot_events):
    path = f"assemblies/{job.pk}/due/"
    assert (
        bot_client.post("assemblies/999999/due/", actor=2001, data={"days": 5}).status_code == 404
    )
    assert bot_client.post(path, actor=1001, data={"days": 5}).status_code == 403
    assert bot_client.post(path, actor=777, data={"days": 5}).status_code == 403
    for bad in (0, 31, "5", True, None):
        r = bot_client.post(path, actor=2001, data={"days": bad})
        assert r.status_code == 400 and r.json()["field"] == "due", bad
    assert bot_client.post(path, actor=2001, data={}).status_code == 400
    bot_events.clear()
    ok = bot_client.post(path, actor=2001, data=load_fixture("misc.assembly_due_request.json"))
    assert ok.status_code == 200
    got = ok.json()["assembly"]
    assert got["due_date"] and got["due_set_by"]["name"] == "Rahbar" and got["rev"] == 2
    assert len(bot_events.of("assembly.due_set")) == 1
    assert bot_client.post(path, actor=2001, data={"days": 10}).status_code == 200
    assert len(bot_events.of("assembly.due_set")) == 1  # same date: no second event


def test_bot_due_finished_conflict(job, asm, head, bot_client):
    AS.finish_assembly(job, by=asm, note=NOTE)
    r = bot_client.post(f"assemblies/{job.pk}/due/", actor=2001, data={"days": 5})
    assert r.status_code == 409


# --- assembler ----------------------------------------------------------------------


def test_bot_assembler_head_picks(blank, asm, head, bot_client, bot_events):
    r = bot_client.post(
        f"assemblies/{blank.pk}/assembler/",
        actor=2001,
        data=load_fixture("misc.assembly_assembler_request.json") | {"user_id": asm.pk},
    )
    assert r.status_code == 200, r.content
    got = r.json()["assembly"]
    assert got["assembler"] == {"id": asm.pk, "name": "Yig'uvchi ustasi"} and got["started_at"]
    assert set(got) == set(load_fixture("misc.assembly_assembler_response.json")["assembly"])
    assert bot_events.one("assembly.task")["to"] == [1001]
    assert len(bot_events.of("assembly.due_ask")) == 1


def test_bot_assembler_permissions_and_errors(
    blank, asm, head, manager, bot_client, make_staff, order_factory
):
    path = f"assemblies/{blank.pk}/assembler/"
    body = {"user_id": asm.pk}
    assert bot_client.post(path, actor=777, data=body).status_code == 403  # not linked
    assert bot_client.post(path, actor=3001, data=body).status_code == 403  # manager
    assert bot_client.post(path, actor=1001, data=body).status_code == 403  # assembler
    assert bot_client.post("assemblies/999999/assembler/", actor=2001, data=body).status_code == 404
    plain = make_staff("assembly.view_assembly", telegram_id=1010)
    gone = make_staff("oauth.user_assembly", telegram_id=1011)
    gone.is_active = False
    gone.save()
    for bad in (
        {"user_id": 99999},
        {},
        {"user_id": "x"},
        {"user_id": True},
        {"user_id": plain.pk},
        {"user_id": gone.pk},
    ):
        assert bot_client.post(path, actor=2001, data=bad).status_code == 404, bad
    assert Assembly.objects.get(pk=blank.pk).user_id is None
    early = _row(order_factory, OrderStatus.DETAILING)
    r = bot_client.post(f"assemblies/{early.pk}/assembler/", actor=2001, data=body)
    assert r.status_code == 400


def test_bot_assembler_finished_409(job, asm, asm2, head, bot_client):
    AS.finish_assembly(job, by=asm, note=NOTE)
    r = bot_client.post(f"assemblies/{job.pk}/assembler/", actor=2001, data={"user_id": asm2.pk})
    assert r.status_code == 409


def test_bot_assembler_other_after_start_409_same_200(job, asm, asm2, head, bot_client, bot_events):
    r = bot_client.post(f"assemblies/{job.pk}/assembler/", actor=2001, data={"user_id": asm2.pk})
    assert r.status_code == 409
    assert "Yig'uvchi ustasi" in r.json()["detail"] and "saytda" in r.json()["detail"]
    assert Assembly.objects.get(pk=job.pk).user_id == asm.pk
    n = len(bot_events.of("assembly.task"))
    r = bot_client.post(f"assemblies/{job.pk}/assembler/", actor=2001, data={"user_id": asm.pk})
    assert r.status_code == 200
    assert len(bot_events.of("assembly.task")) == n
    assert Assembly.objects.get(pk=job.pk).rev == job.rev


def test_service_keep_started_under_lock(job, asm2, head):
    from core.exceptions import ServiceConflict

    with pytest.raises(ServiceConflict):
        AS.assign_assembler(job, asm2, by=head, keep_started=True)


def test_bot_assembler_same_user_activates_legacy_row(
    order_factory, asm, head, bot_client, bot_events
):
    legacy = _row(order_factory, user=asm)
    r = bot_client.post(f"assemblies/{legacy.pk}/assembler/", actor=2001, data={"user_id": asm.pk})
    assert r.status_code == 200 and r.json()["assembly"]["started_at"]
    assert len(bot_events.of("assembly.task")) == 1


# --- contract fixtures --------------------------------------------------------------


def test_assembly_fixtures_match_real_payloads(
    order_factory, bot_events, head, manager, asm, asm2, monkeypatch
):
    a = _row(order_factory)
    Order.objects.filter(pk=a.order_id).update(status=OrderStatus.WORKING)
    from order.services import send_order_to_assembly

    send_order_to_assembly(Order.objects.get(pk=a.order_id))
    fx = load_fixture("dto.assembly_task.1.json")
    dto = assembly_task(Assembly.objects.select_related("order__client").get(pk=a.pk))
    assert set(dto) == set(fx)
    ready = bot_events.one("assembly.ready")
    fx_ready = load_fixture("event.assembly.ready.json")["data"]
    assert set(ready) == set(fx_ready) and ready["to"] == [2001]
    assert set(ready["assemblers"][0]) == set(fx_ready["assemblers"][0])
    assert set(ready["assembly"]) == set(fx)
    AS.assign_assembler(a, asm, by=head)
    for name in ("assembly.task", "assembly.due_ask"):
        real = bot_events.one(name)
        assert set(real) == set(load_fixture(f"event.{name}.json")["data"]), name
        assert set(real["assembly"]) == set(fx)
    AS.set_assembly_due(a, by=head, days=5)
    assert set(bot_events.one("assembly.due_set")) == set(
        load_fixture("event.assembly.due_set.json")["data"]
    )
    AS.assign_assembler(a, asm2, by=head)
    assert set(bot_events.one("assembly.unassigned")) == set(
        load_fixture("event.assembly.unassigned.json")["data"]
    )
    from accounting.text import now

    Assembly.objects.filter(pk=a.pk).update(due_date=now().date() - timedelta(days=2))
    AS.due_assembly_reminders(now().replace(hour=23))
    assert set(bot_events.of("assembly.remind")[-1]) == set(
        load_fixture("event.assembly.remind.json")["data"]
    )
    AS.finish_assembly(a, by=asm2, note=NOTE)
    assert set(bot_events.one("assembly.done")) == set(
        load_fixture("event.assembly.done.json")["data"]
    )
    assert set(load_fixture("misc.assembly_finish_request.json")) == {"note"}
    assert load_fixture("misc.assembly_due_request.json") == {"days": 10}
    assert set(load_fixture("misc.assembly_assembler_request.json")) == {"user_id"}
    for name in (
        "misc.assembly_finish_response.json",
        "misc.assembly_due_response.json",
        "misc.assembly_assembler_response.json",
    ):
        assert set(load_fixture(name)) == {"assembly"}
        assert set(load_fixture(name)["assembly"]) == set(fx)
