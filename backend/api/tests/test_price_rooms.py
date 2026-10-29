"""Price calculation by rooms: rooms → furniture, the «Excel» sheet, the offer PDF."""

import io

import pytest
from djmoney.money import Money
from openpyxl import load_workbook
from PIL import Image

from metering.price.models import Calculate, Inventory, InventoryType, ObjectType, Price, RoomType


@pytest.fixture
def catalog(db):
    kitchen = ObjectType.objects.create(name="Кухня", count_name="pog")
    wardrobe = ObjectType.objects.create(name="Шкаф", count_name="kv")
    facade = InventoryType.objects.create(
        name="Фасад материал", obj=kitchen, type=InventoryType.TYPE_KV
    )
    mech = InventoryType.objects.create(name="Механизм", obj=kitchen, type=InventoryType.TYPE_COUNT)
    return {
        "kitchen": kitchen,
        "wardrobe": wardrobe,
        "facade": facade,
        "mech": mech,
        "mdf": Inventory.objects.create(name="МДФ краш", type=facade, price=Money(300, "USD")),
        "blum": Inventory.objects.create(name="BLUM", type=mech, price=Money(10, "USD")),
        "oshxona": RoomType.objects.create(name="Oshxona", icon="🍳"),
        "yotoq": RoomType.objects.create(name="Yotoqxona", icon="🛏"),
    }


@pytest.fixture
def price(db):
    return Price.objects.create(metering=None, desc="Zilola opa")


def url(price, tail=""):
    return f"/api/v1/prices/{price.pk}/{tail}"


def add_kitchen(api_client, price, room_id, catalog, count=4.0):
    return api_client.post(
        url(price, "calculations/"),
        {
            "name": "Кухня",
            "count": count,
            "object_type": catalog["kitchen"].pk,
            "room": room_id,
            "note": "Подсветка",
            "items": [
                {"inventory_type": catalog["facade"].pk, "inventory": catalog["mdf"].pk},
                {"inventory_type": catalog["mech"].pk, "inventory": catalog["blum"].pk, "count": 5},
            ],
        },
        format="json",
    )


def test_rooms_are_numbered_and_hold_furniture(admin_api, price, catalog):
    r = admin_api.post(url(price, "rooms/"), {"room_type": catalog["yotoq"].pk}, format="json")
    assert r.status_code == 200, r.data
    r = admin_api.post(url(price, "rooms/"), {"room_type": catalog["yotoq"].pk}, format="json")
    r = admin_api.post(url(price, "rooms/"), {"room_type": catalog["oshxona"].pk}, format="json")
    names = [room["name"] for room in r.data["rooms"]]
    assert names == ["Yotoqxona", "Yotoqxona 2", "Oshxona"]

    kitchen_room = r.data["rooms"][2]["id"]
    r = add_kitchen(admin_api, price, kitchen_room, catalog)
    assert r.status_code == 200, r.data
    calc = r.data["calculations"][0]
    assert calc["room"] == kitchen_room and calc["note"] == "Подсветка"
    # 4 п.м. × 300 + 5 × 10
    assert r.data["price"]["amount"] == 1250

    sheet = r.data["sheet"]
    room = next(x for x in sheet["rooms"] if x["id"] == kitchen_room)
    item = room["items"][0]
    assert item["count_text"] == "4 п.м."
    assert {"label": "Фасад материал", "value": "МДФ краш"} in item["params"]
    assert {"label": "Механизм", "value": "BLUM × 5"} in item["params"]
    assert room["total"] == 1250 and sheet["total"] == 1250
    assert sheet["client"] == "Zilola opa"


def test_room_type_limits_furniture(admin_api, price, catalog):
    catalog["yotoq"].object_types.set([catalog["wardrobe"]])
    r = admin_api.post(url(price, "rooms/"), {"room_type": catalog["yotoq"].pk}, format="json")
    r = add_kitchen(admin_api, price, r.data["rooms"][0]["id"], catalog)
    assert r.status_code == 400
    assert "mos emas" in r.data["detail"]


def test_room_of_another_price_is_refused(admin_api, price, catalog):
    other = Price.objects.create(metering=None)
    r = admin_api.post(url(other, "rooms/"), {"room_type": catalog["oshxona"].pk}, format="json")
    r = add_kitchen(admin_api, price, r.data["rooms"][0]["id"], catalog)
    assert r.status_code == 404


def test_deleting_a_room_removes_its_furniture_and_total(admin_api, price, catalog):
    r = admin_api.post(url(price, "rooms/"), {"room_type": catalog["oshxona"].pk}, format="json")
    room_id = r.data["rooms"][0]["id"]
    add_kitchen(admin_api, price, room_id, catalog)
    r = admin_api.delete(url(price, f"rooms/{room_id}/"))
    assert r.status_code == 200
    assert r.data["rooms"] == [] and r.data["calculations"] == []
    assert r.data["price"]["amount"] == 0
    assert not Calculate.objects.filter(price=price).exists()


def test_rename_and_reorder_rooms(admin_api, price, catalog):
    admin_api.post(url(price, "rooms/"), {"room_type": catalog["oshxona"].pk}, format="json")
    r = admin_api.post(url(price, "rooms/"), {"room_type": catalog["yotoq"].pk}, format="json")
    a, b = [x["id"] for x in r.data["rooms"]]
    r = admin_api.patch(url(price, f"rooms/{b}/"), {"name": "Master-spalnya"}, format="json")
    assert r.data["rooms"][1]["name"] == "Master-spalnya"
    r = admin_api.post(url(price, "rooms/reorder/"), {"ids": [b, a]}, format="json")
    assert [x["id"] for x in r.data["rooms"]] == [b, a]
    assert (
        admin_api.post(url(price, "rooms/reorder/"), {"ids": [b]}, format="json").status_code == 400
    )


def test_old_calculations_without_room_show_as_other(admin_api, price, catalog):
    Calculate.objects.create(
        name="Eski", price=price, obj=catalog["kitchen"], count=1, amount=Money(100, "USD")
    )
    sheet = admin_api.get(url(price)).data["sheet"]
    assert sheet["rooms"][-1]["name"] == "Boshqa"
    assert sheet["total"] == 100


def test_viewer_cannot_edit_rooms(api, price, catalog):
    client = api("price.view_price")
    r = client.post(url(price, "rooms/"), {"room_type": catalog["oshxona"].pk}, format="json")
    assert r.status_code == 403
    assert client.get("/api/v1/room-types/").status_code == 200


def test_excel_and_pdf(admin_api, price, catalog, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    r = admin_api.post(url(price, "rooms/"), {"room_type": catalog["oshxona"].pk}, format="json")
    room_id = r.data["rooms"][0]["id"]
    add_kitchen(admin_api, price, room_id, catalog)

    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "teal").save(buf, "PNG")
    buf.seek(0)
    buf.name = "render.png"
    r = admin_api.post(url(price, f"rooms/{room_id}/images/"), {"file": buf}, format="multipart")
    assert r.status_code == 200, r.data
    assert len(r.data["rooms"][0]["images"]) == 1

    xlsx = admin_api.get(url(price, "excel/"))
    assert xlsx.status_code == 200
    flat = [
        str(c)
        for row in load_workbook(io.BytesIO(xlsx.content)).active.iter_rows(values_only=True)
        for c in row
        if c is not None
    ]
    assert "🍳 Oshxona" in flat and "МДФ краш" in flat and "Итого" in flat

    pdf = admin_api.get(url(price, "pdf/"))
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    image_id = r.data["rooms"][0]["images"][0]["id"]
    r = admin_api.delete(url(price, f"rooms/{room_id}/images/{image_id}/"))
    assert r.data["rooms"][0]["images"] == []


def test_non_image_upload_is_refused(admin_api, price, catalog, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    r = admin_api.post(url(price, "rooms/"), {"room_type": catalog["oshxona"].pk}, format="json")
    room_id = r.data["rooms"][0]["id"]
    buf = io.BytesIO(b"%PDF-1.4 fake")
    buf.name = "doc.pdf"
    r = admin_api.post(url(price, f"rooms/{room_id}/images/"), {"file": buf}, format="multipart")
    assert r.status_code == 400


def test_offer_title_and_variant_are_editable(admin_api, price):
    r = admin_api.patch(
        url(price), {"client_title": "Зилола опа", "variant": "Премиум"}, format="json"
    )
    assert r.status_code == 200
    assert r.data["sheet"]["client"] == "Зилола опа"
    assert r.data["sheet"]["variant"] == "Премиум"


def test_calculation_delete_works_but_price_delete_does_not(admin_api, price, catalog):
    r = admin_api.post(url(price, "rooms/"), {"room_type": catalog["oshxona"].pk}, format="json")
    r = add_kitchen(admin_api, price, r.data["rooms"][0]["id"], catalog)
    calc_id = r.data["calculations"][0]["id"]
    r = admin_api.delete(url(price, f"calculations/{calc_id}/"))
    assert r.status_code == 200 and r.data["calculations"] == []
    assert admin_api.delete(url(price)).status_code == 405
    assert Price.objects.filter(pk=price.pk).exists()
