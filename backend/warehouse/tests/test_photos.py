import io

import pytest
from PIL import Image

from api.tests.conftest import make_staff  # noqa: F401
from core.exceptions import ServiceConflict, ServiceError
from warehouse import services as W
from warehouse.models import Product, ProductPhoto

pytestmark = pytest.mark.django_db


def img_bytes(size=(300, 200), fmt="JPEG", mode="RGB", color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, fmt)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def keeper(make_staff):  # noqa: F811
    user = make_staff()
    W.assign_keeper(user)
    return user


@pytest.fixture
def product(keeper):
    return W.save_product(keeper, {"name": "LDSP", "unit": "list"})


def test_normalize_shrinks_and_drops_alpha():
    main, thumb = W._normalize_image(img_bytes((4000, 2000), "PNG", "RGBA", (0, 0, 0, 0)))
    m, t = Image.open(io.BytesIO(main)), Image.open(io.BytesIO(thumb))
    assert m.format == "JPEG" and max(m.size) == 1600
    assert t.format == "JPEG" and max(t.size) == 400


@pytest.mark.parametrize("content", [b"", b"not an image", b"\x00\x00\x00\x18ftypheic" + b"0" * 40])
def test_normalize_rejects_garbage(content):
    with pytest.raises(ServiceError) as e:
        W._normalize_image(content)
    assert e.value.field == "file"


def test_normalize_rejects_gif():
    with pytest.raises(ServiceError):
        W._normalize_image(img_bytes(fmt="GIF", mode="P"))


def test_add_limit_cover_delete_and_files(product, keeper, django_capture_on_commit_callbacks):
    photos = [
        W.add_product_photo(keeper, product, img_bytes(), tg_file_id="x" * 300) for _ in range(5)
    ]
    assert [p.position for p in photos] == [0, 1, 2, 3, 4]
    assert len(photos[0].tg_file_id) == 255
    with pytest.raises(ServiceError) as e:
        W.add_product_photo(keeper, product, img_bytes())
    assert e.value.field == "file"
    W.set_product_cover(keeper, photos[3])
    order = list(product.photos.values_list("pk", flat=True))
    assert order[0] == photos[3].pk and sorted(p.position for p in product.photos.all()) == [
        0,
        1,
        2,
        3,
        4,
    ]
    victim = product.photos.first()
    names = [victim.image.name, victim.thumb.name]
    with django_capture_on_commit_callbacks(execute=True):
        W.delete_product_photo(keeper, victim)
    assert [p.position for p in product.photos.all()] == [0, 1, 2, 3]
    assert not any(W.default_storage.exists(n) for n in names)


def test_only_the_keeper_edits_photos(product, make_staff):  # noqa: F811
    with pytest.raises(ServiceError):
        W.add_product_photo(make_staff(), product, img_bytes())


def test_chiqim_without_price_uses_avg_cost(product, keeper):
    W.add_movement(keeper, product=product, kind="in", quantity=10, unit_price=1000)
    m = W.add_movement(keeper, product=product, kind="out", quantity=4)
    assert m.unit_price == 1000 and m.total == 4000
    with pytest.raises(ServiceError) as e:
        W.add_movement(keeper, product=product, kind="in", quantity=1)
    assert e.value.field == "unit_price"


def test_cancel_twice_is_a_conflict(product, keeper):
    m = W.add_movement(keeper, product=product, kind="in", quantity=1, unit_price=5)
    W.cancel_movement(keeper, m)
    with pytest.raises(ServiceConflict):
        W.cancel_movement(keeper, m)


def test_find_products_exact_code_first(keeper):
    a = W.save_product(keeper, {"name": "Petlya", "code": "P-1X", "unit": "dona"})
    b = W.save_product(keeper, {"name": "A P-1 maxsus", "code": "Z9", "unit": "dona"})
    c = W.save_product(keeper, {"name": "Yopiq", "code": "P-1", "unit": "dona", "is_active": False})
    names = [p.pk for p in W.find_products("p-1")]
    assert names == [b.pk, a.pk] and c.pk not in names
    assert c.pk in [p.pk for p in W.find_products("p-1", include_inactive=True)]


def test_delete_product_removes_photo_files(product, keeper, django_capture_on_commit_callbacks):
    ph = W.add_product_photo(keeper, product, img_bytes())
    name = ph.image.name
    with django_capture_on_commit_callbacks(execute=True):
        W.delete_product(keeper, product)
    assert not Product.objects.filter(pk=product.pk).exists()
    assert not ProductPhoto.objects.exists() and not W.default_storage.exists(name)


def test_mpo_and_broken_exif_are_handled(product, keeper):
    # a JPEG whose EXIF is garbage must be a clean 400-style refusal or a valid photo, never a crash
    buf = io.BytesIO()
    Image.new("RGB", (50, 50)).save(buf, "JPEG")
    raw = bytearray(buf.getvalue())
    raw[2:2] = b"\xff\xe1\x00\x0aExif\x00\x00\xff\xff"  # truncated EXIF segment
    try:
        W._normalize_image(bytes(raw))
    except ServiceError as e:
        assert e.field == "file"


def test_vanished_photo_is_not_found(product, keeper):
    from core.exceptions import ServiceNotFound

    ph = W.add_product_photo(keeper, product, img_bytes())
    ProductPhoto.objects.filter(pk=ph.pk).delete()
    with pytest.raises(ServiceNotFound):
        W.delete_product_photo(keeper, ph)
    with pytest.raises(ServiceNotFound):
        W.set_product_cover(keeper, ph)


def test_chiqim_default_price_overflow_guard(product, keeper):
    from decimal import Decimal

    W.add_movement(keeper, product=product, kind="in", quantity=1, unit_price=1000)
    Product.objects.filter(pk=product.pk).update(
        avg_cost=Decimal("9999999999999.00"), quantity=Decimal("999999999")
    )
    with pytest.raises(ServiceError) as e:
        W.add_movement(keeper, product=product, kind="out", quantity=999999)
    assert e.value.field == "quantity"
