"""The bosh menejer sends an order to detailing with a deadline (due_at)."""

from datetime import timedelta

from django.utils import timezone

from order.constants import OrderStatus
from order.detailing.models import Detailing

BOSS = ("order.view_order", "detailing.add_detailing", "detailing.view_detailing")


def _future(days=2):
    return (timezone.now() + timedelta(days=days)).replace(microsecond=0)


def test_deadline_required_and_in_future(api, order_factory, today):
    order = order_factory(end_date=today)
    client = api(*BOSS)
    url = f"/api/v1/orders/{order.pk}/detailing/"

    assert client.post(url, {}, format="json").status_code == 400
    past = (timezone.now() - timedelta(hours=1)).isoformat()
    resp = client.post(url, {"due_at": past}, format="json")
    assert resp.status_code == 400
    order.refresh_from_db()
    assert order.status == OrderStatus.CREATED
    assert not Detailing.objects.filter(order=order).exists()

    due = _future()
    resp = client.post(url, {"due_at": due.isoformat()}, format="json")
    assert resp.status_code == 200, resp.content
    assert Detailing.objects.get(order=order).due_at == due


def test_deadline_shown_and_moved(api, order_factory, today):
    order = order_factory(end_date=today)
    boss = api(*BOSS)
    boss.post(
        f"/api/v1/orders/{order.pk}/detailing/", {"due_at": _future().isoformat()}, format="json"
    )
    detailing = Detailing.objects.get(order=order)

    resp = boss.get(f"/api/v1/detailings/{detailing.pk}/")
    assert resp.data["due_at"] and resp.data["actions"]["due"] is True

    new_due = _future(5)
    resp = boss.post(
        f"/api/v1/detailings/{detailing.pk}/due/", {"due_at": new_due.isoformat()}, format="json"
    )
    assert resp.status_code == 200, resp.content
    detailing.refresh_from_db()
    assert detailing.due_at == new_due

    # The detailing worker cannot move it, nor PATCH it in.
    worker = api("detailing.view_detailing", "detailing.change_detailing")
    url = f"/api/v1/detailings/{detailing.pk}/"
    assert worker.get(url).data["actions"]["due"] is False
    assert worker.post(f"{url}due/", {"due_at": _future(9).isoformat()}, format="json").status_code == 403
    worker.patch(url, {"due_at": _future(9).isoformat()}, format="json")
    detailing.refresh_from_db()
    assert detailing.due_at == new_due

    # A done detailing keeps its deadline.
    detailing.done = True
    detailing.save(update_fields=["done"])
    resp = boss.post(f"{url}due/", {"due_at": _future(7).isoformat()}, format="json")
    assert resp.status_code == 400
