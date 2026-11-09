"""Every /api/v1/bot/warehouse/ route is keeper-only; bad bodies are 400, not 500."""

import pytest

from api.tests.botkit import bot_client  # noqa: F401
from api.tests.conftest import make_staff  # noqa: F401
from api.tests.test_bot_warehouse import TG, jpeg, keeper, media, up_file  # noqa: F401
from warehouse import services as W
from warehouse.models import ProductPhoto

pytestmark = pytest.mark.django_db

ROUTES = [
    ("get", "warehouse/meta/"),
    ("get", "warehouse/products/"),
    ("post", "warehouse/products/"),
    ("get", "warehouse/products/1/"),
    ("patch", "warehouse/products/1/"),
    ("post", "warehouse/products/1/photos/"),
    ("delete", "warehouse/photos/1/"),
    ("post", "warehouse/photos/1/cover/"),
    ("get", "warehouse/photos/1/file/"),
    ("post", "warehouse/photos/1/tg-file/"),
    ("get", "warehouse/movements/"),
    ("post", "warehouse/movements/"),
    ("post", "warehouse/movements/1/cancel/"),
    ("get", "warehouse/summary/"),
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_non_keeper_and_stranger_are_403_everywhere(bot_client, make_staff, method, path):  # noqa: F811
    other = make_staff()
    other.telegram_id = 777
    other.save(update_fields=["telegram_id"])
    for actor in (777, 999):
        r = getattr(bot_client, method)(path, actor=actor)
        assert r.status_code == 403, (method, path, actor, r.status_code)


def test_bad_bodies_are_400_not_500(bot_client, keeper):  # noqa: F811
    p = W.save_product(keeper, {"name": "X", "unit": "dona"})
    assert bot_client.post("warehouse/movements/", actor=TG, data={}).status_code == 400
    assert (
        bot_client.post(
            "warehouse/movements/", actor=TG, data={"product": p.pk, "kind": "zz", "quantity": "1"}
        ).status_code
        == 400
    )
    r = bot_client.post(
        "warehouse/movements/", actor=TG, data={"product": p.pk, "kind": "in", "quantity": "abc"}
    )
    assert r.status_code == 400
    r = bot_client.post(
        "warehouse/movements/", actor=TG, data={"product": p.pk, "kind": "in", "quantity": "1"}
    )
    assert r.status_code == 400 and r.data["field"] == "unit_price"
    assert bot_client.post("warehouse/products/", actor=TG, data={}).status_code == 400
    assert bot_client.get("warehouse/products/99999/", actor=TG).status_code == 404
    assert (
        bot_client.post(
            "warehouse/photos/99999/tg-file/", actor=TG, data={"file_id": "a"}
        ).status_code
        == 404
    )
    assert bot_client.post("warehouse/photos/1/tg-file/", actor=TG, data={}).status_code in (
        400,
        404,
    )
    assert bot_client.post("warehouse/movements/999999/cancel/", actor=TG).status_code == 404


def test_bot_upload_without_file_and_limits(bot_client, keeper):  # noqa: F811
    p = W.save_product(keeper, {"name": "X", "unit": "dona"})
    path = f"warehouse/products/{p.pk}/photos/"
    r = bot_client.call("POST", path, actor=TG, form={"tg_file_id": "A"})
    assert r.status_code == 400
    for _ in range(5):
        assert (
            bot_client.call("POST", path, actor=TG, files={"file": up_file(jpeg())}).status_code
            == 201
        )
    r = bot_client.call("POST", path, actor=TG, files={"file": up_file(jpeg())})
    assert r.status_code == 400 and r.data["field"] == "file"
    assert ProductPhoto.objects.filter(product=p).count() == 5


def test_tg_file_id_is_only_a_cache(bot_client, keeper):  # noqa: F811
    p = W.save_product(keeper, {"name": "X", "unit": "dona"})
    up = bot_client.call(
        "POST", f"warehouse/products/{p.pk}/photos/", actor=TG,
        files={"file": up_file(jpeg())}, form={"tg_file_id": "z" * 400},
    )  # fmt: skip
    ph = ProductPhoto.objects.get()
    assert up.status_code == 201 and len(ph.tg_file_id) == 255
    before = ph.image.name
    bot_client.post(f"warehouse/photos/{ph.pk}/tg-file/", actor=TG, data={"file_id": "new"})
    ph.refresh_from_db()
    assert ph.tg_file_id == "new" and ph.image.name == before
