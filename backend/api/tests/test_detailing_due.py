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
    assert (
        worker.post(f"{url}due/", {"due_at": _future(9).isoformat()}, format="json").status_code
        == 403
    )
    worker.patch(url, {"due_at": _future(9).isoformat()}, format="json")
    detailing.refresh_from_db()
    assert detailing.due_at == new_due

    # A done detailing keeps its deadline.
    detailing.done = True
    detailing.save(update_fields=["done"])
    resp = boss.post(f"{url}due/", {"due_at": _future(7).isoformat()}, format="json")
    assert resp.status_code == 400


def test_next_status_does_not_skip_the_detailing_deadline(admin_api, order_factory):
    """«Keyingi bosqich» from «Yaratildi» would reach detailing without a deadline."""
    from datetime import date, timedelta

    from order.constants import OrderStatus

    order = order_factory(end_date=date.today() + timedelta(days=30))
    assert order.status == OrderStatus.CREATED
    assert admin_api.get(f"/api/v1/orders/{order.pk}/").data["actions"]["next_status"] is False
    r = admin_api.post(f"/api/v1/orders/{order.pk}/next-status/")
    assert r.status_code == 400 and "muddat" in r.data["detail"]


def test_next_status_from_installing_needs_head_tayyor_when_assembly_exists(
    admin_api, order_factory
):
    """«Установка» -> «Готов» only via the production head's «Tayyor»; orders without an
    assembly row keep the plain step."""
    from order.assembly.models import Assembly
    from order.constants import OrderStatus
    from order.models import Order

    with_asm = order_factory()
    Order.objects.filter(pk=with_asm.pk).update(status=OrderStatus.INSTALLING)
    Assembly.objects.create(order=with_asm, square=5)
    data = admin_api.get(f"/api/v1/orders/{with_asm.pk}/").data["actions"]
    assert data["next_status"] is False and data["next_status_hint"]
    r = admin_api.post(f"/api/v1/orders/{with_asm.pk}/next-status/")
    assert r.status_code == 400 and "Tayyor" in r.data["detail"]
    assert Order.objects.get(pk=with_asm.pk).status == OrderStatus.INSTALLING

    without = order_factory()
    Order.objects.filter(pk=without.pk).update(status=OrderStatus.INSTALLING)
    data = admin_api.get(f"/api/v1/orders/{without.pk}/").data["actions"]
    assert data["next_status"] is True and data["next_status_hint"] is None
    assert admin_api.post(f"/api/v1/orders/{without.pk}/next-status/").status_code == 200
    assert Order.objects.get(pk=without.pk).status == OrderStatus.DONE
