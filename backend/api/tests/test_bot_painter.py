"""Painter (molyar) bot API: «Bajardim» with an izoh and the deadline buttons, plus the
contract fixtures (docs/bot_contract/*painter*)."""

import pytest
from djmoney.money import Money

from api.tests.botkit import load_fixture
from order.painter import services as PS
from order.painter.dto import painter_task
from order.painter.models import Painter, PainterType

pytestmark = pytest.mark.django_db

NOTE = "Fasad bo'yaldi, 8 ta eshik"


@pytest.fixture
def mol(make_staff):
    return make_staff("painter.view_painter", name="Molyar ustasi", telegram_id=1001)


@pytest.fixture
def head(make_staff):
    return make_staff(
        "oauth.user_production_head", "painter.view_painter", name="Rahbar", telegram_id=2001
    )


@pytest.fixture
def manager(make_staff):
    return make_staff("assembly.manager", "painter.view_painter", name="Menejer", telegram_id=3001)


@pytest.fixture
def painter(order_factory, mol):
    t = PainterType.objects.create(name="Glyanets", price=Money(10, "UZS"), user=mol)
    p = Painter.objects.create(order=order_factory(), square=5)
    return PS.assign_painter_type(p, t)


def test_bot_done(painter, mol, head, manager, make_staff, bot_client, bot_events):
    path = f"painters/{painter.pk}/done/"
    other = make_staff("painter.view_painter", telegram_id=1009)
    assert (
        bot_client.post("painters/999999/done/", actor=1001, data={"note": NOTE}).status_code == 404
    )
    assert bot_client.post(path, actor=777, data={"note": NOTE}).status_code == 403  # not linked
    assert bot_client.post(path, actor=other.telegram_id, data={"note": NOTE}).status_code == 403
    for bad in ("ab", "", "x" * 2001, None, 5):
        r = bot_client.post(path, actor=1001, data={"note": bad})
        assert r.status_code == 400 and r.json()["field"] == "note", bad
    bot_events.clear()
    ok = bot_client.post(path, actor=1001, data={"note": NOTE})
    assert ok.status_code == 200
    got = ok.json()["painter"]
    assert got["state"] == "done" and got["note"] == NOTE and got["done_by"]["id"] == mol.pk
    assert len(bot_events.of("painter.done")) == 1
    assert bot_client.post(path, actor=1001, data={"note": NOTE}).status_code == 409


def test_bot_done_rover_unfinished_400(order_factory, mol, bot_client):
    from order.rover.models import Rover

    order = order_factory()
    Rover.objects.create(order=order, square=3)
    p = Painter.objects.create(order=order, square=5)
    t = PainterType.objects.create(name="T", price=Money(1, "UZS"), user=mol)
    Painter.objects.filter(pk=p.pk).update(type=t)
    r = bot_client.post(f"painters/{p.pk}/done/", actor=1001, data={"note": NOTE})
    assert r.status_code == 400


def test_bot_due(painter, mol, head, bot_client, bot_events):
    path = f"painters/{painter.pk}/due/"
    assert bot_client.post("painters/999999/due/", actor=2001, data={"days": 5}).status_code == 404
    assert bot_client.post(path, actor=1001, data={"days": 5}).status_code == 403
    for bad in (0, 31, "5", True, None):
        r = bot_client.post(path, actor=2001, data={"days": bad})
        assert r.status_code == 400 and r.json()["field"] == "due", bad
    bot_events.clear()
    ok = bot_client.post(path, actor=2001, data={"days": 10})
    assert ok.status_code == 200
    got = ok.json()["painter"]
    assert got["due_date"] and got["due_set_by"]["name"] == "Rahbar" and got["rev"] == 2
    assert len(bot_events.of("painter.due_set")) == 1
    # the same date again: no second event
    assert bot_client.post(path, actor=2001, data={"days": 10}).status_code == 200
    assert len(bot_events.of("painter.due_set")) == 1


def test_bot_due_done_conflict(painter, mol, head, bot_client):
    PS.mark_painter_done(painter, by=mol, note=NOTE)
    assert (
        bot_client.post(f"painters/{painter.pk}/due/", actor=2001, data={"days": 5}).status_code
        == 409
    )


# --- 13. contract fixtures ----------------------------------------------------------


def test_painter_fixtures_match_real_payloads(bot_events, head, manager, painter, mol, bot_client):
    p = painter_task(Painter.objects.get(pk=painter.pk))
    fx = load_fixture("dto.painter_task.1.json")
    assert set(p) == set(fx)
    assert set(p["type"]) == set(fx["type"]) and set(p["painter"]) == set(fx["painter"])
    for name in ("painter.task", "painter.due_ask"):
        real = bot_events.one(name)
        fixture = load_fixture(f"event.{name}.json")["data"]
        assert set(real) == set(fixture), name
        assert set(real["painter"]) == set(fx)
    PS.set_painter_due(painter, by=head, days=5)
    assert set(bot_events.one("painter.due_set")) == set(
        load_fixture("event.painter.due_set.json")["data"]
    )
    PS.mark_painter_done(painter, by=mol, note=NOTE)
    assert set(bot_events.one("painter.done")) == set(
        load_fixture("event.painter.done.json")["data"]
    )
    assert set(load_fixture("misc.painter_done_request.json")) == {"note"}
    assert load_fixture("misc.painter_due_request.json") == {"days": 10}
    for name in ("misc.painter_done_response.json", "misc.painter_due_response.json"):
        assert set(load_fixture(name)) == {"painter"}
        assert set(load_fixture(name)["painter"]) == set(fx)


def test_painter_other_events_match_fixtures(
    bot_events, order_factory, painter, mol, head, manager, make_staff, monkeypatch
):
    from datetime import timedelta

    from accounting.text import now

    mol2 = make_staff("painter.view_painter", name="Molyar 2", telegram_id=1002)
    t2 = PainterType.objects.create(name="Mat", price=Money(2, "UZS"), user=mol2)
    PS.assign_painter_type(painter, t2)
    assert set(bot_events.one("painter.unassigned")) == set(
        load_fixture("event.painter.unassigned.json")["data"]
    )
    Painter.objects.filter(pk=painter.pk).update(due_date=now().date() - timedelta(days=2))
    monkeypatch.setattr("order.painter.services.now", now)
    PS.due_painter_reminders(now().replace(hour=23))
    assert set(bot_events.of("painter.remind")[-1]) == set(
        load_fixture("event.painter.remind.json")["data"]
    )
    from order.rover.models import Rover
    from order.rover.tasks import notify_painting_ready_task

    order = order_factory()
    rover = Rover.objects.create(order=order, square=2, done=True)
    Painter.objects.create(order=order, square=2)
    notify_painting_ready_task(rover.pk)
    ready = bot_events.one("painter.ready")
    fx_ready = load_fixture("event.painter.ready.json")["data"]
    assert set(ready) == set(fx_ready)
    assert ready["to"] == [2001]  # the production head
    assert set(ready["types"][0]) == set(fx_ready["types"][0])
    assert set(ready["types"][0]["user"]) == set(fx_ready["types"][0]["user"])


@pytest.fixture
def team(make_staff):
    u = make_staff("painter.view_painter", name="Autsors ustasi", telegram_id=1005)
    return PainterType.objects.create(name="Autsors", price=Money(5, "UZS"), user=u)


@pytest.fixture
def fresh_painter(order_factory):
    return Painter.objects.create(order=order_factory(), square=4)


def test_bot_type_head_picks_team(fresh_painter, team, head, bot_client, bot_events):
    r = bot_client.post(
        f"painters/{fresh_painter.pk}/type/",
        actor=2001,
        data=load_fixture("misc.painter_type_request.json") | {"type_id": team.pk},
    )
    assert r.status_code == 200, r.content
    got = r.json()["painter"]
    assert got["type"] == {"id": team.pk, "name": "Autsors"} and got["started_at"]
    assert set(got) == set(load_fixture("misc.painter_type_response.json")["painter"])
    assert bot_events.one("painter.task")["to"] == [1005]
    assert len(bot_events.of("painter.due_ask")) == 1


def test_bot_type_permissions_and_errors(
    fresh_painter, team, head, manager, mol, bot_client, make_staff
):
    path = f"painters/{fresh_painter.pk}/type/"
    body = {"type_id": team.pk}
    assert bot_client.post(path, actor=777, data=body).status_code == 403  # not linked
    assert bot_client.post(path, actor=3001, data=body).status_code == 403  # manager
    assert bot_client.post(path, actor=1001, data=body).status_code == 403  # painter
    assert bot_client.post("painters/999999/type/", actor=2001, data=body).status_code == 404
    for bad in ({"type_id": 99999}, {}, {"type_id": "x"}, {"type_id": True}):
        assert bot_client.post(path, actor=2001, data=bad).status_code == 404, bad
    no_user = PainterType.objects.create(name="Bo'sh", price=Money(1, "UZS"), user=None)
    assert bot_client.post(path, actor=2001, data={"type_id": no_user.pk}).status_code == 400
    assert fresh_painter.__class__.objects.get(pk=fresh_painter.pk).type_id is None


def test_bot_type_rover_unfinished_400_and_done_409(order_factory, team, head, painter, bot_client):
    from order.rover.models import Rover

    order = order_factory()
    Rover.objects.create(order=order, square=3)
    p = Painter.objects.create(order=order, square=5)
    r = bot_client.post(f"painters/{p.pk}/type/", actor=2001, data={"type_id": team.pk})
    assert r.status_code == 400
    PS.mark_painter_done(painter, by=painter.type.user, note=NOTE)
    r = bot_client.post(f"painters/{painter.pk}/type/", actor=2001, data={"type_id": team.pk})
    assert r.status_code == 409


def test_bot_type_other_team_after_start_409_same_team_200(
    painter, team, head, bot_client, bot_events
):
    cur = painter.type
    r = bot_client.post(f"painters/{painter.pk}/type/", actor=2001, data={"type_id": team.pk})
    assert r.status_code == 409
    assert "Glyanets" in r.json()["detail"] and "saytda" in r.json()["detail"]
    assert Painter.objects.get(pk=painter.pk).type_id == cur.pk
    n = len(bot_events.of("painter.task"))
    r = bot_client.post(f"painters/{painter.pk}/type/", actor=2001, data={"type_id": cur.pk})
    assert r.status_code == 200
    assert len(bot_events.of("painter.task")) == n
    assert Painter.objects.get(pk=painter.pk).rev == painter.rev


def test_service_keep_started_refuses_other_team_under_lock(painter, team, head):
    # the bot view's quick check runs before the lock; the service re-checks under it
    from core.exceptions import ServiceConflict
    from order.painter.services import assign_painter_type

    cur = painter.type_id
    with pytest.raises(ServiceConflict):
        assign_painter_type(painter, team, by=head, keep_started=True)
    assert Painter.objects.get(pk=painter.pk).type_id == cur
