"""Site API of the product pictures: permissions, validation answers, query count."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from PIL import Image
from rest_framework.test import APIClient

from api.tests.conftest import api, make_staff  # noqa: F401
from oauth.models import User
from warehouse import services as W
from warehouse.models import Product, ProductPhoto, WarehouseConfig

pytestmark = pytest.mark.django_db
URL = "/api/v1/warehouse/products"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def jpeg(size=(300, 200), exif_orientation=None):
    buf = io.BytesIO()
    img = Image.new("RGB", size, (10, 120, 200))
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


def f(content, name="a.jpg", ctype="image/jpeg"):
    return SimpleUploadedFile(name, content, content_type=ctype)


def client_for(user):
    c = APIClient()
    c.force_authenticate(User.objects.get(pk=user.pk))
    return c


@pytest.fixture
def keeper(make_staff):  # noqa: F811
    user = make_staff()
    W.assign_keeper(user)
    return user


@pytest.fixture
def kc(keeper):
    return client_for(keeper)


@pytest.fixture
def product(keeper):
    return W.save_product(keeper, {"name": "LDSP", "unit": "list"})


def upload(c, pid, content, **kw):
    return c.post(f"{URL}/{pid}/photos/", {"file": f(content, **kw)}, format="multipart")


def test_keeper_uploads_covers_and_deletes(kc, product):
    ids = []
    for _ in range(2):
        r = upload(kc, product.pk, jpeg())
        assert r.status_code == 201, r.data
        ids.append(r.data["photos"][-1]["id"])
    assert r.data["cover"]["id"] == ids[0]
    ph = r.data["photos"][0]
    assert set(ph) == {"id", "url", "thumb", "position", "width", "height"}
    assert ph["url"].endswith(".jpg") and ph["thumb"].endswith("_t.jpg") and ph["width"] == 300
    c = kc.post(f"{URL}/{product.pk}/photos/{ids[1]}/cover/")
    assert c.status_code == 200 and [p["id"] for p in c.data["photos"]] == [ids[1], ids[0]]
    d = kc.delete(f"{URL}/{product.pk}/photos/{ids[1]}/")
    assert d.status_code == 200 and [p["id"] for p in d.data["photos"]] == [ids[0]]
    assert d.data["cover"]["id"] == ids[0]
    assert kc.delete(f"{URL}/{product.pk}/photos/{ids[1]}/").status_code == 404


def test_photo_of_another_product_is_404(kc, keeper, product):
    other = W.save_product(keeper, {"name": "Boshqa", "unit": "dona"})
    pid = upload(kc, other.pk, jpeg()).data["photos"][0]["id"]
    assert kc.delete(f"{URL}/{product.pk}/photos/{pid}/").status_code == 404
    assert kc.post(f"{URL}/{product.pk}/photos/{pid}/cover/").status_code == 404
    assert ProductPhoto.objects.filter(pk=pid).exists()


def test_superuser_who_is_not_the_keeper_gets_400(api, product):  # noqa: F811
    admin = api(superuser=True)
    r = upload(admin, product.pk, jpeg())
    assert r.status_code == 400 and "omborchi" in r.data["detail"]
    assert not ProductPhoto.objects.exists()


def test_keeper_without_change_product_is_403(make_staff, product):  # noqa: F811
    user = make_staff("warehouse.view_product")
    cfg = WarehouseConfig.get()
    cfg.keeper = user
    cfg.save()
    c = client_for(user)
    assert upload(c, product.pk, jpeg()).status_code == 403
    assert c.delete(f"{URL}/{product.pk}/photos/1/").status_code == 403
    assert c.post(f"{URL}/{product.pk}/photos/1/cover/").status_code == 403
    assert not ProductPhoto.objects.exists()


def test_viewer_sees_pictures_but_cannot_edit(make_staff, kc, product):  # noqa: F811
    upload(kc, product.pk, jpeg())
    viewer = client_for(make_staff("warehouse.view_product"))
    r = viewer.get(f"{URL}/{product.pk}/")
    assert r.status_code == 200 and len(r.data["photos"]) == 1 and r.data["cover"]["id"]
    assert upload(viewer, product.pk, jpeg()).status_code == 403


def test_unauthenticated_is_401(product):
    assert (
        APIClient().post(f"{URL}/{product.pk}/photos/", {}, format="multipart").status_code == 401
    )


@pytest.mark.parametrize(
    "content",
    [b"plain text", b"\x00\x00\x00\x18ftypheic" + b"0" * 64, b"\xff\xd8\xff garbage"],
    ids=["garbage", "heic", "truncated-jpeg"],
)
def test_bad_files_are_400_on_field_file(kc, product, content):
    r = upload(kc, product.pk, content)
    assert r.status_code == 400 and r.data["field"] == "file"
    assert not ProductPhoto.objects.exists()


def test_empty_and_missing_file_are_400(kc, product):
    r = upload(kc, product.pk, b"")
    assert r.status_code == 400 and "file" in (r.data.get("field") or r.data)
    r = kc.post(f"{URL}/{product.pk}/photos/", {}, format="multipart")
    assert r.status_code == 400 and "file" in r.data


def test_oversize_is_400_on_field_file(kc, product):
    r = upload(kc, product.pk, b"\xff\xd8" + b"0" * (10 * 1024 * 1024))
    assert r.status_code == 400 and "file" in r.data
    assert not ProductPhoto.objects.exists()


def test_sixth_picture_is_400_on_field_file(kc, product):
    for _ in range(5):
        assert upload(kc, product.pk, jpeg()).status_code == 201
    r = upload(kc, product.pk, jpeg())
    assert r.status_code == 400 and r.data["field"] == "file" and "5" in r.data["detail"]
    assert product.photos.count() == 5


def test_exif_orientation_is_applied(kc, product):
    # 300x200 landscape flagged "rotate 90 cw" must be stored as 200x300 portrait
    r = upload(kc, product.pk, jpeg((300, 200), exif_orientation=6))
    assert r.status_code == 201
    ph = product.photos.get()
    assert (ph.width, ph.height) == (200, 300)
    with Image.open(ph.image.path) as im:
        assert im.size == (200, 300) and not im.getexif().get(0x0112)


def test_large_image_is_stored_at_most_1600(kc, product):
    upload(kc, product.pk, jpeg((3200, 1600)))
    ph = product.photos.get()
    assert (ph.width, ph.height) == (1600, 800)


def test_list_query_count_does_not_grow_with_photos(kc, keeper):
    def count():
        with CaptureQueriesContext(connection) as ctx:
            r = kc.get(f"{URL}/")
            assert r.status_code == 200
        return len(ctx), r

    products = [W.save_product(keeper, {"name": f"P{i}", "unit": "dona"}) for i in range(6)]
    base, _ = count()
    for p in products:
        for _ in range(3):
            W.add_product_photo(keeper, p, jpeg())
    many, r = count()
    assert Product.objects.count() == 6
    results = r.data["results"] if isinstance(r.data, dict) else r.data
    assert all(len(p["photos"]) == 3 and p["cover"] for p in results)
    assert many <= base + 1  # one extra prefetch query at most, never per row
