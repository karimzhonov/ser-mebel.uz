"""Rover section: the worker reads the order's «Деталировка» folder too, hands the job in
with the amount in so'm AND $, and records client «peredelka» jobs (order/client, m², sum)."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone
from djmoney.money import Money
from filer.models import Folder
from rest_framework.test import APIClient

from order.detailing.models import Detailing
from order.rover.models import Rover, RoverRework

pytestmark = pytest.mark.django_db


def rover_client(make_staff, group="Rover"):
    u = make_staff()
    u.groups.add(Group.objects.get(name=group))
    c = APIClient()
    c.force_authenticate(type(u).objects.get(pk=u.pk))
    c.user = u
    return c


def detailed_order(order_factory, with_rover=True):
    o = order_factory()
    order_folder = Folder.objects.create(name="Заказ")
    det_folder = Folder.objects.create(name="Деталировка / Производстьво", parent=order_folder)
    sub = Folder.objects.create(name="dxf", parent=det_folder)
    d = Detailing.objects.create(order=o, done=True)
    Detailing.objects.filter(pk=d.pk).update(folder=det_folder)
    o.folder = order_folder
    o.save(update_fields=["folder"])
    rover = Rover.objects.create(order=o, square=2, price=Money(1, "UZS")) if with_rover else None
    return o, rover, order_folder, det_folder, sub


# --- detailing folder ---------------------------------------------------------------


def test_rover_worker_reads_detailing_folder(order_factory, make_staff):
    o, rover, order_folder, det_folder, sub = detailed_order(order_factory)
    c = rover_client(make_staff)
    item = c.get(f"/api/v1/rovers/{rover.pk}/").data
    assert item["detailing_folder"] == det_folder.pk
    listed = c.get("/api/v1/rovers/").data["results"][0]
    assert listed["detailing_folder"] == det_folder.pk
    got = c.get(f"/api/v1/folders/{det_folder.pk}/")
    assert got.status_code == 200, got.data
    assert got.data["read_only"] and not got.data["can_write"] and got.data["parent"] is None
    assert c.get(f"/api/v1/folders/{sub.pk}/").status_code == 200
    # still nothing above it, and no writes
    assert c.get(f"/api/v1/folders/{order_folder.pk}/").status_code == 403
    assert (
        c.post(f"/api/v1/folders/{det_folder.pk}/", {"name": "n"}, format="json").status_code == 403
    )


def test_detailing_folder_closed_without_rover(order_factory, make_staff):
    _, _, _, det_folder, _ = detailed_order(order_factory, with_rover=False)
    assert rover_client(make_staff).get(f"/api/v1/folders/{det_folder.pk}/").status_code == 403


def test_molyar_reads_detailing_folder_of_own_job(order_factory, make_staff):
    from order.painter.models import Painter, PainterPart, PainterType

    molyar = rover_client(make_staff, "Molyar")
    stranger = rover_client(make_staff, "Molyar")
    team = PainterType.objects.create(name="A", price=Money(1, "UZS"), user=molyar.user)
    PainterType.objects.create(name="B", price=Money(1, "UZS"), user=stranger.user)
    o, _, order_folder, det_folder, sub = detailed_order(order_factory, with_rover=False)
    p = Painter.objects.create(order=o, square=4)
    PainterPart.objects.create(painter=p, type=team, square=4)

    item = molyar.get(f"/api/v1/painters/{p.pk}/").data
    assert item["detailing_folder"] == det_folder.pk
    assert molyar.get("/api/v1/painters/").data["results"][0]["detailing_folder"] == det_folder.pk
    got = molyar.get(f"/api/v1/folders/{det_folder.pk}/")
    assert got.status_code == 200, got.data
    assert got.data["read_only"] and got.data["parent"] is None
    assert molyar.get(f"/api/v1/folders/{sub.pk}/").status_code == 200
    assert molyar.get(f"/api/v1/folders/{order_folder.pk}/").status_code == 403
    assert (
        molyar.post(f"/api/v1/folders/{det_folder.pk}/", {"name": "n"}, format="json").status_code
        == 403
    )
    # a team with no part in this job: closed
    assert stranger.get(f"/api/v1/folders/{det_folder.pk}/").status_code == 403


def test_molyar_detailing_folder_closed_while_rover_runs(order_factory, make_staff):
    """Painting starts after the rover: until then the molyar doesn't get the job (nor
    its folders), same as «Дизайн»."""
    from order.painter.models import Painter, PainterPart, PainterType

    molyar = rover_client(make_staff, "Molyar")
    team = PainterType.objects.create(name="A", price=Money(1, "UZS"), user=molyar.user)
    o, rover, _, det_folder, _ = detailed_order(order_factory)  # rover not done
    p = Painter.objects.create(order=o, square=4)
    PainterPart.objects.create(painter=p, type=team, square=4)
    assert molyar.get(f"/api/v1/folders/{det_folder.pk}/").status_code == 403
    Rover.objects.filter(pk=rover.pk).update(done=True)
    assert molyar.get(f"/api/v1/folders/{det_folder.pk}/").status_code == 200


# --- so'm + $ -----------------------------------------------------------------------


def _done(c, rover, uzs, usd, currency="UZS"):
    body = {"price": {"amount": str(uzs), "currency": currency}, "note": "4 ta eshik frezer"}
    if usd is not None:
        body["price_usd"] = str(usd)
    return c.post(f"/api/v1/rovers/{rover.pk}/done/", body, format="json")


def test_done_with_both_currencies(order_factory, make_staff):
    _, rover, *_ = detailed_order(order_factory)
    c = rover_client(make_staff)
    r = _done(c, rover, 150000, 20)
    assert r.status_code == 200, r.data
    assert r.data["state"] == "checking"
    assert float(r.data["price"]["amount"]) == 150000 and r.data["price"]["currency"] == "UZS"
    assert r.data["price_usd"] == 20
    rover.refresh_from_db()
    assert rover.price == Money(150000, "UZS") and float(rover.price_usd) == 20


def test_done_dollars_only_and_both_zero_refused(order_factory, make_staff):
    _, rover, *_ = detailed_order(order_factory)
    c = rover_client(make_staff)
    bad = _done(c, rover, 0, 0)
    assert bad.status_code == 400 and bad.data["field"] == "price"
    assert _done(c, rover, 0, -5).status_code == 400
    ok = _done(c, rover, 0, 35)
    assert ok.status_code == 200, ok.data
    assert ok.data["price_usd"] == 35


def test_done_without_price_usd_still_works(order_factory, make_staff):
    """The bot (and old clients) send only `price` (so'm)."""
    _, rover, *_ = detailed_order(order_factory)
    c = rover_client(make_staff)
    r = _done(c, rover, 100, None)
    assert r.status_code == 200, r.data
    rover.refresh_from_db()
    assert rover.price == Money(100, "UZS") and rover.price_usd == 0


def test_usd_price_becomes_the_dollar_part(order_factory, make_staff):
    _, rover, *_ = detailed_order(order_factory)
    c = rover_client(make_staff)
    assert _done(c, rover, 100, 5, currency="USD").data["field"] == "price"  # $ twice
    r = _done(c, rover, 100, None, currency="USD")
    assert r.status_code == 200, r.data
    rover.refresh_from_db()
    assert rover.price == Money(0, "UZS") and float(rover.price_usd) == 100


def test_dollar_only_reaches_bot_card_as_usd(order_factory, make_staff):
    from order.rover.dto import rover_task

    _, rover, *_ = detailed_order(order_factory)
    assert _done(rover_client(make_staff), rover, 0, 35).status_code == 200
    rover.refresh_from_db()
    card = rover_task(rover)
    assert card["amount"] == "35.00" and card["currency"] == "USD"


# --- peredelka ----------------------------------------------------------------------


def rover_order(order_factory):
    o = order_factory()
    Rover.objects.create(order=o, square=1, price=Money(1, "UZS"))  # no detailing: released
    return o


def test_picker_only_orders_that_reached_rover(order_factory, make_staff):
    plain = order_factory()
    o = rover_order(order_factory)
    c = rover_client(make_staff)
    ids = [x["id"] for x in c.get("/api/v1/rover-reworks/orders/").data]
    assert o.pk in ids and plain.pk not in ids
    r = c.post(
        "/api/v1/rover-reworks/", {"order": plain.pk, "square": 1, "price_uzs": 1}, format="json"
    )
    assert r.status_code == 400 and r.data["field"] == "order"


def test_worker_records_rework(order_factory, make_staff):
    o = rover_order(order_factory)
    c = rover_client(make_staff)
    picker = c.get("/api/v1/rover-reworks/orders/", {"search": str(o.order_number)}).data
    assert picker[0] == {"id": o.pk, "order_number": o.order_number, "client_fio": o.client.fio}
    assert "phone" not in picker[0]
    by_name = c.get("/api/v1/rover-reworks/orders/", {"search": o.client.fio[:4]}).data
    assert o.pk in [x["id"] for x in by_name]

    r = c.post(
        "/api/v1/rover-reworks/",
        {"order": o.pk, "square": 3.5, "price_uzs": "200000", "price_usd": "10", "note": "2 fasad"},
        format="json",
    )
    assert r.status_code == 201, r.data
    assert r.data["order_detail"]["client_fio"] == o.client.fio
    assert r.data["square"] == 3.5 and r.data["price_uzs"] == 200000 and r.data["price_usd"] == 10
    assert r.data["can_delete"] is True
    rw = RoverRework.objects.get()
    assert rw.created_by_id == c.user.pk

    listed = c.get("/api/v1/rover-reworks/").data
    assert listed["count"] == 1
    assert listed["totals"] == {"square": 3.5, "price_uzs": 200000, "price_usd": 10}


def test_rework_validation(order_factory, make_staff):
    o = rover_order(order_factory)
    c = rover_client(make_staff)
    post = lambda **kw: c.post(  # noqa: E731
        "/api/v1/rover-reworks/", {"order": o.pk, "square": 1, **kw}, format="json"
    )
    assert post(price_uzs=0, price_usd=0).data["field"] == "price_uzs"
    assert post(square=0, price_uzs=1).data["field"] == "square"
    assert post(price_uzs=-1, price_usd=5).status_code == 400
    assert post(price_usd=5).status_code == 201
    assert (
        c.post("/api/v1/rover-reworks/", {"square": 1, "price_uzs": 1}, format="json").status_code
        == 400
    )


def test_rework_scoping_and_delete(order_factory, make_staff, api):
    o = rover_order(order_factory)
    a, b = rover_client(make_staff), rover_client(make_staff)
    rid = a.post(
        "/api/v1/rover-reworks/", {"order": o.pk, "square": 1, "price_uzs": 5000}, format="json"
    ).data["id"]
    # another worker neither sees nor deletes it
    assert b.get("/api/v1/rover-reworks/").data["count"] == 0
    assert b.delete(f"/api/v1/rover-reworks/{rid}/").status_code == 404
    # the production head / checker sees every row
    head = api("oauth.user_production_head", "rover.view_rover")
    assert head.get("/api/v1/rover-reworks/").data["count"] == 1
    assert head.get("/api/v1/rover-reworks/", {"user": "x"}).status_code == 400
    checker = api("oauth.user_rover_checker", "rover.view_rover")
    assert checker.get("/api/v1/rover-reworks/").data["count"] == 1
    # the author can't delete a row from an earlier day; the head can
    RoverRework.objects.filter(pk=rid).update(created_at=timezone.now() - timedelta(days=2))
    assert a.delete(f"/api/v1/rover-reworks/{rid}/").status_code in (400, 403)
    assert head.delete(f"/api/v1/rover-reworks/{rid}/").status_code == 204
    assert not RoverRework.objects.exists()


def test_rework_needs_rover_role(order_factory, api):
    o = rover_order(order_factory)
    nobody = api()
    assert nobody.get("/api/v1/rover-reworks/").status_code == 403
    assert nobody.get("/api/v1/rover-reworks/orders/").status_code == 403
    viewer = api("rover.view_rover")
    assert viewer.get("/api/v1/rover-reworks/").status_code == 200
    assert (
        viewer.post(
            "/api/v1/rover-reworks/", {"order": o.pk, "square": 1, "price_uzs": 1}, format="json"
        ).status_code
        == 403
    )


# --- production head: «Tasdiqlash» / «Bekor qilish» --------------------------------


def test_head_rejects_and_worker_resubmits(order_factory, make_staff, api):
    _, rover, *_ = detailed_order(order_factory)
    worker = rover_client(make_staff)
    head = api("oauth.user_production_head", "rover.view_rover")
    assert _done(worker, rover, 150000, 0).status_code == 200

    card = head.get(f"/api/v1/rovers/{rover.pk}/").data
    assert card["actions"]["confirm"] and card["actions"]["reject"]
    # a reason is required
    bad = head.post(f"/api/v1/rovers/{rover.pk}/reject/", {"reason": " "}, format="json")
    assert bad.status_code == 400 and bad.data["field"] == "reason"
    r = head.post(
        f"/api/v1/rovers/{rover.pk}/reject/",
        {"reason": "Summa xato, 4 emas 3 eshik"},
        format="json",
    )
    assert r.status_code == 200, r.data
    assert r.data["state"] == "new" and r.data["submitted_at"] is None
    assert r.data["reject_reason"] == "Summa xato, 4 emas 3 eshik"
    assert r.data["rejected_by_detail"] is not None and r.data["rejected_at"]
    assert not r.data["actions"]["reject"]
    # back in «Faol»
    active = worker.get("/api/v1/rovers/", {"done": "false", "state": "new"}).data
    assert [x["id"] for x in active["results"]] == [rover.pk]
    assert worker.get(f"/api/v1/rovers/{rover.pk}/").data["actions"]["done"]
    # a second reject / confirm of a job not in checking is refused
    assert (
        head.post(
            f"/api/v1/rovers/{rover.pk}/reject/", {"reason": "yana"}, format="json"
        ).status_code
        == 400
    )
    assert head.post(f"/api/v1/rovers/{rover.pk}/confirm/").status_code == 400

    # the worker fixes it and hands it in again; the reason is cleared
    again = _done(worker, rover, 120000, 5)
    assert again.status_code == 200, again.data
    assert again.data["state"] == "checking" and again.data["reject_reason"] == ""
    ok = head.post(f"/api/v1/rovers/{rover.pk}/confirm/")
    assert ok.status_code == 200 and ok.data["state"] == "done"


def test_checker_can_reject_worker_cannot(order_factory, make_staff, api):
    _, rover, *_ = detailed_order(order_factory)
    worker = rover_client(make_staff)
    assert _done(worker, rover, 1000, 0).status_code == 200
    assert (
        worker.post(
            f"/api/v1/rovers/{rover.pk}/reject/", {"reason": "o'zim"}, format="json"
        ).status_code
        == 403
    )
    assert worker.get(f"/api/v1/rovers/{rover.pk}/").data["actions"]["reject"] is False
    checker = api("oauth.user_rover_checker", "rover.view_rover")
    r = checker.post(
        f"/api/v1/rovers/{rover.pk}/reject/", {"reason": "Izoh to'liq emas"}, format="json"
    )
    assert r.status_code == 200 and r.data["state"] == "new"
