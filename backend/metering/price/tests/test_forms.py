import json

from metering.price.forms import InventoryCountFormField, InventoryCountWidget


def test_decompress_returns_three_item_list_for_empty_value():
    widget = InventoryCountWidget()
    assert widget.decompress(None) == [None, None, ""]
    assert widget.decompress("") == [None, None, ""]
    assert widget.decompress([]) == [None, None, ""]


def test_decompress_passes_through_existing_three_item_list():
    widget = InventoryCountWidget()
    assert widget.decompress([5, 2.5, "100"]) == [5, 2.5, "100"]
    assert widget.decompress((5, 2.5, "100")) == [5, 2.5, "100"]


def test_decompress_parses_json_string():
    widget = InventoryCountWidget()
    value = json.dumps([7, 3, "150"])
    assert widget.decompress(value) == [7, 3, "150"]


def test_decompress_rejects_malformed_json_or_wrong_length():
    widget = InventoryCountWidget()
    assert widget.decompress("not json") == [None, None, ""]
    assert widget.decompress(json.dumps([1, 2])) == [None, None, ""]


def test_value_from_datadict_roundtrip():
    widget = InventoryCountWidget()
    data = {
        "inv_1_0": "5",
        "inv_1_1": "2.5",
        "inv_1_2": "100",
    }
    result = widget.value_from_datadict(data, {}, "inv_1")

    assert result == ["5", "2.5", "100"]


def test_value_from_datadict_missing_keys_returns_nones():
    widget = InventoryCountWidget()
    result = widget.value_from_datadict({}, {}, "inv_1")

    assert result == [None, None, None]


def test_decompress_of_value_from_datadict_output_is_a_noop_when_already_a_list():
    """The full round trip: what value_from_datadict returns is already a
    3-item list, so MultiWidget won't call decompress() on it again — but if it
    did (e.g. re-rendering with the same value), decompress must return it
    unchanged since it's already in the [inv_id, count, price] shape.
    """
    widget = InventoryCountWidget()
    data = {"inv_1_0": "5", "inv_1_1": "2.5", "inv_1_2": "100"}
    value = widget.value_from_datadict(data, {}, "inv_1")

    assert widget.decompress(value) == value


def test_inventory_count_form_field_bound_data_accepts_list_without_raising():
    """Regression: forms.JSONField.bound_data() unconditionally does
    json.loads(data), and InventoryCountWidget.value_from_datadict() returns a
    Python list — json.loads(list) raises TypeError (uncaught by JSONField),
    so re-rendering a bound CalculateForm after a validation error 500s.
    InventoryCountFormField.bound_data() must short-circuit for list/tuple
    input instead of forwarding it to json.loads() via the parent.
    """
    field = InventoryCountFormField(required=False)
    data = ["5", "2.5", "100"]

    result = field.bound_data(data, initial=None)

    assert result == ["5", "2.5", "100"]


def test_inventory_count_form_field_bound_data_still_parses_json_strings():
    """Non-list bound data (e.g. a JSON-encoded string) must still go through
    the normal forms.JSONField.bound_data()/json.loads() path."""
    field = InventoryCountFormField(required=False)

    result = field.bound_data(json.dumps([5, 2, "100"]), initial=None)

    assert result == [5, 2, "100"]
