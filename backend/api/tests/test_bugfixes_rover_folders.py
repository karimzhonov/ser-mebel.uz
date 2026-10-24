"""Regressions for two staging bugs:
1. the same order showed up for the rover AND the painter at once — painting must
   start only after the rover is done;
2. staff without filer.* permissions could not open the folders of the objects they
   work on (e.g. a designer opening "Файлы замера")."""

from datetime import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from djmoney.money import Money

pytestmark = pytest.mark.django_db


# --- 1. rover -> painter ---------------------------------------------------------


@pytest.fixture
def rover_and_painter(order_factory):
    from order.painter.models import Painter, PainterType
    from order.rover.models import Rover

    order = order_factory()
    rover = Rover.objects.create(order=order, square=3)
    painter = Painter.objects.create(order=order, square=5)
    return rover, painter, PainterType


def test_painter_waits_for_rover(admin_api, rover_and_painter):
    rover, painter, _ = rover_and_painter
    assert admin_api.get("/api/v1/painters/").data["count"] == 0
    assert admin_api.get("/api/v1/rovers/").data["count"] == 1
    overview = admin_api.get("/api/v1/dashboard/overview/").data
    stages = {s["key"]: s["count"] for s in overview["production"]["stages"]}
    assert stages["rover"] == 1 and stages["painter"] == 0

    admin_api.post(f"/api/v1/rovers/{rover.pk}/done/")
    assert admin_api.get("/api/v1/painters/").data["count"] == 1


def test_painter_actions_blocked_until_rover_done(rover_and_painter):
    from core.exceptions import ServiceError
    from oauth.models import User
    from order.painter.services import assign_painter_type, mark_painter_done

    rover, painter, PainterType = rover_and_painter
    ptype = PainterType.objects.create(
        name="Глянец", price=Money(5, "USD"), user=User.objects.create_user(phone="+998907770000")
    )
    with pytest.raises(ServiceError):
        assign_painter_type(painter, ptype)
    with pytest.raises(ServiceError):
        mark_painter_done(painter)


def test_order_without_rover_goes_straight_to_painter(admin_api, order_factory):
    from order.painter.models import Painter

    Painter.objects.create(order=order_factory(), square=5)
    assert admin_api.get("/api/v1/painters/").data["count"] == 1


# --- 2. folders follow the object -------------------------------------------------


@pytest.fixture
def metering_with_design(db_client):
    from core.utils import create_folder
    from metering.design.models import Design
    from metering.models import Metering

    m = Metering.objects.create(client=db_client, date_time=datetime(2026, 10, 1, 10))
    if m.folder_id is None:
        create_folder(m, "Замер")
        m.refresh_from_db()
    Design.objects.create(metering=m)
    return m


def test_designer_opens_metering_folder_without_filer_perms(
    api, metering_with_design, tmp_path, settings
):
    settings.MEDIA_ROOT = str(tmp_path)
    designer = api("design.view_design")
    url = f"/api/v1/folders/{metering_with_design.folder_id}/"
    resp = designer.get(url)
    assert resp.status_code == 200, resp.data
    assert resp.data["rights"]["upload"] is True
    pdf = SimpleUploadedFile("design.pdf", b"%PDF-1.4", content_type="application/pdf")
    assert designer.post(url, {"file": pdf}, format="multipart").status_code == 201


def test_unrelated_staff_cannot_open_folder(api, metering_with_design):
    outsider = api("call_center.view_invoice")
    assert outsider.get(f"/api/v1/folders/{metering_with_design.folder_id}/").status_code == 403


def test_assembler_opens_only_own_order_folder(api, make_staff, order_factory):
    from filer.models import Folder

    from order.assembly.models import Assembly

    me = api("assembly.view_assembly")
    mine, other = order_factory(), order_factory()
    for order in (mine, other):
        order.folder = Folder.objects.create(name=f"Заказ-{order.pk}")
        order.save(update_fields=["folder"])
    Assembly.objects.create(order=mine, square=1, user=me.user)
    Assembly.objects.create(order=other, square=1, user=make_staff())
    assert me.get(f"/api/v1/folders/{mine.folder_id}/").status_code == 200
    assert me.get(f"/api/v1/folders/{other.folder_id}/").status_code == 403


def test_only_own_files_deletable_without_filer_delete(
    api, metering_with_design, tmp_path, settings
):
    from filer.models import File

    settings.MEDIA_ROOT = str(tmp_path)
    designer = api("design.view_design")
    folder = metering_with_design.folder
    someone_elses = File.objects.create(
        folder=folder, original_filename="a.pdf", file=SimpleUploadedFile("a.pdf", b"%PDF")
    )
    mine = designer.post(
        f"/api/v1/folders/{folder.pk}/",
        {"file": SimpleUploadedFile("b.pdf", b"%PDF", content_type="application/pdf")},
        format="multipart",
    ).data[0]
    assert mine["can_delete"] is True
    assert designer.delete(f"/api/v1/files/{someone_elses.pk}/").status_code == 403
    assert designer.delete(f"/api/v1/files/{mine['id']}/").status_code == 204


# --- review follow-ups ------------------------------------------------------------


def test_stray_same_named_folders_dont_hijack_or_crash_new_objects(db_client, default_factory):
    """A user-made "Заказ" / "Заказ-<next pk>" folder elsewhere must be ignored."""
    from filer.models import Folder

    from conftest import make_order

    elsewhere = Folder.objects.create(name="Где-то")
    Folder.objects.create(name="Заказ", parent=elsewhere)
    first = make_order(db_client=db_client)
    from core.utils import create_folder

    create_folder(first, "Заказ")
    trap = Folder.objects.create(name=f"Заказ-{first.pk + 1}", parent=elsewhere)
    second = make_order(db_client=db_client)
    folder = create_folder(second, "Заказ")
    assert folder.pk != trap.pk
    assert folder.parent.name == "Заказ" and folder.parent.parent is None


def test_workers_cannot_create_folders_and_reserved_names_refused(
    api, admin_api, metering_with_design
):
    designer = api("design.view_design")
    url = f"/api/v1/folders/{metering_with_design.folder_id}/"
    assert designer.get(url).data["rights"]["create_folder"] is False
    assert designer.post(url, {"name": "Заказ-99"}, format="json").status_code == 403
    assert admin_api.post(url, {"name": "Заказ-99"}, format="json").status_code == 400
    assert admin_api.post(url, {"name": "Фото объекта"}, format="json").status_code == 201


def test_price_folder_closed_to_production_staff(api, order_factory):
    from filer.models import Folder

    from metering.price.models import Price
    from order.assembly.models import Assembly

    me = api("assembly.view_assembly")
    order = order_factory()
    order.folder = Folder.objects.create(name=f"Заказ-{order.pk}")
    order.save(update_fields=["folder"])
    price_folder = Folder.objects.create(name="Расчёт цены", parent=order.folder)
    price = Price.objects.create()
    Price.objects.filter(pk=price.pk).update(folder=price_folder)
    Assembly.objects.create(order=order, square=1, user=me.user)
    assert me.get(f"/api/v1/folders/{order.folder_id}/").status_code == 200
    assert me.get(f"/api/v1/folders/{price_folder.pk}/").status_code == 403


def test_unfiled_file_deletable_by_admin(admin_api, tmp_path, settings):
    from filer.models import File

    settings.MEDIA_ROOT = str(tmp_path)
    f = File.objects.create(original_filename="x.pdf", file=SimpleUploadedFile("x.pdf", b"%PDF"))
    assert admin_api.delete(f"/api/v1/files/{f.pk}/").status_code == 204


def test_rover_done_notifies_painting_ready(admin_api, rover_and_painter, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "oauth.models.User.send_messages", classmethod(lambda cls, *a, **k: calls.append((a, k)))
    )
    rover, painter, _ = rover_and_painter
    admin_api.post(f"/api/v1/rovers/{rover.pk}/done/")
    assert calls and calls[0][0][0] == "assembly.manager"
