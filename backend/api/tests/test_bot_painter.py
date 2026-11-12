"""Painter (molyar) bot API: «Bajardim» with an izoh and the deadline buttons, plus the
contract fixtures (docs/bot_contract/*painter*)."""

import pytest
from djmoney.money import Money

from api.tests.botkit import load_fixture
from order.painter import services as PS
from order.painter.dto import painter_task
from order.painter.models import Painter, PainterPart, PainterType

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
    return PS.assign_whole_job(p, t)


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
    PainterPart.objects.create(painter=p, type=t, square=5)
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
    assert got["due_date"] and got["due_set_by"]["name"] == "Rahbar"
    assert got["parts"][0]["rev"] == 2 and got["parts"][0]["due_date"] == got["due_date"]
    assert len(bot_events.of("painter.part_due_set")) == 1
    # the same date again: no second event
    assert bot_client.post(path, actor=2001, data={"days": 10}).status_code == 200
    assert len(bot_events.of("painter.part_due_set")) == 1


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
    assert set(p["parts"][0]) == set(fx["parts"][0])
    part_fx = load_fixture("dto.painter_part_task.1.json")
    part = PainterPart.objects.get(painter=painter)
    from order.painter.dto import painter_part_task

    got = painter_part_task(part)
    assert set(got) == set(part_fx) and set(got["type"]) == set(part_fx["type"])
    for name in ("painter.part_task", "painter.part_due_ask", "painter.assigned"):
        real = bot_events.one(name)
        fixture = load_fixture(f"event.{name}.json")["data"]
        assert set(real) == set(fixture), name
    assert set(bot_events.one("painter.part_task")["part"]) == set(part_fx)
    assert set(bot_events.one("painter.assigned")["painter"]) == set(fx)
    PS.set_painter_due(painter, by=head, days=5)
    ev = bot_events.one("painter.part_due_set")
    assert set(ev) == set(load_fixture("event.painter.part_due_set.json")["data"])
    assert set(ev["part"]) == set(part_fx)
    PS.mark_painter_done(painter, by=mol, note=NOTE)
    assert set(bot_events.one("painter.part_done")) == set(
        load_fixture("event.painter.part_done.json")["data"]
    )
    assert set(bot_events.one("painter.done")) == set(
        load_fixture("event.painter.done.json")["data"]
    )
    assert set(load_fixture("misc.painter_done_request.json")) == {"note"}
    assert set(load_fixture("misc.painter_part_done_request.json")) == {"note"}
    assert set(load_fixture("misc.painter_part_due_request.json")) == {"days"}
    for name in ("done", "due", "type"):
        assert set(load_fixture(f"misc.painter_{name}_response.json")["painter"]) == set(fx), name
    for name in ("done", "due"):
        assert set(load_fixture(f"misc.painter_part_{name}_response.json")["part"]) == set(part_fx)
