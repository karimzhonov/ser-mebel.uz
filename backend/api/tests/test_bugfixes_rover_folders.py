"""Regressions: the same order showed up for the rover AND the painter at once —
painting must start only after the rover is done. Plus the folder-name hardening in
core/utils/filer.py."""

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
