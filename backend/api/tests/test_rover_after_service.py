"""A rover job reaches the rover section only once the detailing is done and its parts
came out of the service (Detailing.service_out_at)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from core.exceptions import ServiceConflict
from order.detailing.models import Detailing
from order.rover import services as RS
from order.rover.models import Rover

pytestmark = pytest.mark.django_db

WORKER = ("oauth.user_rover", "rover.view_rover", "rover.change_rover")
NOTE = "3 ta eshik frezerlandi"


def _setup(order_factory):
    order = order_factory()
    det = Detailing.objects.create(order=order, rover_square=2)
    return det, Rover.objects.get(order=order)


def test_waits_until_service_out_then_released_once(order_factory, make_staff, bot_events, api):
    worker = make_staff(*WORKER, name="Usta", telegram_id=1001)
    w = api(*WORKER)
    det, rover = _setup(order_factory)
    # detailing not done yet: hidden, nobody told, can't be handed in
    assert rover.released_at is None
    assert bot_events.of("rover.task") == []
    assert w.get("/api/v1/rovers/").data["count"] == 0
    with pytest.raises(ServiceConflict):
        RS.submit_rover(rover, by=worker, price=RS.auto_rover_price(2), note=NOTE)

    out = timezone.now() + timedelta(hours=3)
    Detailing.objects.filter(pk=det.pk).update(done=True, service_out_at=out)
    assert RS.release_due_rovers(timezone.now()) == 0  # parts still at the service
    assert Rover.objects.get(pk=rover.pk).released_at is None

    assert RS.release_due_rovers(out + timedelta(minutes=1)) == 1
    r = Rover.objects.get(pk=rover.pk)
    assert r.released_at == out + timedelta(minutes=1)
    assert bot_events.one("rover.task")["rover"]["id"] == rover.pk
    assert RS.release_due_rovers(out + timedelta(minutes=2)) == 0  # idempotent
    assert len(bot_events.of("rover.task")) == 1
    assert w.get("/api/v1/rovers/").data["count"] == 1
    RS.submit_rover(r, by=worker, price=RS.auto_rover_price(2), note=NOTE)


def test_rover_added_after_service_out_starts_at_once(order_factory):
    order = order_factory()
    det = Detailing.objects.create(order=order, square=5)
    Detailing.objects.filter(pk=det.pk).update(
        done=True, service_out_at=timezone.now() - timedelta(hours=1)
    )
    det.refresh_from_db()
    det.rover_square = 3
    det.save()
    assert Rover.objects.get(order=order).released_at is not None


def test_order_page_marks_rover_waiting(order_factory, admin_api):
    det, rover = _setup(order_factory)
    data = admin_api.get(f"/api/v1/orders/{det.order_id}/").data
    assert data["production"]["rover"]["released"] is False
