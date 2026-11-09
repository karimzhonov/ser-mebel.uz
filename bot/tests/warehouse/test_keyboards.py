from bot.warehouse import keyboards as K

P = {
    "id": 123456789,
    "name": "X",
    "photos_count": 5,
    "url": "https://x.uz/warehouse?search=a",
    "is_active": True,
}
PHOTOS = [{"id": 987654321 + i} for i in range(5)]
UNITS = [{"value": "kvadrat_metr", "label": "m²"}, {"value": "dona", "label": "dona"}]
RES = {
    "items": [{**P, "quantity": "1.000", "unit_label": "dona", "low": True}],
    "page": 2,
    "pages": 3,
}


def _all(kb):
    return [btn for row in kb.inline_keyboard for btn in row]


def test_every_callback_fits_64_bytes_and_is_wh():
    kbs = [
        K.open_kb(),
        K.menu_kb(),
        K.cancel_kb(),
        K.skip_kb(K.b("x", "wh:lc")),
        K.confirm_kb(),
        K.photo_kb(),
        K.card_kb(P),
        K.list_kb("s", RES),
        K.units_kb(UNITS),
        K.units_kb(UNITS, "wh:eu:", f":{P['id']}"),
        K.categories_kb(["a"] * 40),
        K.edit_kb(P),
        K.moves_kb(
            P["id"],
            {"items": [{"number": "K-0000001234", "is_cancelled": False}], "page": 2, "pages": 3},
        ),
        K.cancel_move_kb("K-0000001234"),
        K.gallery_kb(PHOTOS, P["id"]),
        K.delete_kb(PHOTOS[0]["id"]),
        K.attach_kb(P["id"]),
    ]
    for kb in kbs:
        for btn in _all(kb):
            if btn.callback_data:
                assert btn.callback_data.startswith("wh:")
                assert len(btn.callback_data.encode()) <= 64
