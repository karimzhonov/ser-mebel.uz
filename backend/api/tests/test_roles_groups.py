"""Roles = groups: CRUD, section levels, members, default groups, routing."""

import importlib

import pytest
from django.apps import apps
from django.contrib.auth.models import Group

from oauth import access as A
from oauth.models import User

pytestmark = pytest.mark.django_db

DEFAULTS = [
    "Operator",
    "O'lcham oluvchi",
    "Dizayner",
    "Narxchi",
    "Menejer",
    "Bosh menejer",
    "Konstruktor",
    "Molyar",
    "Sborkachi",
    "Rover",
]


def perms_of(group):
    return {f"{p.content_type.app_label}.{p.codename}" for p in group.permissions.all()}


def test_default_groups_exist_with_the_flags():
    assert set(DEFAULTS) <= set(Group.objects.values_list("name", flat=True))
    assert "oauth.user_design" in perms_of(Group.objects.get(name="Dizayner"))
    assert "design.change_design" in perms_of(Group.objects.get(name="Dizayner"))
    assert "oauth.user_metering" in perms_of(Group.objects.get(name="O'lcham oluvchi"))
    assert "oauth.user_call_center" in perms_of(Group.objects.get(name="Operator"))
    assert "metering.present_to_client" in perms_of(Group.objects.get(name="Menejer"))
    boss = perms_of(Group.objects.get(name="Bosh menejer"))
    assert {"metering.manage_metering", "call_center.manage_invoice", "order.add_order"} <= boss
    assert "oauth.user_detailing" in perms_of(Group.objects.get(name="Konstruktor"))
    assert "oauth.user_assembly" in perms_of(Group.objects.get(name="Sborkachi"))


def test_default_groups_migration_is_idempotent_and_leaves_existing_alone():
    mod = importlib.import_module("oauth.migrations.0012_default_role_groups")
    custom = Group.objects.get(name="Dizayner")
    custom.permissions.clear()  # the owner changed it by hand
    before = Group.objects.count()
    mod.create_default_groups(apps, None)
    mod.create_default_groups(apps, None)
    assert Group.objects.count() == before
    assert custom.permissions.count() == 0  # never modified
    # a deleted default comes back, the others are not touched
    Group.objects.filter(name="Rover").delete()
    mod.create_default_groups(apps, None)
    assert "oauth.user_rover" in perms_of(Group.objects.get(name="Rover"))
    assert custom.permissions.count() == 0


def test_group_access_round_trip():
    g = Group.objects.create(name="Test rol")
    assert all(s["level"] == "none" for s in A.group_access(g)["sections"])
    out = A.set_group_access(g, {"designs": "edit", "design_designer": "view", "clients": "view"})
    by = {s["key"]: s for s in out["sections"]}
    assert by["designs"]["level"] == "edit" and by["clients"]["level"] == "view"
    assert by["design_designer"]["level"] == "view" and by["design_designer"]["is_flag"]
    assert "oauth.user_design" in perms_of(g)
    again = {s["key"]: s["level"] for s in A.group_access(g)["sections"]}
    assert again["designs"] == "edit" and again["meterings"] == "none"
    A.set_group_access(g, {"designs": "none"})
    assert "design.change_design" not in perms_of(g)
    with pytest.raises(Exception):
        A.set_group_access(g, {"nope": "view"})


def test_group_access_makes_members_staff():
    g = Group.objects.create(name="Yangi rol")
    u = User.objects.create_user(phone="+998901234500", password="x")
    assert not u.is_staff
    g.user_set.add(u)
    A.set_group_access(g, {"clients": "view"})
    u.refresh_from_db()
    assert u.is_staff
    g2 = Group.objects.create(name="Bo'sh rol")
    u2 = User.objects.create_user(phone="+998901234501", password="x")
    from oauth.services import add_group_member

    add_group_member(g2, u2)
    u2.refresh_from_db()
    assert not u2.is_staff  # nothing to log in for yet
    add_group_member(g, u2)
    u2.refresh_from_db()
    assert u2.is_staff


def test_groups_api_crud_access_members(admin_api, api, make_staff):
    r = admin_api.get("/api/v1/groups/")
    assert r.status_code == 200 and isinstance(r.data, list)
    assert {"id", "name", "member_count"} <= set(r.data[0])
    r = admin_api.post("/api/v1/groups/", {"name": "Yangi"}, format="json")
    assert r.status_code == 201 and r.data["name"] == "Yangi" and r.data["member_count"] == 0
    gid = r.data["id"]
    assert admin_api.post("/api/v1/groups/", {"name": "yangi"}, format="json").status_code == 400
    assert admin_api.post("/api/v1/groups/", {"name": " "}, format="json").status_code == 400
    r = admin_api.patch(f"/api/v1/groups/{gid}/", {"name": "Boshqa"}, format="json")
    assert r.status_code == 200 and r.data["name"] == "Boshqa"

    r = admin_api.post(
        f"/api/v1/groups/{gid}/access/",
        {"levels": {"clients": "edit", "metering_presenter": "view"}},
        format="json",
    )
    assert r.status_code == 200
    got = {
        s["key"]: s["level"]
        for s in admin_api.get(f"/api/v1/groups/{gid}/access/").data["sections"]
    }
    assert got["clients"] == "edit" and got["metering_presenter"] == "view"
    assert admin_api.post(f"/api/v1/groups/{gid}/access/", {}, format="json").status_code == 400

    user = make_staff(name="Bobur", telegram_id=555)
    r = admin_api.post(f"/api/v1/groups/{gid}/members/", {"add": [user.pk]}, format="json")
    assert r.status_code == 200
    assert [m["id"] for m in r.data] == [user.pk] and r.data[0]["telegram_id"] == 555
    assert admin_api.get("/api/v1/groups/").data[-1]["member_count"] >= 0
    # a role with people cannot be deleted
    r = admin_api.delete(f"/api/v1/groups/{gid}/")
    assert r.status_code == 400 and "nafar" in str(r.data)
    assert Group.objects.filter(pk=gid).exists()
    admin_api.post(f"/api/v1/groups/{gid}/members/", {"remove": [user.pk]}, format="json")
    assert admin_api.get(f"/api/v1/groups/{gid}/members/").data == []
    assert admin_api.delete(f"/api/v1/groups/{gid}/").status_code == 204

    plain = api("client.view_client")
    assert plain.get("/api/v1/groups/").status_code == 403
    assert plain.post("/api/v1/groups/", {"name": "x"}, format="json").status_code == 403


def test_pipeline_block_only_for_bosses(api, admin_api):
    assert (
        admin_api.get("/api/v1/dashboard/overview/").data["pipeline"]["counts"]["zamer_today"] == 0
    )
    boss = api("metering.manage_metering")
    assert boss.get("/api/v1/dashboard/overview/").data["pipeline"] is not None
    assert api("metering.view_metering").get("/api/v1/dashboard/overview/").data["pipeline"] is None


def test_keeper_cannot_be_managed_through_groups(admin_api, make_staff):
    from warehouse.services import KEEPER_GROUP, assign_keeper

    keeper = make_staff(name="Omborchi")
    assign_keeper(keeper)
    kg = Group.objects.get(name=KEEPER_GROUP)
    other = make_staff(name="Boshqa")
    for body in ({"add": [other.pk]}, {"remove": [keeper.pk]}):
        r = admin_api.post(f"/api/v1/groups/{kg.pk}/members/", body, format="json")
        assert r.status_code == 400 and "Ombor sahifasida" in str(r.data)
    # the keeper cannot be dropped into another role either
    g = Group.objects.create(name="Boshqa rol")
    r = admin_api.post(f"/api/v1/groups/{g.pk}/members/", {"add": [keeper.pk]}, format="json")
    assert r.status_code == 400
    assert (
        admin_api.patch(f"/api/v1/groups/{kg.pk}/", {"name": "X"}, format="json").status_code == 400
    )
    assert admin_api.delete(f"/api/v1/groups/{kg.pk}/").status_code == 400
    r = admin_api.post(
        f"/api/v1/groups/{kg.pk}/access/", {"levels": {"clients": "edit"}}, format="json"
    )
    assert r.status_code == 400
    rows = {x["name"]: x for x in admin_api.get("/api/v1/groups/").data}
    assert rows[KEEPER_GROUP]["locked"] is True and rows["Boshqa rol"]["locked"] is False


def test_members_post_validates_before_applying(admin_api, make_staff):
    g = Group.objects.create(name="Tekshiruv")
    u = make_staff(name="U")
    url = f"/api/v1/groups/{g.pk}/members/"
    for bad in (
        {"add": [u.pk], "remove": [True]},
        {"add": [u.pk], "remove": [999999]},
        {"add": ["1"]},
        {"add": [True]},
    ):
        assert admin_api.post(url, bad, format="json").status_code == 400
        assert g.user_set.count() == 0  # nothing was applied
    assert admin_api.post(url, {"add": [u.pk]}, format="json").status_code == 200
    assert g.user_set.count() == 1


def test_user_serializer_groups_make_staff():
    from api.serializers.users import UserSerializer

    g = Group.objects.get(name="Dizayner")
    s = UserSerializer(
        data={"phone": "+998901112233", "name": "N", "is_staff": False, "groups": [g.pk]}
    )
    assert s.is_valid(), s.errors
    u = s.save()
    assert u.is_staff
    empty = Group.objects.create(name="Bo'sh2")
    u2 = User.objects.create_user(phone="+998901112244", password="x")
    s = UserSerializer(u2, data={"groups": [empty.pk]}, partial=True)
    assert s.is_valid() and not s.save().is_staff
    s = UserSerializer(u2, data={"groups": [g.pk]}, partial=True)
    assert s.is_valid() and s.save().is_staff


def test_default_groups_migration_matches_names_case_insensitively():
    mod = importlib.import_module("oauth.migrations.0012_default_role_groups")
    Group.objects.filter(name="Rover").delete()
    Group.objects.create(name="rover")
    before = Group.objects.count()
    mod.create_default_groups(apps, None)
    assert Group.objects.count() == before


def test_assignees_hints_when_pools_empty(admin_api):

    Group.objects.filter(name__in=["Dizayner", "Narxchi"]).delete()
    r = admin_api.get("/api/v1/meterings/assignees/")
    assert r.status_code == 200
    assert "«Dizayner»" in r.data["designer_hint"] and "«Narxchi»" in r.data["pricer_hint"]
