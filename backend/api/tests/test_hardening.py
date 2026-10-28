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
        "/api/v1/invoices/?date_from=bad",
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


# --- uploads without an extension ("pdf (3)" from phones) ---------------------------


@pytest.fixture
def order_folder(db_client, default_factory):
    from filer.models import Folder

    from conftest import make_order

    order = make_order(db_client=db_client)
    order.folder = Folder.objects.create(name=f"Заказ-{order.pk}")
    order.save(update_fields=["folder"])
    return order.folder


def test_pdf_without_extension_gets_client_name_and_pdf(
    admin_api, order_folder, tmp_path, settings
):
    settings.MEDIA_ROOT = str(tmp_path)
    upload = SimpleUploadedFile("pdf (3)", b"%PDF-1.7 ...", content_type="application/octet-stream")
    resp = admin_api.post(
        f"/api/v1/folders/{order_folder.pk}/", {"file": upload}, format="multipart"
    )
    assert resp.status_code == 201, resp.data
    assert resp.data[0]["name"] == "Test Client.pdf"
    assert resp.data[0]["url"].endswith(".pdf")


def test_meaningful_name_kept_and_extension_added(admin_api, order_folder, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    upload = SimpleUploadedFile("Oshxona loyihasi", b"%PDF-1.4", content_type="application/pdf")
    resp = admin_api.post(
        f"/api/v1/folders/{order_folder.pk}/", {"file": upload}, format="multipart"
    )
    assert resp.data[0]["name"] == "Oshxona loyihasi.pdf"


def test_named_pdf_unchanged_and_unknown_type_refused(admin_api, order_folder, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    ok = SimpleUploadedFile("Shartnoma.PDF", b"%PDF-1.4", content_type="application/pdf")
    resp = admin_api.post(f"/api/v1/folders/{order_folder.pk}/", {"file": ok}, format="multipart")
    assert resp.status_code == 201, resp.data
    assert resp.data[0]["name"] == "Shartnoma.PDF"
    junk = SimpleUploadedFile(
        "noma'lum", b"\x00\x01binary", content_type="application/octet-stream"
    )
    resp = admin_api.post(f"/api/v1/folders/{order_folder.pk}/", {"file": junk}, format="multipart")
    assert resp.status_code == 400 and "aniqlab bo'lmadi" in resp.data["detail"]


@pytest.mark.parametrize(
    "name,content,ctype",
    [
        ("virus.exe", b"MZ\x90\x00", "text/plain"),  # real bad extension, whatever the type
        ("page", b"<html><script>x</script>", "application/pdf"),  # claims PDF, isn't
        ("pic", b"<svg onload=x>", "image/png"),  # claims PNG, isn't
        ("notes.html", b"%PDF-1.4", "application/pdf"),  # .html never, even with PDF bytes
    ],
)
def test_spoofed_or_dangerous_uploads_refused(
    admin_api, order_folder, tmp_path, settings, name, content, ctype
):
    settings.MEDIA_ROOT = str(tmp_path)
    upload = SimpleUploadedFile(name, content, content_type=ctype)
    resp = admin_api.post(
        f"/api/v1/folders/{order_folder.pk}/", {"file": upload}, format="multipart"
    )
    assert resp.status_code == 400, resp.data


def test_dotted_name_without_real_extension_and_control_chars(
    admin_api, order_folder, tmp_path, settings
):
    settings.MEDIA_ROOT = str(tmp_path)
    upload = SimpleUploadedFile(
        "scan 2024.05\r\n", b"%PDF-1.4", content_type="application/octet-stream"
    )
    resp = admin_api.post(
        f"/api/v1/folders/{order_folder.pk}/", {"file": upload}, format="multipart"
    )
    assert resp.status_code == 201, resp.data
    assert resp.data[0]["name"] == "scan 2024.05.pdf"


def test_old_extensionless_file_gets_download_name(admin_api, order_folder, tmp_path, settings):
    from filer.models import File

    settings.MEDIA_ROOT = str(tmp_path)
    File.objects.create(
        folder=order_folder,
        original_filename="pdf (3)",
        file=SimpleUploadedFile("pdf (3)", b"%PDF-1.4 old"),
    )
    files = admin_api.get(f"/api/v1/folders/{order_folder.pk}/").data["files"]
    assert files[0]["name"] == "pdf (3)"  # data untouched
    assert files[0]["download_name"] == "pdf (3).pdf"


def test_dotted_client_name_pdf_accepted(admin_api, order_folder, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    upload = SimpleUploadedFile(
        "Karimov.Smeta", b"%PDF-1.4", content_type="application/octet-stream"
    )
    resp = admin_api.post(
        f"/api/v1/folders/{order_folder.pk}/", {"file": upload}, format="multipart"
    )
    assert resp.status_code == 201, resp.data
    assert resp.data[0]["name"] == "Karimov.Smeta.pdf"


def _xlsx_bytes():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
    return buf.getvalue()


def test_extensionless_xlsx_gets_download_name_and_downloads(
    admin_api, order_folder, tmp_path, settings
):
    from filer.models import File

    settings.MEDIA_ROOT = str(tmp_path)
    f = File.objects.create(
        folder=order_folder, original_filename="xlsx", file=SimpleUploadedFile("xlsx", _xlsx_bytes())
    )
    files = admin_api.get(f"/api/v1/folders/{order_folder.pk}/").data["files"]
    assert files[0]["download_name"] == "xlsx.xlsx"
    resp = admin_api.get(f"/api/v1/files/{f.pk}/")
    assert resp.status_code == 200
    assert 'filename="xlsx.xlsx"' in resp["Content-Disposition"]
    assert resp["Content-Disposition"].startswith("attachment")
    assert b"".join(resp.streaming_content).startswith(b"PK")


def test_type_word_name_is_used_when_the_bytes_say_nothing(
    admin_api, order_folder, tmp_path, settings
):
    from filer.models import File

    settings.MEDIA_ROOT = str(tmp_path)
    File.objects.create(
        folder=order_folder, original_filename="docx (2)", file=SimpleUploadedFile("d", b"plain")
    )
    files = admin_api.get(f"/api/v1/folders/{order_folder.pk}/").data["files"]
    assert files[0]["download_name"] == "docx (2).docx"


def test_missing_file_download_is_a_410_not_a_redirect(admin_api, order_folder, tmp_path, settings):
    import os

    from filer.models import File

    settings.MEDIA_ROOT = str(tmp_path)
    f = File.objects.create(
        folder=order_folder, original_filename="a.pdf", file=SimpleUploadedFile("a.pdf", b"%PDF-1")
    )
    os.remove(f.file.path)
    resp = admin_api.get(f"/api/v1/files/{f.pk}/")
    assert resp.status_code == 410 and "topilmadi" in resp.data["detail"]
