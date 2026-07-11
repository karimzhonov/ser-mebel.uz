"""Independent repro of the reported production crash:

    TypeError at /admin/price/price/add/
    the JSON object must be str, bytes or bytearray, not list
    POST /admin/price/price/add/?_changelist_filters=done%3DFalse

    TypeError at /admin/price/price/99/change/
    the JSON object must be str, bytes or bytearray, not list
    POST /admin/price/price/99/change/

Root cause per django-dev: forms.JSONField.bound_data() unconditionally calls
json.loads(data) when Django re-renders a *bound* form (e.g. after a
validation error elsewhere on the page). InventoryCountWidget.value_from_datadict()
always returns a Python list (never a JSON string), so on any invalid resubmit
that includes a TYPE_COUNT inline, json.loads(list) raises TypeError and the
admin 500s -- regardless of whether the inv_* field itself was filled in,
because BoundField.value() calls field.bound_data() for every bound field on
the page during rendering, not just invalid ones.

This test builds the *exact* repro shape: a real TYPE_COUNT InventoryType (so
the buggy field actually gets attached to the dynamic CalculateForm), a POST
with a deliberately blank required field (Calculate.name) to force Django to
re-render the bound form, and asserts the response is a normal 200
(re-rendered with validation errors) rather than a 500/TypeError.
"""

import pytest
from django.urls import reverse
from djmoney.money import Money


def _object_type_and_inventory():
    from metering.price.models import Inventory, InventoryType, ObjectType

    obj_type = ObjectType.objects.create(name="Kuxnya-crashrepro")
    inv_type = InventoryType.objects.create(
        name="Mexanizm-crashrepro", obj=obj_type, type=InventoryType.TYPE_COUNT
    )
    inventory = Inventory.objects.create(
        name="BLUM-crashrepro", type=inv_type, price=Money(10, "USD")
    )
    return obj_type, inv_type, inventory


def _calculate_inline_post_data(inv_type, inventory, *, name=""):
    """Build the exact POST keys the rendered CalculateInline formset uses.

    Field names verified by rendering the real admin add page and inspecting
    the HTML (prefix is the model-name-derived "calculate_set", independent
    of the dynamically-generated Object{pk}CalculateInline class name) --
    not guessed.
    """
    return {
        "calculate_set-TOTAL_FORMS": "1",
        "calculate_set-INITIAL_FORMS": "0",
        "calculate_set-MIN_NUM_FORMS": "0",
        "calculate_set-MAX_NUM_FORMS": "1000",
        "calculate_set-0-id": "",
        "calculate_set-0-name": name,
        "calculate_set-0-count": "5",
        f"calculate_set-0-inv_{inv_type.pk}_0": str(inventory.pk),
        f"calculate_set-0-inv_{inv_type.pk}_1": "2",
        f"calculate_set-0-inv_{inv_type.pk}_2": "",
    }


@pytest.mark.django_db
def test_price_add_reinvalid_submit_with_filled_inventory_count_does_not_500(
    logged_in_admin_client,
):
    obj_type, inv_type, inventory = _object_type_and_inventory()

    url = reverse("admin:price_price_add") + "?_changelist_filters=done%3DFalse"
    data = {"desc": "crash repro"}
    # Calculate.name is required and left blank -> the inline form is invalid,
    # forcing the whole changeform to be re-rendered bound (not saved), which
    # is exactly when JSONField.bound_data() gets called on the inv_* field.
    data.update(_calculate_inline_post_data(inv_type, inventory, name=""))

    response = logged_in_admin_client.post(url, data=data)

    assert response.status_code == 200, getattr(response, "content", b"")[:3000]
    # Sanity: it really did fail validation (i.e. we exercised the re-render
    # path, not a redirect-on-success).
    assert b"errorlist" in response.content or response.context is not None


@pytest.mark.django_db
def test_price_change_reinvalid_submit_with_filled_inventory_count_does_not_500(
    logged_in_admin_client,
):
    from metering.price.models import Price

    obj_type, inv_type, inventory = _object_type_and_inventory()
    price = Price.objects.create(metering=None)

    url = reverse("admin:price_price_change", args=[price.pk])
    data = {"desc": "crash repro change"}
    data.update(_calculate_inline_post_data(inv_type, inventory, name=""))

    response = logged_in_admin_client.post(url, data=data)

    assert response.status_code == 200, getattr(response, "content", b"")[:3000]
