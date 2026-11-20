"""Sending an order to detailing gives the detailers a Telegram card (deadline, client,
«Bajardim» on the site) instead of the bare «Оповещение о заказе»."""

from datetime import timedelta

import pytest
from django.utils import timezone

from api.tests.botkit import load_fixture
from order.detailing.dto import detailing_task
from order.detailing.models import Detailing

pytestmark = pytest.mark.django_db

DETAILER = ("oauth.user_detailing", "detailing.view_detailing")


def _future(days=2):
    return (timezone.now() + timedelta(days=days)).replace(microsecond=0)


def test_send_and_move_emit_card_no_bare_message(
    admin_api, order_factory, make_staff, bot_events, monkeypatch, today
):
    from oauth.models import User

    bare = []
    monkeypatch.setattr(User, "send_message", lambda self, *a, **k: bare.append(self.pk))
    make_staff(*DETAILER, name="Detal", telegram_id=3001)
    make_staff(*DETAILER, name="Telegramsiz")  # no Telegram: not in `to`
    make_staff("detailing.view_detailing", name="Faqat ko'radi", telegram_id=3002)
    order = order_factory(end_date=today)
    due = _future()
    resp = admin_api.post(
        f"/api/v1/orders/{order.pk}/detailing/", {"due_at": due.isoformat()}, format="json"
    )
    assert resp.status_code == 200, resp.content
    ev = bot_events.one("detailing.task")
    assert ev["to"] == [3001] and ev["how"] == "new"
    card = ev["detailing"]
    assert card["order"]["number"] == order.order_number
    assert card["due_at"] == due.isoformat(timespec="seconds")
    assert card["url"].endswith(f"/production/detailing?open={card['id']}")
    assert bare == []  # the bare Telegram message is gone

    bot_events.clear()
    new_due = _future(5)
    resp = admin_api.post(
        f"/api/v1/detailings/{card['id']}/due/", {"due_at": new_due.isoformat()}, format="json"
    )
    assert resp.status_code == 200, resp.content
    ev = bot_events.one("detailing.task")
    assert ev["how"] == "moved"
    assert ev["detailing"]["due_at"] == new_due.isoformat(timespec="seconds")


def test_dto_matches_fixture(order_factory):
    d = Detailing.objects.create(order=order_factory(), due_at=_future())
    want = load_fixture("event.detailing.task.json")["data"]["detailing"]
    assert set(detailing_task(d)) == set(want)
