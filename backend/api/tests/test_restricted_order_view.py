"""Rover jobs and outsource Molyar jobs show a reduced order to everyone but the
production head, assembly managers and superusers."""

import importlib
from datetime import date

import pytest
from django.apps import apps as global_apps
from djmoney.money import Money

from order.painter.models import Painter, PainterType
from order.rover.models import Rover

pytestmark = pytest.mark.django_db

PRIVATE = ("address", "address_link", "lat", "lon", "map_url", "end_date", "deadline")
ROVER_PERMS = ("oauth.user_rover", "rover.view_rover", "rover.change_rover")
HEAD_PERMS = ("oauth.user_production_head", "rover.view_rover", "painter.view_painter")
MANAGER_PERMS = ("assembly.manager", "rover.view_rover", "painter.view_painter")
PAINTER_PERMS = ("painter.view_painter",)


@pytest.fixture
def rover(order_factory):
    o = order_factory(end_date=date(2026, 12, 1), address="Chilonzor 7")
    return Rover.objects.create(order=o, square=4, price=Money(1, "UZS"))


def assert_stripped(order):
    for key in PRIVATE:
        assert order[key] is None, key
    assert order["client"]["phone"] is None and order["client"]["fio"]
    assert order["folder"] is None


def assert_full(order):
    assert order["address"] == "Chilonzor 7"
    assert order["end_date"] == "2026-12-01"
    assert order["client"]["phone"]


def test_rover_worker_gets_reduced_order(rover, api):
    c = api(*ROVER_PERMS)
    for data in (
        c.get(f"/api/v1/rovers/{rover.pk}/").data,
        c.get("/api/v1/rovers/").data["results"][0],
    ):
        assert data["restricted"] is True and data["can_open_order"] is False
        assert_stripped(data["order"])
        assert data["folder"] is None
        assert "design_folder" in data


def test_rover_design_folder_is_set(rover, api):
    from filer.models import Folder

    rover.order.folder = Folder.objects.create(name="order-folder")
    rover.order.save(update_fields=["folder"])
    # restricted viewer: no «Дизайн» folder → None, never the order folder
    data = api(*ROVER_PERMS).get(f"/api/v1/rovers/{rover.pk}/").data
    assert data["design_folder"] is None
    assert data["order"]["folder"] is None
    # full viewer keeps the fallback
    assert api(*HEAD_PERMS).get(f"/api/v1/rovers/{rover.pk}/").data["design_folder"] == (
        rover.order.folder_id
    )


def test_rover_design_folder_is_the_design_folder(rover, api):
    from filer.models import Folder

    root = Folder.objects.create(name="Замеры")
    design = Folder.objects.create(name="Дизайн", parent=root)
    from datetime import datetime

    from metering.models import Metering

    m = Metering.objects.create(
        client=rover.order.client, date_time=datetime(2026, 10, 1, 10), folder=root
    )
    Metering.objects.filter(pk=m.pk).update(folder=root)
    rover.order.metering = m
    rover.order.save(update_fields=["metering"])
    data = api(*ROVER_PERMS).get(f"/api/v1/rovers/{rover.pk}/").data
    assert data["design_folder"] == design.pk


def test_rover_list_query_count_does_not_grow(
    rover, api, order_factory, django_assert_max_num_queries
):
    c = api(*ROVER_PERMS)
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as one:
        c.get("/api/v1/rovers/")
    for _ in range(4):
        Rover.objects.create(order=order_factory(), square=1, price=Money(1, "UZS"))
    with CaptureQueriesContext(connection) as five:
        assert c.get("/api/v1/rovers/").data["count"] == 5
    assert len(five) <= len(one)


def test_painter_type_outsource_only_by_head(api):
    t = PainterType.objects.create(name="T", price=Money(1, "UZS"), outsource=True)
    perms = ("painter.view_paintertype", "painter.change_paintertype", "painter.add_paintertype")
    worker = api(*perms)
    url = f"/api/v1/painter-types/{t.pk}/"
    assert worker.patch(url, {"outsource": False}, format="json").status_code == 403
    t.refresh_from_db()
    assert t.outsource is True
    # same value / other fields are fine
    assert worker.patch(url, {"outsource": True, "name": "N"}, format="json").status_code == 200
    body = {"name": "X", "price": {"amount": 1, "currency": "UZS"}, "outsource": True}
    assert worker.post("/api/v1/painter-types/", body, format="json").status_code == 403
    body["outsource"] = False
    assert worker.post("/api/v1/painter-types/", body, format="json").status_code == 201
    head = api("oauth.user_production_head", *perms)
    assert head.patch(url, {"outsource": False}, format="json").status_code == 200
    t.refresh_from_db()
    assert t.outsource is False


def test_rover_worker_cannot_search_by_phone(rover, api):
    c = api(*ROVER_PERMS)
    phone = str(rover.order.client.phone)
    assert c.get("/api/v1/rovers/", {"search": phone}).data["count"] == 0
    assert api(*HEAD_PERMS).get("/api/v1/rovers/", {"search": phone}).data["count"] == 1


@pytest.mark.parametrize("who", ["head", "manager", "super"])
def test_rover_full_for_privileged(rover, api, who):
    c = (
        api(superuser=True)
        if who == "super"
        else api(*(HEAD_PERMS if who == "head" else MANAGER_PERMS))
    )
    data = c.get(f"/api/v1/rovers/{rover.pk}/").data
    assert data["restricted"] is False and data["can_open_order"] is True
    assert_full(data["order"])


def _painter(order_factory, make_staff, outsource):
    mol = make_staff(*PAINTER_PERMS, name="Molyar", telegram_id=1001)
    t = PainterType.objects.create(
        name="Team", price=Money(10, "UZS"), user=mol, outsource=outsource
    )
    o = order_factory(end_date=date(2026, 12, 1), address="Chilonzor 7")
    return mol, Painter.objects.create(order=o, square=5, type=t)


def test_outsource_painter_is_reduced_for_its_painter(order_factory, make_staff, api):
    mol, p = _painter(order_factory, make_staff, True)
    c = api(*PAINTER_PERMS)
    c.force_authenticate(mol)
    for data in (
        c.get(f"/api/v1/painters/{p.pk}/").data,
        c.get("/api/v1/painters/").data["results"][0],
    ):
        assert data["restricted"] is True and data["can_open_order"] is False
        for key in PRIVATE:
            assert data["order"][key] is None, key
        assert data["order"]["client"]["phone"] is None
        assert data["folder"] is None or data["folder"] == p.folder_id


def test_regular_painter_is_unchanged(order_factory, make_staff, api):
    mol, p = _painter(order_factory, make_staff, False)
    c = api(*PAINTER_PERMS)
    c.force_authenticate(mol)
    data = c.get(f"/api/v1/painters/{p.pk}/").data
    assert data["restricted"] is False and data["can_open_order"] is True
    assert_full(data["order"])


def test_head_sees_outsource_painter_in_full(order_factory, make_staff, api):
    _, p = _painter(order_factory, make_staff, True)
    data = api(*HEAD_PERMS).get(f"/api/v1/painters/{p.pk}/").data
    assert data["restricted"] is False
    assert_full(data["order"])


def test_painter_type_outsource_is_editable(api):
    c = api(
        "oauth.user_production_head",
        "painter.view_paintertype",
        "painter.add_paintertype",
        "painter.change_paintertype",
    )
    r = c.post(
        "/api/v1/painter-types/",
        {"name": "X", "price": {"amount": "1", "currency": "UZS"}, "outsource": True},
        format="json",
    )
    assert r.status_code == 201, r.data
    assert r.data["outsource"] is True


def test_dto_carries_outsource(order_factory, make_staff):
    from order.painter.dto import painter_task

    _, p = _painter(order_factory, make_staff, True)
    assert painter_task(p)["outsource"] is True


def test_migration_marks_outsource_by_name(db):
    mod = importlib.import_module("order.painter.migrations.0011_paintertype_outsource")
    names = ["Аутсорс команда", "Autsors Ali", "OUTSOURCE", "Glyanets"]
    for n in names:
        PainterType.objects.create(name=n, price=Money(1, "UZS"))
    mod.mark_outsource(global_apps, None)
    got = {t.name: t.outsource for t in PainterType.objects.all()}
    assert got == {
        "Аутсорс команда": True,
        "Autsors Ali": True,
        "OUTSOURCE": True,
        "Glyanets": False,
    }
