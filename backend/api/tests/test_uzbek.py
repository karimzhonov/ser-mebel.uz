"""The API speaks Uzbek (Latin): labels, deadlines and library error messages.
Staff-entered data is returned as entered."""

import re
from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db
CYRILLIC = re.compile(r"[А-Яа-яЁёЎўҚқҒғҲҳ]")


def _texts(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _texts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _texts(v)
    elif isinstance(obj, str):
        yield obj


def test_meta_labels_are_uzbek_latin(admin_api):
    data = admin_api.get("/api/v1/meta/").data
    for key in (
        "order_statuses",
        "metering_statuses",
        "solutions",
        "inventory_type_kinds",
        "count_names",
    ):
        for item in data[key]:
            assert not CYRILLIC.search(item["label"]), item
    assert {s["value"]: s["label"] for s in data["order_statuses"]}[
        "working"
    ] == "Xomashyo buyurtmasi"


def test_boards_and_overview_have_no_cyrillic(admin_api, order_factory):
    order_factory(end_date=date.today() - timedelta(days=2))
    for url in ("/api/v1/dashboard/boards/", "/api/v1/dashboard/overview/"):
        data = admin_api.get(url).data
        bad = [t for t in _texts(data) if CYRILLIC.search(t) and t not in ("Test Client",)]
        assert bad == [], (url, bad)


def test_library_validation_messages_are_uzbek(admin_api):
    resp = admin_api.post("/api/v1/invoices/", {}, format="json")
    assert resp.status_code == 400
    assert resp.data["fio"] == ["Bu maydonni to'ldirish shart."]


def test_auth_errors_are_uzbek(db):
    resp = APIClient().get("/api/v1/orders/")
    assert resp.status_code == 401 and resp.data["detail"] == "Tizimga kirilmagan."
    resp = APIClient().post(
        "/api/v1/auth/login/", {"phone": "+998900000001", "password": "x"}, format="json"
    )
    assert not CYRILLIC.search(str(resp.data))


def test_staff_entered_data_is_untouched(admin_api):
    resp = admin_api.post(
        "/api/v1/invoices/",
        {"fio": "Алишер Навоий", "phone": "+998901119911", "desc": "Кухня"},
        format="json",
    )
    assert resp.data["client"]["fio"] == "Алишер Навоий" and resp.data["desc"] == "Кухня"


def test_not_found_is_uzbek(admin_api, order_factory):
    from order.assembly.models import Assembly

    hidden = Assembly.objects.create(order=order_factory(), square=1)  # order still "created"
    resp = admin_api.get(f"/api/v1/assemblies/{hidden.pk}/")
    assert resp.status_code == 404 and resp.data == {"detail": "Topilmadi."}
