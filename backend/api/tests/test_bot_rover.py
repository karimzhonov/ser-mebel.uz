"""Rover check flow: the worker hands the job in with the amount, a checker confirms it
(site or Telegram button); events and contract fixtures (docs/bot_contract/*rover*)."""

import pytest
from djmoney.money import Money

from api.tests.botkit import load_fixture
from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from order.rover import services as RS
from order.rover.dto import rover_task
from order.rover.models import Rover

pytestmark = pytest.mark.django_db

CHECKER = ("oauth.user_rover_checker", "rover.view_rover")
WORKER = ("rover.view_rover", "rover.change_rover")


@pytest.fixture
def rover(order_factory):
    return Rover.objects.create(order=order_factory(), square=4)


@pytest.fixture
def worker(make_staff):
    return make_staff(*WORKER, name="Rover ustasi")


@pytest.fixture
def checker(make_staff):
    return make_staff(*CHECKER, name="Tekshiruvchi", telegram_id=111222333)


NOTE = "Fasad frezerlandi, 8 ta eshik"


def amount(n="150000"):
    return Money(n, "UZS")


def test_submit_then_confirm(rover, worker, checker, bot_events):
    r = RS.submit_rover(rover, by=worker, price=amount(), note=NOTE)
    assert r.state == "checking" and not r.done and r.price == amount()
    assert bot_events.one("rover.check")["to"] == [111222333]
    r = RS.confirm_rover(r, by=checker)
    assert r.state == "done" and r.done and r.checked_by == checker
    data = bot_events.one("rover.checked")
    assert data["by_name"] == "Tekshiruvchi" and data["rover"]["state"] == "done"


def test_submit_guards(rover, worker, checker):
    with pytest.raises(ServiceError):
        RS.submit_rover(rover, by=worker, price=amount("0"), note=NOTE)
    with pytest.raises(ServiceForbidden):
        RS.submit_rover(rover, by=checker, price=amount(), note=NOTE)
    RS.submit_rover(rover, by=worker, price=amount(), note=NOTE)
    with pytest.raises(ServiceConflict):
        RS.submit_rover(rover, by=worker, price=amount(), note=NOTE)


def test_confirm_guards(rover, worker, checker):
    with pytest.raises(ServiceError):
        RS.confirm_rover(rover, by=checker)  # not handed in
    RS.submit_rover(rover, by=worker, price=amount(), note=NOTE)
    with pytest.raises(ServiceForbidden):
        RS.confirm_rover(rover, by=worker)
    RS.confirm_rover(rover, by=checker)
    with pytest.raises(ServiceConflict):
        RS.confirm_rover(rover, by=checker)


def test_bot_confirm_endpoint(rover, worker, checker, bot_client, bot_events):
    RS.submit_rover(rover, by=worker, price=amount(), note=NOTE)
    assert bot_client.post("rovers/999999/confirm/", actor=111222333).status_code == 404
    assert bot_client.post(f"rovers/{rover.pk}/confirm/", actor=777).status_code == 403
    resp = bot_client.post(f"rovers/{rover.pk}/confirm/", actor=111222333)
    assert resp.status_code == 200 and resp.json()["rover"]["state"] == "done"
    assert bot_client.post(f"rovers/{rover.pk}/confirm/", actor=111222333).status_code == 409


def test_rover_fixtures_match(rover, worker, checker):
    rover = RS.submit_rover(rover, by=worker, price=amount(), note=NOTE)
    rover = RS.confirm_rover(rover, by=checker)
    fixture = load_fixture("dto.rover_task.1.json")
    assert set(rover_task(rover)) == set(fixture)
    assert set(load_fixture("misc.rover_confirm_response.json")["rover"]) == set(fixture)
