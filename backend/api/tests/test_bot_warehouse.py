import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from api.tests.botkit import bot_client, load_fixture  # noqa: F401
from api.tests.conftest import api, make_staff  # noqa: F401
from warehouse import services as W

pytestmark = pytest.mark.django_db
TG = 5550001


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def keeper(make_staff):  # noqa: F811
    user = make_staff()
    user.telegram_id = TG
    user.save(update_fields=["telegram_id"])
    W.assign_keeper(user)
    return user


def jpeg(size=(800, 600)):
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


def up_file(content):
    return SimpleUploadedFile("a.jpg", content, content_type="image/jpeg")


def keys(d):
    return set(d)


def test_not_keeper_is_403(bot_client, make_staff):  # noqa: F811
    other = make_staff()
    other.telegram_id = 777
    other.save(update_fields=["telegram_id"])
    r = bot_client.get("warehouse/meta/", actor=777)
    assert r.status_code == 403 and r.data["detail"] == "Ombor faqat omborchi uchun."
    assert bot_client.get("warehouse/meta/", actor=999).status_code == 403


def test_whoami_flag(bot_client, keeper):  # noqa: F811
    r = bot_client.post("whoami/", actor=TG, data={"user": {"id": TG}})
    assert r.data["warehouse"] == {"is_keeper": True}


def test_full_flow_matches_fixtures(bot_client, keeper):  # noqa: F811
    r = bot_client.post(
        "warehouse/products/", actor=TG, data={"name": "LDSP oq", "unit": "list", "code": "LD-1"}
    )
    assert r.status_code == 201, r.data
    pid = r.data["product"]["id"]
    assert keys(r.data["product"]) == keys(
        load_fixture("misc.wh_product_detail_response.json")["product"]
    )
    assert (
        bot_client.post("warehouse/products/", actor=TG, data={"name": "x", "unit": "zz"}).data[
            "field"
        ]
        == "unit"
    )

    up = bot_client.call(
        "POST",
        f"warehouse/products/{pid}/photos/",
        actor=TG,
        files={"file": up_file(jpeg())},
        form={"tg_file_id": "AG1"},
    )
    assert up.status_code == 201, up.data
    ph = up.data["photo"]
    assert keys(ph) == keys(load_fixture("dto.wh_photo.1.json")) and ph["tg_file_id"] == "AG1"
    assert up.data["product"]["cover"]["id"] == ph["id"] and up.data["product"]["photos_count"] == 1
    bad = bot_client.call(
        "POST", f"warehouse/products/{pid}/photos/", actor=TG, files={"file": up_file(b"nope")}
    )
    assert bad.status_code == 400 and bad.data["field"] == "file"
    raw = bot_client.get(f"warehouse/photos/{ph['id']}/file/", actor=TG)
    assert raw.status_code == 200 and raw["Content-Type"] == "image/jpeg"
    assert (
        bot_client.post(
            f"warehouse/photos/{ph['id']}/tg-file/", actor=TG, data={"file_id": "AG2"}
        ).status_code
        == 204
    )

    mv = bot_client.post(
        "warehouse/movements/",
        actor=TG,
        data={
            "product": pid,
            "kind": "in",
            "quantity": "12.5",
            "unit_price": "1000",
            "counterparty": "Kron",
        },
    )
    assert mv.status_code == 201, mv.data
    assert keys(mv.data["movement"]) == keys(load_fixture("dto.wh_movement.1.json"))
    assert keys(mv.data["product"]) == keys(load_fixture("dto.wh_product.1.json")) | {"photos"}
    out = bot_client.post(
        "warehouse/movements/", actor=TG, data={"product": pid, "kind": "out", "quantity": "2"}
    )
    assert out.status_code == 201 and out.data["movement"]["unit_price"] == "1000.00"
    over = bot_client.post(
        "warehouse/movements/", actor=TG, data={"product": pid, "kind": "out", "quantity": "99"}
    )
    assert over.status_code == 400 and over.data["field"] == "quantity"

    detail = bot_client.get(f"warehouse/products/{pid}/", actor=TG)
    assert keys(detail.data) == keys(load_fixture("misc.wh_product_detail_response.json"))
    assert detail.data["last_in"]["counterparty"] == "Kron" and len(detail.data["recent"]) == 2

    n = out.data["movement"]["number"]
    assert bot_client.post(f"warehouse/movements/{n}/cancel/", actor=TG).status_code == 200
    assert bot_client.post(f"warehouse/movements/{n}/cancel/", actor=TG).status_code == 409
    lst = bot_client.get(f"warehouse/movements/?product={pid}", actor=TG)
    assert lst.data["total"] == 2 and lst.data["items"][0]["is_cancelled"] is True

    s = bot_client.get("warehouse/summary/?period=week", actor=TG)
    assert keys(s.data) == keys(load_fixture("misc.wh_summary_response.json"))
    assert bot_client.get("warehouse/summary/?period=zzz", actor=TG).status_code == 400

    meta = bot_client.get("warehouse/meta/", actor=TG)
    assert meta.data["max_photos"] == 5 and meta.data["categories"] == []


def test_products_paging_and_photo_ops(bot_client, keeper):  # noqa: F811
    for i in range(10):
        W.save_product(keeper, {"name": f"P{i:02d}", "unit": "dona"})
    r = bot_client.get("warehouse/products/?page=2", actor=TG)
    assert (r.data["page"], r.data["pages"], r.data["total"], len(r.data["items"])) == (2, 2, 10, 2)
    pid = r.data["items"][0]["id"]
    ids = []
    for _ in range(2):
        up = bot_client.call(
            "POST", f"warehouse/products/{pid}/photos/", actor=TG, files={"file": up_file(jpeg())}
        )
        ids.append(up.data["photo"]["id"])
    c = bot_client.post(f"warehouse/photos/{ids[1]}/cover/", actor=TG)
    assert [p["id"] for p in c.data["product"]["photos"]] == [ids[1], ids[0]]
    d = bot_client.delete(f"warehouse/photos/{ids[1]}/", actor=TG)
    assert d.data["product"]["photos_count"] == 1 and d.data["product"]["cover"]["id"] == ids[0]
    assert bot_client.delete(f"warehouse/photos/{ids[1]}/", actor=TG).status_code == 404
