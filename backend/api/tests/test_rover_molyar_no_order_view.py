"""oauth 0018: the «Rover» and «Molyar» lavozims lose order.view_order; their work pages stay."""

import importlib
from datetime import date

import pytest
from django.apps import apps
from django.contrib.auth.models import Group, Permission
from djmoney.money import Money

from order.painter.models import Painter, PainterType
from order.rover.models import Rover

pytestmark = pytest.mark.django_db

MOD = "oauth.migrations.0018_rover_molyar_no_order_view"


def perms_of(g):
    return {f"{p.content_type.app_label}.{p.codename}" for p in g.permissions.all()}


def give(group, *keys):
    for k in keys:
        a, c = k.split(".")
        group.permissions.add(Permission.objects.get(content_type__app_label=a, codename=c))


def test_fresh_db_rover_and_molyar_have_no_order_view():
    for name in ("Rover", "Molyar"):
        p = perms_of(Group.objects.get(name=name))
        assert not {"order.view_order", "order.view_order_price"} & p
    assert "rover.view_rover" in perms_of(Group.objects.get(name="Rover"))
    assert "painter.view_painter" in perms_of(Group.objects.get(name="Molyar"))


def test_migration_strips_only_rover_and_molyar_and_is_idempotent():
    mod = importlib.import_module(MOD)
    rover, molyar = Group.objects.get(name="Rover"), Group.objects.get(name="Molyar")
    odd = Group.objects.create(name="  MOLYAR ")
    for g in (rover, molyar, odd):
        give(g, "order.view_order", "order.view_order_price")
    other = Group.objects.get(name="Sborkachi")
    checker = Group.objects.get(name="Rover tekshiruvchi")
    before = (perms_of(other), perms_of(checker))
    assert "order.view_order" in before[0] and "order.view_order" in before[1]
    for _ in range(2):
        mod.remove_perms(apps, None)
        for g in (rover, molyar, odd):
            p = perms_of(g)
            assert "order.view_order" not in p and "order.view_order_price" not in p
        assert (perms_of(other), perms_of(checker)) == before
    assert "rover.view_rover" in perms_of(rover)
    mod.restore_perms(apps, None)
    assert "order.view_order" in perms_of(rover)
    assert "order.view_order_price" not in perms_of(rover)


def _client(group_name, make_staff):
    from rest_framework.test import APIClient

    u = make_staff()
    u.groups.add(Group.objects.get(name=group_name))
    c = APIClient()
    c.force_authenticate(type(u).objects.get(pk=u.pk))
    c.user = u
    return c


def test_rover_group_user_cannot_open_orders_but_keeps_rover_pages(order_factory, make_staff):
    o = order_factory(end_date=date(2026, 12, 1))
    r = Rover.objects.create(order=o, square=4, price=Money(1, "UZS"))
    c = _client("Rover", make_staff)
    assert c.get(f"/api/v1/orders/{o.pk}/").status_code == 403
    assert c.get("/api/v1/rovers/").status_code == 200
    got = c.get(f"/api/v1/rovers/{r.pk}/")
    assert got.status_code == 200 and got.data["restricted"] is True


def test_molyar_group_painter_still_sees_own_jobs(order_factory, make_staff):
    c = _client("Molyar", make_staff)
    t = PainterType.objects.create(name="T", price=Money(1, "UZS"), user=c.user)
    o = order_factory()
    p = Painter.objects.create(order=o, square=3, type=t)
    assert c.get(f"/api/v1/orders/{o.pk}/").status_code == 403
    got = c.get("/api/v1/painters/")
    assert got.status_code == 200 and [x["id"] for x in got.data["results"]] == [p.pk]
    assert c.get("/api/v1/painter-types/").status_code == 200
