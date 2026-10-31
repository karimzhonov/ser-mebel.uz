"""«Tizim → Xodimlar → Huquqlar»: section levels none / view / edit."""

import pytest
from django.contrib.auth.models import Group, Permission

from oauth.access import SECTIONS


def levels(client, user):
    r = client.get(f"/api/v1/users/{user.pk}/access/")
    assert r.status_code == 200
    return {s["key"]: s for s in r.data["sections"]}


def put(client, user, data):
    return client.post(f"/api/v1/users/{user.pk}/access/", {"levels": data}, format="json")


def fresh(user):
    return type(user).objects.get(pk=user.pk)


def test_view_and_edit_levels(admin_api, make_staff):
    u = make_staff()
    assert levels(admin_api, u)["hr_attendance"]["level"] == "none"
    r = put(admin_api, u, {"hr_attendance": "view", "warehouse": "view"})
    assert r.status_code == 200, r.data
    u = fresh(u)
    assert u.has_perm("hr.view_attendance") and u.has_perm("hr.view_employee")
    assert not u.has_perm("hr.change_attendance")
    assert u.has_perm("warehouse.view_movement") and not u.has_perm("warehouse.add_movement")
    put(admin_api, u, {"hr_attendance": "edit"})
    u = fresh(u)
    assert u.has_perm("hr.change_attendance") and u.has_perm("hr.add_leave")
    assert levels(admin_api, u)["hr_attendance"]["level"] == "edit"
    put(admin_api, u, {"hr_attendance": "none"})
    u = fresh(u)
    assert not u.has_perm("hr.view_attendance")
    assert u.has_perm("warehouse.view_product")  # untouched section kept


def test_shared_read_survives(admin_api, make_staff):
    u = make_staff()
    put(admin_api, u, {"prices": "edit", "catalog": "view"})
    put(admin_api, u, {"catalog": "none"})
    u = fresh(u)
    # «Narx hisoblash» still needs to read the catalog
    assert u.has_perm("price.view_inventorytype") and u.has_perm("price.change_price")
    assert not u.has_perm("price.add_inventorytype")


def test_single_perm_sections_and_view_only(admin_api, make_staff):
    u = make_staff()
    put(admin_api, u, {"order_price": "view", "finance_all": "view"})
    u = fresh(u)
    assert u.has_perm("order.view_order_price") and u.has_perm("accounting.view_all_operations")
    assert put(admin_api, u, {"warehouse": "edit"}).status_code == 400
    assert put(admin_api, u, {"nope": "view"}).status_code == 400


def test_groups_reported_not_changed(admin_api, make_staff):
    g = Group.objects.create(name="HR")
    g.permissions.add(
        *Permission.objects.filter(content_type__app_label="hr", codename__startswith="view_")
    )
    u = make_staff()
    u.groups.add(g)
    s = levels(admin_api, u)["hr_attendance"]
    assert s["from_groups"] == "view" and s["level"] == "none"
    put(admin_api, u, {"hr_attendance": "none"})
    assert fresh(u).has_perm("hr.view_attendance")  # still from the group


def test_staff_flag_and_guards(admin_api, api, make_staff):
    u = make_staff()
    type(u).objects.filter(pk=u.pk).update(is_staff=False)
    put(admin_api, u, {"clients": "view"})
    assert fresh(u).is_staff
    boss = make_staff(superuser=True)
    assert put(admin_api, boss, {"clients": "view"}).status_code == 400
    # only superusers manage access
    other = api("oauth.view_user")
    assert other.get(f"/api/v1/users/{u.pk}/access/").status_code == 403


@pytest.mark.django_db
def test_every_section_permission_exists():
    from oauth.access import _edit, _view

    have = {
        f"{a}.{c}" for a, c in Permission.objects.values_list("content_type__app_label", "codename")
    }
    missing = {p for s in SECTIONS for p in _view(s) | _edit(s)} - have
    assert not missing, missing
