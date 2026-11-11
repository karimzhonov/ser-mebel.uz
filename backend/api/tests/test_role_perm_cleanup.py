"""oauth 0019: Molyar can't manage teams, the head can; Sborkachi is no assembly manager."""

import importlib

import pytest
from django.apps import apps
from django.contrib.auth.models import Group, Permission
from djmoney.money import Money
from rest_framework.test import APIClient

from order.assembly.models import Assembly
from order.painter.models import PainterType

pytestmark = pytest.mark.django_db

MOD = "oauth.migrations.0019_role_perm_cleanup"
TYPE = {"painter.add_paintertype", "painter.change_paintertype", "painter.delete_paintertype"}


def perms_of(g):
    return {f"{p.content_type.app_label}.{p.codename}" for p in g.permissions.all()}


def give(group, *keys):
    for k in keys:
        a, c = k.split(".")
        group.permissions.add(Permission.objects.get(content_type__app_label=a, codename=c))


def _client(group_name, make_staff):
    u = make_staff()
    u.groups.add(Group.objects.get(name=group_name))
    c = APIClient()
    c.force_authenticate(type(u).objects.get(pk=u.pk))
    c.user = u
    return c


def test_fresh_db_groups():
    molyar = perms_of(Group.objects.get(name="Molyar"))
    assert not TYPE & molyar and "painter.view_paintertype" in molyar
    assert TYPE <= perms_of(Group.objects.get(name="Ishlab chiqarish rahbari"))
    assert "assembly.manager" not in perms_of(Group.objects.get(name="Sborkachi"))
    assert "assembly.view_assembly" in perms_of(Group.objects.get(name="Sborkachi"))


def test_migration_idempotent_and_reversible():
    mod = importlib.import_module(MOD)
    molyar = Group.objects.get(name="Molyar")
    head = Group.objects.get(name="Ishlab chiqarish rahbari")
    sb = Group.objects.get(name="Sborkachi")
    odd = Group.objects.create(name=" SBORKACHI ")
    other = Group.objects.get(name="Bosh menejer")
    give(other, "assembly.manager")
    give(odd, "assembly.manager")
    for _ in range(2):
        mod.forward(apps, None)
        assert not TYPE & perms_of(molyar)
        assert TYPE <= perms_of(head)
        assert "assembly.manager" not in perms_of(sb) | perms_of(odd)
        assert "assembly.manager" in perms_of(other)
    mod.backward(apps, None)
    assert TYPE <= perms_of(molyar)
    assert "assembly.manager" in perms_of(sb)
    assert not TYPE & perms_of(head)
    mod.backward(apps, None)
    mod.forward(apps, None)


def test_molyar_cannot_patch_painter_types_head_can(make_staff):
    t = PainterType.objects.create(name="T", price=Money(1, "UZS"))
    url = f"/api/v1/painter-types/{t.pk}/"
    assert _client("Molyar", make_staff).patch(url, {"name": "N"}, format="json").status_code == 403
    head = _client("Ishlab chiqarish rahbari", make_staff)
    assert head.patch(url, {"name": "N", "outsource": True}, format="json").status_code == 200
    t.refresh_from_db()
    assert t.name == "N" and t.outsource is True


def test_sborkachi_restricted_and_sees_only_own_jobs(order_factory, make_staff):
    from order.constants import OrderStatus
    from order.models import Order
    from order.visibility import sees_full_order

    c = _client("Sborkachi", make_staff)
    assert sees_full_order(c.user) is False
    assert c.get("/api/v1/assemblies/assemblers/").status_code == 403
    mine, other = order_factory(), order_factory()
    Order.objects.filter(pk__in=[mine.pk, other.pk]).update(status=OrderStatus.ASSEMBLY)
    a1 = Assembly.objects.create(order=mine, user=c.user, square=1)
    Assembly.objects.create(order=other, user=make_staff(), square=1)
    got = c.get("/api/v1/assemblies/")
    assert got.status_code == 200
    assert [x["id"] for x in got.data["results"]] == [a1.pk]
