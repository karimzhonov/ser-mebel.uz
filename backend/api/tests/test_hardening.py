import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "1e20", "abc"])
def test_money_rejects_non_finite_and_huge(admin_api, order_factory, amount):
    order = order_factory()
    resp = admin_api.patch(
        f"/api/v1/orders/{order.pk}/",
        {"price": {"amount": amount, "currency": "USD"}},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/orders/?factory=x",
        "/api/v1/incomes/?date_from=bad",
        "/api/v1/inventory-types/?obj=x",
    ],
)
def test_bad_query_params_are_400(admin_api, url):
    assert admin_api.get(url).status_code == 400


def test_order_needs_finished_design(admin_api, db_client, default_factory):
    from datetime import datetime

    from metering.design.models import Design
    from metering.models import Metering

    metering = Metering.objects.create(client=db_client, date_time=datetime(2026, 10, 1, 10))
    design = Design.objects.create(metering=metering)
    design_type = design.designtype_set.first()
    body = {"metering": metering.pk, "design_type": design_type.pk, "address": "x"}
    assert admin_api.post("/api/v1/orders/", body, format="json").status_code == 400
    design.done = True
    design.save()
    assert admin_api.post("/api/v1/orders/", body, format="json").status_code == 201


def test_refused_order_leaves_no_orphan_client(admin_api):
    from client.models import Client
    from order.models import Factory

    Factory.objects.all().delete()  # no default factory -> create_order refuses
    resp = admin_api.post(
        "/api/v1/orders/",
        {"client_phone": "+998907770011", "client_fio": "New", "address": "x"},
        format="json",
    )
    assert resp.status_code == 400
    assert not Client.objects.filter(phone="+998907770011").exists()


def test_upload_rejects_executable_types(admin_api, tmp_path, settings):
    from filer.models import Folder

    settings.MEDIA_ROOT = str(tmp_path)
    folder = Folder.objects.create(name="f")
    bad = SimpleUploadedFile("x.html", b"<script>alert(1)</script>", content_type="text/html")
    resp = admin_api.post(f"/api/v1/folders/{folder.pk}/", {"file": bad}, format="multipart")
    assert resp.status_code == 400
    ok = SimpleUploadedFile("plan.pdf", b"%PDF-1.4", content_type="application/pdf")
    resp = admin_api.post(f"/api/v1/folders/{folder.pk}/", {"file": ok}, format="multipart")
    assert resp.status_code == 201
    listing = admin_api.get(f"/api/v1/folders/{folder.parent_id or folder.pk}/")
    assert listing.status_code == 200


def test_assemblers_list_is_manager_only(api):
    assert api("assembly.view_assembly").get("/api/v1/assemblies/assemblers/").status_code == 403
    manager = api("assembly.view_assembly", "assembly.manager")
    assert manager.get("/api/v1/assemblies/assemblers/").status_code == 200


def test_painter_type_without_painter_refused(admin_api, order_factory):
    from djmoney.money import Money

    from order.painter.models import Painter, PainterType

    painter = Painter.objects.create(order=order_factory(), square=2)
    ptype = PainterType.objects.create(name="Глянец", price=Money(5, "USD"))
    resp = admin_api.patch(f"/api/v1/painters/{painter.pk}/", {"type": ptype.pk}, format="json")
    assert resp.status_code == 400
