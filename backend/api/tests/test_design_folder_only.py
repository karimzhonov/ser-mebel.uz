"""Rover and Molyar workers read only the order's «Дизайн» folder (and below), as one folder;
they have no filer permissions (oauth 0020)."""

import importlib
from datetime import datetime

import pytest
from django.apps import apps as global_apps
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from djmoney.money import Money
from filer.models import File, Folder
from rest_framework.test import APIClient

from metering.models import Metering
from order.painter.models import Painter, PainterType
from order.rover.models import Rover

pytestmark = pytest.mark.django_db


def group_client(name, make_staff):
    u = make_staff()
    u.groups.add(Group.objects.get(name=name))
    c = APIClient()
    c.force_authenticate(type(u).objects.get(pk=u.pk))
    c.user = u
    return c


def tree(order, with_files=None):
    """order folder > Замеры (metering) > Дизайн > sub, plus a stage folder."""
    order_folder = Folder.objects.create(name="Заказ")
    meter = Folder.objects.create(name="Замеры", parent=order_folder)
    design = Folder.objects.create(name="Дизайн", parent=meter)
    sub = Folder.objects.create(name="sub", parent=design)
    stage = Folder.objects.create(name="Rover", parent=order_folder)
    m = Metering.objects.create(
        client=order.client, date_time=datetime(2026, 10, 1, 10), folder=meter
    )
    Metering.objects.filter(pk=m.pk).update(folder=meter)
    order.metering = m
    order.folder = order_folder
    order.save(update_fields=["metering", "folder"])
    return order_folder, meter, design, sub, stage


@pytest.fixture
def media(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)


def test_rover_reads_only_design_folder(order_factory, make_staff, media):
    o = order_factory()
    Rover.objects.create(order=o, square=1, price=Money(1, "UZS"))
    order_folder, meter, design, sub, stage = tree(o)
    f = File.objects.create(
        folder=sub, original_filename="x.pdf", file=SimpleUploadedFile("x.pdf", b"%PDF")
    )
    c = group_client("Rover", make_staff)
    for denied in (order_folder, meter, stage):
        assert c.get(f"/api/v1/folders/{denied.pk}/").status_code == 403
    got = c.get(f"/api/v1/folders/{design.pk}/")
    assert got.status_code == 200
    assert got.data["parent"] is None and got.data["read_only"] and not got.data["can_write"]
    assert [b["name"] for b in got.data["breadcrumbs"]] == ["Дизайн"]
    got = c.get(f"/api/v1/folders/{sub.pk}/")
    assert got.status_code == 200 and got.data["parent"] == design.pk
    assert [b["name"] for b in got.data["breadcrumbs"]] == ["Дизайн", "sub"]
    assert c.get(f"/api/v1/files/{f.pk}/").status_code == 200
    assert c.get(f"/api/v1/folders/{design.pk}/messages/").status_code == 403
    # writes refused
    assert c.post(f"/api/v1/folders/{design.pk}/", {"name": "n"}, format="json").status_code == 403
    up = SimpleUploadedFile("y.pdf", b"%PDF-1")
    assert c.post(f"/api/v1/folders/{design.pk}/", {"file": up}).status_code == 403
    assert c.delete(f"/api/v1/files/{f.pk}/").status_code == 403
    msg = c.post(f"/api/v1/folders/{design.pk}/messages/", {"message": "hi"}, format="json")
    assert msg.status_code == 403
    # root-level listings / files outside the design folder
    other = File.objects.create(
        folder=stage, original_filename="z.pdf", file=SimpleUploadedFile("z.pdf", b"%PDF")
    )
    assert c.get(f"/api/v1/files/{other.pk}/").status_code == 403


def test_rover_no_access_without_rover_row(order_factory, make_staff):
    o = order_factory()
    _, _, design, _, _ = tree(o)
    c = group_client("Rover", make_staff)
    assert c.get(f"/api/v1/folders/{design.pk}/").status_code == 403


def test_molyar_only_own_team(order_factory, make_staff):
    c = group_client("Molyar", make_staff)
    mine = PainterType.objects.create(name="A", price=Money(1, "UZS"), user=c.user)
    theirs = PainterType.objects.create(name="B", price=Money(1, "UZS"))
    o1, o2 = order_factory(), order_factory()
    o1_folder, o1_meter, o1_design, _, o1_stage = tree(o1)
    _, _, o2_design, _, _ = tree(o2)
    p = Painter.objects.create(order=o1, square=1, type=mine, folder=o1_stage)
    Painter.objects.create(order=o2, square=1, type=theirs)
    assert c.get(f"/api/v1/folders/{o1_design.pk}/").status_code == 200
    assert c.get(f"/api/v1/folders/{o2_design.pk}/").status_code == 403
    for denied in (o1_folder, o1_meter, o1_stage):
        assert c.get(f"/api/v1/folders/{denied.pk}/").status_code == 403
    item = c.get("/api/v1/painters/").data["results"][0]
    assert item["id"] == p.pk
    assert item["folder"] is None and item["order"]["folder"] is None
    assert item["design_folder"] == o1_design.pk


def test_full_viewers_unchanged(order_factory, make_staff, api):
    o = order_factory()
    t = PainterType.objects.create(name="A", price=Money(1, "UZS"))
    order_folder, meter, design, _, stage = tree(o)
    p = Painter.objects.create(order=o, square=1, type=t)
    Painter.objects.filter(pk=p.pk).update(folder=stage)
    head = api("oauth.user_production_head", "painter.view_painter")
    item = head.get("/api/v1/painters/").data["results"][0]
    assert item["folder"] == stage.pk and item["order"]["folder"] == order_folder.pk
    assert item["design_folder"] == design.pk
    admin = api(superuser=True)
    got = admin.get(f"/api/v1/folders/{design.pk}/")
    assert got.data["parent"] == meter.pk and got.data["can_write"] and not got.data["read_only"]
    assert [b["name"] for b in got.data["breadcrumbs"]] == ["Заказ", "Замеры", "Дизайн"]


def test_filer_user_without_group_unchanged(order_factory, api):
    o = order_factory()
    _, meter, _, _, _ = tree(o)
    c = api("filer.view_folder")
    assert c.get(f"/api/v1/folders/{meter.pk}/").status_code == 200


def test_migration_0020_only_rover_and_molyar_idempotent():
    mod = importlib.import_module("oauth.migrations.0020_rover_molyar_no_filer")
    perms = list(Permission.objects.filter(content_type__app_label="filer"))
    rover, molyar = Group.objects.get(name="Rover"), Group.objects.get(name="Molyar")
    odd = Group.objects.create(name="  MOLYAR ")
    other = Group.objects.get(name="Sborkachi")
    for g in (rover, molyar, odd, other):
        g.permissions.add(*perms)
    before = other.permissions.count()
    for _ in range(2):
        mod.remove_filer_perms(global_apps, None)
        for g in (rover, molyar, odd):
            assert not g.permissions.filter(content_type__app_label="filer").exists()
        assert other.permissions.count() == before
    mod.migrations.RunPython.noop  # reverse is a no-op by design
    assert "rover.view_rover" in {
        f"{p.content_type.app_label}.{p.codename}" for p in rover.permissions.all()
    }


def test_fresh_rover_molyar_have_no_filer_perms():
    for name in ("Rover", "Molyar"):
        assert (
            not Group.objects.get(name=name)
            .permissions.filter(content_type__app_label="filer")
            .exists()
        )


def post_order_tree(order):
    """The real layout after the order is made: «Дизайн» sits under the ORDER folder."""
    order_folder, meter, _, _, stage = tree(order)
    Folder.objects.filter(parent=meter, name="Дизайн").update(parent=order_folder)
    design = Folder.objects.get(parent=order_folder, name="Дизайн")
    return order_folder, meter, design, stage


def test_design_folder_under_order_folder(order_factory, make_staff, api):
    from order.rover.dto import design_folder_id, design_folder_url

    o = order_factory()
    r = Rover.objects.create(order=o, square=1, price=Money(1, "UZS"))
    order_folder, meter, design, stage = post_order_tree(o)
    o.refresh_from_db()
    assert design_folder_id(o, fallback=False) == design.pk
    assert design_folder_url(o).endswith(f"/files/{design.pk}")
    c = group_client("Rover", make_staff)
    assert c.get(f"/api/v1/rovers/{r.pk}/").data["design_folder"] == design.pk
    assert c.get("/api/v1/rovers/").data["results"][0]["design_folder"] == design.pk
    got = c.get(f"/api/v1/folders/{design.pk}/")
    assert got.status_code == 200 and got.data["parent"] is None
    assert [b["name"] for b in got.data["breadcrumbs"]] == ["Дизайн"]
    assert c.get(f"/api/v1/folders/{order_folder.pk}/").status_code == 403
    assert c.get(f"/api/v1/folders/{meter.pk}/").status_code == 403


def test_painter_design_folder_under_order_folder(order_factory, make_staff):
    c = group_client("Molyar", make_staff)
    t = PainterType.objects.create(name="A", price=Money(1, "UZS"), user=c.user)
    o = order_factory()
    _, _, design, _ = post_order_tree(o)
    Painter.objects.create(order=o, square=1, type=t)
    item = c.get("/api/v1/painters/").data["results"][0]
    assert item["design_folder"] == design.pk and item["folder"] is None
    assert c.get(f"/api/v1/folders/{design.pk}/").status_code == 200


def test_scoped_user_never_writes_even_with_direct_filer_perms(order_factory, make_staff):
    o, o2 = order_factory(), order_factory()
    Rover.objects.create(order=o, square=1, price=Money(1, "UZS"))
    _, _, design, sub, _ = tree(o)
    other = tree(o2)[2]
    f = File.objects.create(
        folder=sub, original_filename="x.pdf", file=SimpleUploadedFile("x.pdf", b"%PDF")
    )
    c = group_client("Rover", make_staff)
    for codename in ("add_file", "add_folder", "delete_file"):
        c.user.user_permissions.add(
            Permission.objects.get(codename=codename, content_type__app_label="filer")
        )
    c.force_authenticate(type(c.user).objects.get(pk=c.user.pk))
    for target in (design, other):
        up = SimpleUploadedFile("y.pdf", b"%PDF-1")
        assert c.post(f"/api/v1/folders/{target.pk}/", {"file": up}).status_code == 403
        assert (
            c.post(f"/api/v1/folders/{target.pk}/", {"name": "n"}, format="json").status_code == 403
        )
    assert c.delete(f"/api/v1/files/{f.pk}/").status_code == 403
    assert File.objects.filter(pk=f.pk).exists()


def test_molyar_needs_finished_rover(order_factory, make_staff):
    c = group_client("Molyar", make_staff)
    t = PainterType.objects.create(name="A", price=Money(1, "UZS"), user=c.user)
    o = order_factory()
    r = Rover.objects.create(order=o, square=1, price=Money(1, "UZS"))
    _, _, design, _, _ = tree(o)
    Painter.objects.create(order=o, square=1, type=t)
    assert c.get(f"/api/v1/folders/{design.pk}/").status_code == 403
    Rover.objects.filter(pk=r.pk).update(done=True)
    assert c.get(f"/api/v1/folders/{design.pk}/").status_code == 200


FILER_WRITE = ("view_folder", "add_folder", "add_file", "delete_file")


def with_filer_and_flag(c, flag):
    perms = [("filer", n) for n in FILER_WRITE] + [("oauth", flag)]
    for app, codename in perms:
        c.user.user_permissions.add(
            Permission.objects.get(codename=codename, content_type__app_label=app)
        )
    c.force_authenticate(type(c.user).objects.get(pk=c.user.pk))
    return c


def check_scoped_with_filer(c, order_folder, other_order_folder, other_design, design, sub, f):
    assert c.get(f"/api/v1/folders/{order_folder.pk}/").status_code == 403
    assert c.get(f"/api/v1/folders/{other_order_folder.pk}/").status_code == 403
    assert c.get(f"/api/v1/folders/{other_design.pk}/").status_code == 403
    got = c.get(f"/api/v1/folders/{design.pk}/")
    assert got.status_code == 200
    assert got.data["read_only"] and not got.data["can_write"] and got.data["parent"] is None
    assert [b["name"] for b in got.data["breadcrumbs"]] == ["Дизайн"]
    assert c.get(f"/api/v1/folders/{sub.pk}/").status_code == 200
    assert c.get(f"/api/v1/files/{f.pk}/").status_code == 200
    up = SimpleUploadedFile("y.pdf", b"%PDF-1")
    assert c.post(f"/api/v1/folders/{design.pk}/", {"file": up}).status_code == 403
    assert c.post(f"/api/v1/folders/{design.pk}/", {"name": "n"}, format="json").status_code == 403
    assert c.delete(f"/api/v1/files/{f.pk}/").status_code == 403
    assert File.objects.filter(pk=f.pk).exists()
    assert c.get(f"/api/v1/folders/{design.pk}/messages/").status_code == 403
    msg = c.post(f"/api/v1/folders/{design.pk}/messages/", {"message": "hi"}, format="json")
    assert msg.status_code == 403


def two_trees(order_factory):
    o, o2 = order_factory(), order_factory()
    order_folder, _, design, sub, _ = tree(o)
    other_folder, _, other_design, _, _ = tree(o2)
    f = File.objects.create(
        folder=sub, original_filename="x.pdf", file=SimpleUploadedFile("x.pdf", b"%PDF")
    )
    return o, order_folder, design, sub, other_folder, other_design, f


def test_molyar_role_with_filer_perms_stays_scoped(order_factory, make_staff, media):
    c = group_client("Molyar", make_staff)
    t = PainterType.objects.create(name="A", price=Money(1, "UZS"), user=c.user)
    o, order_folder, design, sub, other_folder, other_design, f = two_trees(order_factory)
    Painter.objects.create(order=o, square=1, type=t)
    with_filer_and_flag(c, "user_painter")
    check_scoped_with_filer(c, order_folder, other_folder, other_design, design, sub, f)


def test_rover_role_with_filer_perms_stays_scoped(order_factory, make_staff, media):
    c = group_client("Rover", make_staff)
    o, order_folder, design, sub, other_folder, other_design, f = two_trees(order_factory)
    Rover.objects.create(order=o, square=1, price=Money(1, "UZS"))
    with_filer_and_flag(c, "user_rover")
    # no Rover row on the other order -> its design folder is closed too
    check_scoped_with_filer(c, order_folder, other_folder, other_design, design, sub, f)


def test_role_flag_with_full_access_unchanged(order_factory, make_staff, media):
    o, order_folder, design, sub, other_folder, other_design, f = two_trees(order_factory)
    for kwargs, extra in (
        ({"superuser": True}, None),
        ({}, "oauth.user_production_head"),
        ({}, "assembly.manager"),
    ):
        perms = ["filer.view_folder", "filer.add_folder", "oauth.user_painter"]
        if extra:
            perms.append(extra)
        try:
            u = make_staff(*perms, **kwargs)
        except Permission.DoesNotExist:
            continue
        c = APIClient()
        c.force_authenticate(u)
        got = c.get(f"/api/v1/folders/{order_folder.pk}/")
        assert got.status_code == 200 and got.data["can_write"] and not got.data["read_only"]
        assert c.get(f"/api/v1/folders/{other_design.pk}/").status_code == 200
        assert (
            c.post(f"/api/v1/folders/{design.pk}/", {"name": "n"}, format="json").status_code == 201
        )


def test_filer_user_without_role_flag_unchanged(order_factory, api):
    o, order_folder, design, sub, other_folder, other_design, f = two_trees(order_factory)
    c = api("filer.view_folder", "filer.add_folder", "filer.delete_file")
    assert c.get(f"/api/v1/folders/{order_folder.pk}/").data["can_write"]
    assert c.post(f"/api/v1/folders/{design.pk}/", {"name": "n"}, format="json").status_code == 201
    assert c.delete(f"/api/v1/files/{f.pk}/").status_code == 204
