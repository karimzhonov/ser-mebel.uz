"""Old groups -> default lavozims: plan, preview, merge (nobody loses a right)."""

import pytest
from django.contrib.auth.models import Group, Permission

from oauth.services import merge_plan

pytestmark = pytest.mark.django_db


def perm(key):
    app, code = key.split(".")
    return Permission.objects.get(content_type__app_label=app, codename=code)


def old(name, *perms):
    g = Group.objects.create(name=name)
    g.permissions.set([perm(p) for p in perms])
    return g


def plan():
    return {i["group"]["name"]: i for i in merge_plan()["items"]}


def test_plan_suggestions_cyrillic_and_latin():
    names = {
        "Замерщик": "O'lcham oluvchi",
        "zamerchi": "O'lcham oluvchi",
        "Дизайнер": "Dizayner",
        "Моляр": "Molyar",
        "Маляр ": "Molyar",
        "Сборка / Установка": "Sborkachi",
        "Детали": "Konstruktor",
        "Ровер": "Rover",
        "Call-center": "Operator",
        "Цены": "Menejer",  # the price is the managers' job
        "Менеджер": "Menejer",
        "Производство Manager": "Bosh menejer",
    }
    for n in names:
        Group.objects.create(name=n)
    got = plan()
    for n, target in names.items():
        assert got[n.strip() if n.strip() in got else n]["suggested"]["name"] == target, n
        assert got[n.strip() if n.strip() in got else n]["action"] == "merge"


def test_plan_filer_personal_unknown_and_exclusions():
    from warehouse.services import KEEPER_GROUP

    Group.objects.create(name="Filer")
    Group.objects.create(name="Nomalum")
    Group.objects.create(name=KEEPER_GROUP)
    got = plan()
    assert (
        got["Filer"]["suggested"] is None
        and got["Filer"]["action"] == "to_personal"
        and got["Filer"]["to_personal"] is True
    )
    assert got["Nomalum"]["suggested"] is None and got["Nomalum"]["action"] == "choose"
    assert KEEPER_GROUP not in got
    assert "Dizayner" not in got and "Operator" not in got
    assert {"Dizayner", "Rover"} <= {t["name"] for t in merge_plan()["targets"]}


def test_plan_lowercase_operator_is_a_rename():
    Group.objects.filter(name="Operator").delete()
    g = Group.objects.create(name="operator")
    item = plan()["operator"]
    assert item["action"] == "rename"
    assert (
        item["rename_to"] == "Operator"
        and item["suggested"] is None
        and item["group"]["id"] == g.pk
    )


def test_plan_requires_superuser(api, admin_api):
    assert admin_api.get("/api/v1/groups/merge-plan/").status_code == 200
    assert api("oauth.view_user").get("/api/v1/groups/merge-plan/").status_code == 403


def test_merge_into_target_keeps_everyones_rights(admin_api, make_staff):
    src = old("Дизайнер", "design.view_design", "filer.view_file", "oauth.user_design")
    target = Group.objects.get(name="Dizayner")
    m1 = make_staff()
    m2 = make_staff()
    m1.is_staff = m2.is_staff = False
    m1.save()
    m2.save()
    src.user_set.add(m1, m2)
    keys = ["design.view_design", "filer.view_file", "oauth.user_design"]
    from oauth.models import User

    before = {
        u.pk: [u.has_perm(k) for k in keys] for u in User.objects.filter(pk__in=[m1.pk, m2.pk])
    }
    r = admin_api.get(f"/api/v1/groups/{src.pk}/merge-preview/?target={target.pk}")
    assert r.status_code == 200
    assert {m["id"] for m in r.json()["members"]} == {m1.pk, m2.pk}
    assert r.json()["target_member_count"] == target.user_set.count()
    r = admin_api.post(f"/api/v1/groups/{src.pk}/merge-into/", {"target": target.pk}, format="json")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["moved_members"] == 2 and body["deleted"] == "Дизайнер"
    assert isinstance(body["added_permissions"], list)
    assert not Group.objects.filter(pk=src.pk).exists()
    for u in User.objects.filter(pk__in=[m1.pk, m2.pk]):
        assert u.is_staff
        assert target in u.groups.all()
        assert [u.has_perm(k) for k in keys] == before[u.pk]
        assert all(before[u.pk])


def test_preview_lists_only_what_target_lacks(admin_api):
    src = old("Zamer eski", "design.view_design", "metering.view_metering", "oauth.user_design")
    target = Group.objects.get(name="Dizayner")  # already has design + user_design
    r = admin_api.get(f"/api/v1/groups/{src.pk}/merge-preview/?target={target.pk}").json()
    assert r["add_to_target"] == [] or all("design" not in x["key"] for x in r["add_to_target"])
    target.permissions.remove(perm("metering.view_metering"))
    r = admin_api.get(f"/api/v1/groups/{src.pk}/merge-preview/?target={target.pk}").json()
    assert r["add_to_target"]
    assert all({"key", "label"} <= set(x) for x in r["add_to_target"])


def test_merge_to_personal(admin_api, make_staff):
    from oauth.models import User

    src = old("Filer", "filer.view_file", "filer.add_file")
    u = make_staff()
    u.is_staff = False
    u.save()
    src.user_set.add(u)
    r = admin_api.post(f"/api/v1/groups/{src.pk}/merge-into/", {"to_personal": True}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["added_permissions"] == ["filer.add_file", "filer.view_file"]
    assert not Group.objects.filter(pk=src.pk).exists()
    u = User.objects.get(pk=u.pk)
    assert u.is_staff and u.has_perm("filer.view_file") and u.has_perm("filer.add_file")
    assert u.user_permissions.count() == 2


def test_merge_refused_for_keeper_and_self(admin_api):
    from warehouse.services import KEEPER_GROUP

    keeper = Group.objects.create(name=KEEPER_GROUP)
    target = Group.objects.get(name="Dizayner")
    assert (
        admin_api.post(
            f"/api/v1/groups/{keeper.pk}/merge-into/", {"target": target.pk}, format="json"
        ).status_code
        == 400
    )
    assert (
        admin_api.post(
            f"/api/v1/groups/{keeper.pk}/merge-into/", {"to_personal": True}, format="json"
        ).status_code
        == 400
    )
    assert (
        admin_api.post(
            f"/api/v1/groups/{target.pk}/merge-into/", {"target": target.pk}, format="json"
        ).status_code
        == 400
    )
    assert Group.objects.filter(pk=keeper.pk).exists()
    # keeper as a target is refused too
    src = old("X")
    assert (
        admin_api.post(
            f"/api/v1/groups/{src.pk}/merge-into/", {"target": keeper.pk}, format="json"
        ).status_code
        == 400
    )
    assert (
        admin_api.post(f"/api/v1/groups/{src.pk}/merge-into/", {}, format="json").status_code == 400
    )


def test_delete_message_says_lavozim(admin_api, make_staff):
    g = Group.objects.create(name="Tmp")
    g.user_set.add(make_staff())
    r = admin_api.delete(f"/api/v1/groups/{g.pk}/")
    assert r.status_code == 400 and "Lavozimda 1 nafar" in r.content.decode()


def test_empty_source_into_a_target_with_rights_makes_members_staff(db):
    from django.contrib.auth.models import Group, Permission

    from oauth.models import User
    from oauth.services import merge_group

    src = Group.objects.create(name="Eski bo'sh")
    dst = Group.objects.create(name="Yangi lavozim")
    dst.permissions.add(Permission.objects.get(codename="view_metering"))
    u = User.objects.create_user(phone="+998901119988", password="x")
    u.is_staff = False
    u.save()
    src.user_set.add(u)
    merge_group(src, dst)
    u.refresh_from_db()
    assert u.is_staff and dst.user_set.filter(pk=u.pk).exists()


def test_merge_all_applies_every_suggestion(api, admin_api, make_staff):
    from oauth.models import User

    src = old("Дизайнер", "design.view_design", "oauth.user_design")
    u = make_staff()
    src.user_set.add(u)
    old("Filer", "filer.view_file")
    Group.objects.create(name="Nomalum")
    assert api("oauth.view_user").post("/api/v1/groups/merge-all/").status_code == 403
    r = admin_api.post("/api/v1/groups/merge-all/", {}, format="json")
    assert r.status_code == 200, r.content
    done = {d["group"]: d for d in r.json()["done"]}
    assert done["Дизайнер"]["to"] == "Dizayner" and done["Filer"]["action"] == "to_personal"
    assert "Nomalum" in [s["group"] for s in r.json()["skipped"]]
    assert not Group.objects.filter(name__in=["Дизайнер", "Filer"]).exists()
    assert Group.objects.filter(name="Nomalum").exists()
    assert Group.objects.get(name="Dizayner") in User.objects.get(pk=u.pk).groups.all()
    left = {i["group"]["name"] for i in merge_plan()["items"]}
    assert "Nomalum" in left and not {"Дизайнер", "Filer"} & left



def test_old_call_centre_group_does_not_give_the_operator_zamer_editing(admin_api, make_staff):
    """Owner's rule: the operator only views zamers — merging an old group with the
    editing rights into «Operator» must not bring them back."""
    from oauth.models import User

    edit = ["metering.change_metering", "metering.delete_metering", "metering.change_status"]
    src = old("Оператор", "metering.view_metering", "metering.add_metering", *edit)
    u = make_staff(*edit)  # the old per-person setup
    src.user_set.add(u)
    target = Group.objects.get(name="Operator")
    r = admin_api.get(f"/api/v1/groups/{src.pk}/merge-preview/?target={target.pk}").json()
    assert not any("O'lchovlar — o'zgartirish" == x["label"] for x in r["add_to_target"])
    r = admin_api.post(f"/api/v1/groups/{src.pk}/merge-into/", {"target": target.pk}, format="json")
    assert r.status_code == 200, r.content
    have = {f"{p.content_type.app_label}.{p.codename}" for p in target.permissions.all()}
    assert not set(edit) & have and "metering.add_metering" in have
    u = User.objects.get(pk=u.pk)
    assert u.has_perm("metering.add_metering") and not any(u.has_perm(p) for p in edit)
