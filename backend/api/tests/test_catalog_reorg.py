"""«Mahsulotlar»: moving cards between objects, splitting a card into its own object,
retiring an object, and the one-off «Спальня» clean-up migration."""

import importlib

import pytest
from django.apps import apps
from djmoney.money import Money

from metering.price.models import (
    Calculate,
    Inventory,
    InventoryInCalculate,
    InventoryType,
    ObjectType,
    Price,
    RoomType,
)

reorg = importlib.import_module("metering.price.migrations.0022_objecttype_archived_bedroom")


@pytest.fixture
def bedroom(db):
    sp = ObjectType.objects.create(name="Спальня", count_name="kv")
    bed = ObjectType.objects.create(name="Кровать", count_name="kv")
    cards = {
        n: InventoryType.objects.create(name=n, obj=sp, type=InventoryType.TYPE_COUNT)
        for n in [
            "Под ТВ",
            "Рабочий стол",
            "Дамская тумба",
            "Комод",
            "Банкетка",
            "Матрас",
            "Механизм",
            "Ручки",
        ]
    }
    komod = Inventory.objects.create(
        name="Комод ЛДСП", type=cards["Комод"], price=Money(150, "USD")
    )
    lift = Inventory.objects.create(
        name="Подъёмный механизм", type=cards["Механизм"], price=Money(80, "USD")
    )
    yotoq = RoomType.objects.get_or_create(name="Yotoqxona")[0]
    yotoq.object_types.add(sp, bed)
    allrooms = RoomType.objects.get_or_create(name="Mehmonxona")[0]  # empty = all furniture
    return dict(sp=sp, bed=bed, cards=cards, komod=komod, lift=lift, yotoq=yotoq, all=allrooms)


def test_migration_splits_bedroom(bedroom):
    sp, cards = bedroom["sp"], bedroom["cards"]
    price = Price.objects.create(desc="eski")
    calc = Calculate.objects.create(name="Спальня", price=price, obj=sp)
    InventoryInCalculate.objects.create(inventory=bedroom["komod"], calculate=calc, count=1)

    log = []
    reorg.reorganize(apps, out=log.append)

    for n in ["Под ТВ", "Рабочий стол", "Дамская тумба", "Комод", "Банкетка"]:
        obj = ObjectType.objects.get(name=n)
        cards[n].refresh_from_db()
        assert cards[n].obj == obj and not obj.archived
        assert bedroom["yotoq"].object_types.filter(pk=obj.pk).exists()
    for n in ["Матрас", "Механизм"]:
        cards[n].refresh_from_db()
        assert cards[n].obj == bedroom["bed"]
    # products and prices move with their card
    assert Inventory.objects.get(pk=bedroom["lift"].pk).type.obj == bedroom["bed"]
    # «Ручки» matched nothing: Спальня stays visible with it
    sp.refresh_from_db()
    assert not sp.archived and InventoryType.objects.filter(obj=sp).count() == 1
    assert bedroom["all"].object_types.count() == 0  # «all furniture» stays all
    assert any("Ручки" in x for x in log)

    # once the leftover card is gone, a re-run archives it (old calculation keeps it)
    cards["Ручки"].delete()
    reorg.reorganize(apps, out=log.append)
    sp.refresh_from_db()
    assert sp.archived and Calculate.objects.get(pk=calc.pk).obj == sp


def test_migration_deletes_unused_empty_bedroom_and_skips_without_one(db):
    reorg.reorganize(apps, out=lambda _: None)  # nothing to do
    sp = ObjectType.objects.create(name="Spalnya")
    InventoryType.objects.create(name="Kamod", obj=sp)
    reorg.reorganize(apps, out=lambda _: None)
    assert not ObjectType.objects.filter(pk=sp.pk).exists()
    assert InventoryType.objects.get(name="Kamod").obj.name == "Kamod"


def test_move_and_split_api(admin_api, bedroom):
    cards = bedroom["cards"]
    r = admin_api.post(
        f"/api/v1/inventory-types/{cards['Матрас'].pk}/move/",
        {"obj": bedroom["bed"].pk},
        format="json",
    )
    assert r.status_code == 200 and r.data["obj"] == bedroom["bed"].pk
    r = admin_api.post(f"/api/v1/inventory-types/{cards['Комод'].pk}/split/")
    assert r.status_code == 200 and r.data["name"] == "Комод"
    assert bedroom["yotoq"].object_types.filter(pk=r.data["id"]).exists()
    # a second split is refused
    r = admin_api.post(f"/api/v1/inventory-types/{cards['Комод'].pk}/split/")
    assert r.status_code == 400


def test_moving_needs_permission(api, bedroom):
    client = api("price.view_inventorytype")
    r = client.post(
        f"/api/v1/inventory-types/{bedroom['cards']['Матрас'].pk}/move/",
        {"obj": bedroom["bed"].pk},
        format="json",
    )
    assert r.status_code == 403


def test_retire_object(admin_api, bedroom):
    sp = bedroom["sp"]
    assert admin_api.delete(f"/api/v1/object-types/{sp.pk}/").status_code == 400  # has cards
    InventoryType.objects.filter(obj=sp).update(obj=bedroom["bed"])
    Calculate.objects.create(name="x", price=Price.objects.create(), obj=sp)
    r = admin_api.delete(f"/api/v1/object-types/{sp.pk}/")
    assert r.status_code == 200 and r.data["result"] == "archived"
    # archived: no new cards, no new furniture on it
    r = admin_api.post("/api/v1/inventory-types/", {"name": "x", "obj": sp.pk}, format="json")
    assert r.status_code == 400
    empty = ObjectType.objects.create(name="Bo'sh")
    assert admin_api.delete(f"/api/v1/object-types/{empty.pk}/").status_code == 204


def test_old_calculation_keeps_a_moved_card(admin_api, bedroom):
    sp, komod = bedroom["sp"], bedroom["komod"]
    price = Price.objects.create(desc="eski")
    calc = Calculate.objects.create(name="Спальня", price=price, obj=sp)
    InventoryInCalculate.objects.create(inventory=komod, calculate=calc, count=1)
    bedroom["cards"]["Ручки"].delete()
    reorg.reorganize(apps, out=lambda _: None)
    assert ObjectType.objects.get(pk=sp.pk).archived
    card = InventoryType.objects.get(pk=komod.type_id)
    r = admin_api.patch(
        f"/api/v1/prices/{price.pk}/calculations/{calc.pk}/",
        {
            "name": "Спальня",
            "count": 1,
            "object_type": sp.pk,
            "items": [{"inventory_type": card.pk, "inventory": komod.pk, "count": 2}],
        },
        format="json",
    )
    assert r.status_code == 200, r.data
    calc.refresh_from_db()
    assert float(calc.auto_amount) == 300
    # a new piece on the old object is refused
    r = admin_api.post(
        f"/api/v1/prices/{price.pk}/calculations/",
        {"name": "x", "count": 1, "object_type": sp.pk, "items": []},
        format="json",
    )
    assert r.status_code == 400


def test_object_managers_get_the_delete_permission(make_staff):
    from django.contrib.auth.models import Group, Permission

    grant = importlib.import_module("metering.price.migrations.0023_objecttype_delete_perm").grant
    change = Permission.objects.get(codename="change_objecttype", content_type__app_label="price")
    admins = Group.objects.create(name="Admin")
    admins.permissions.add(change)
    other = Group.objects.create(name="Sotuv")
    user = make_staff("price.add_objecttype")
    grant(apps, None)
    assert admins.permissions.filter(codename="delete_objecttype").exists()
    assert not other.permissions.exists()
    user = type(user).objects.get(pk=user.pk)
    assert user.has_perm("price.delete_objecttype")
