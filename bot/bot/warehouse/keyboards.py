"""Keyboards of the omborchi part. All callback_data start with `wh:` and stay <= 64 bytes
(old buttons in chats must keep working; do not rename):

wh:m menu | wh:q ask query | wh:s:{page} results of the saved query | wh:lo:{page} low |
wh:al:{page} all | wh:sm:{d|w|m} summary | wh:n new product | wh:p:{pid} card |
wh:i:{pid} kirim | wh:o:{pid} chiqim | wh:ph:{pid} add photos | wh:g:{pid} gallery |
wh:pc:{photo} cover | wh:pd:{photo} ask delete | wh:pdy:{photo} confirm delete |
wh:e:{pid} edit menu | wh:ef:{n|c|t|u|m}:{pid} edit field | wh:eu:{unit}:{pid} set unit |
wh:ea:{pid} active toggle | wh:h:{pid}:{page} movements | wh:cx:{number} ask cancel |
wh:cy:{number} confirm cancel | wh:un:{unit} unit pick | wh:ct:{idx} category pick |
wh:ot:{v}:{i} toggle candidate i of list version v | wh:op:{v}:{page} candidates page | wh:on continue with the
selected clients | wh:o0 chiqim without clients | wh:sk skip | wh:lp last price | wh:lc last supplier | wh:ok save | wh:ok:ph photos done |
wh:x cancel | wh:at:{pid} attach pending photo | wh:atn do not attach.
"""

from __future__ import annotations

from bot.common.kb import b, grid, ik, reply_kb, url_button

from . import texts as T

MENU_CB = "wh:m"


def reply_menu():
    return reply_kb([[T.MENU_BTN]])


def open_kb():
    return ik([[b("📦 Omborni ochish", MENU_CB)]])


def menu_kb():
    return ik(
        [
            [b("🔍 Qidirish", "wh:q"), b("📋 Barcha mahsulotlar", "wh:al:1")],
            [b("⚠️ Kam qolganlar", "wh:lo:1"), b("➕ Yangi mahsulot", "wh:n")],
            [
                b("📊 Bugun", "wh:sm:d"),
                b("📊 Hafta", "wh:sm:w"),
                b("📊 Oy", "wh:sm:m"),
            ],
        ]
    )


def cancel_kb():
    return ik([[b("❌ Bekor qilish", "wh:x")]])


def skip_kb(*extra):
    return ik([list(extra), [b("⏭ O'tkazib yuborish", "wh:sk")], [b("❌ Bekor qilish", "wh:x")]])


def confirm_kb():
    return ik([[b("✅ Saqlash", "wh:ok"), b("❌ Bekor", "wh:x")]])


def photo_kb():
    return ik([[b("✅ Tayyor", "wh:ok:ph")]])


def photo_new_kb():
    return ik([[b("⏭ O'tkazib yuborish", "wh:sk")]])


def card_kb(p: dict):
    pid = p["id"]
    rows = [
        [b("➕ Kirim", f"wh:i:{pid}"), b("➖ Chiqim", f"wh:o:{pid}")],
        [
            b("📷 Rasm qo'shish", f"wh:ph:{pid}"),
            b(f"🖼 Rasmlar ({p.get('photos_count', 0)})", f"wh:g:{pid}"),
        ],
        [b("✏️ Tahrirlash", f"wh:e:{pid}"), b("📜 Harakatlar", f"wh:h:{pid}:1")],
    ]
    url = p.get("url") or ""
    if url.startswith(("http://", "https://")):
        rows.append([url_button("🌐 Saytda ochish", url)])
    rows.append([b("🏠 Menyu", MENU_CB)])
    return ik(rows)


def list_kb(kind: str, res: dict):
    rows = [[b(T.btn_label(p), f"wh:p:{p['id']}")] for p in res.get("items") or []]
    page, pages = int(res.get("page", 1)), int(res.get("pages", 1))
    nav = []
    if page > 1:
        nav.append(b("◀️", f"wh:{kind}:{page - 1}"))
    if page < pages:
        nav.append(b("▶️", f"wh:{kind}:{page + 1}"))
    rows += [nav, [b("🏠 Menyu", MENU_CB)]]
    return ik(rows)


def summary_kb():
    return menu_kb()


def units_kb(units: list[dict], prefix: str = "wh:un:", suffix: str = ""):
    btns = [b(u["label"], f"{prefix}{u['value']}{suffix}") for u in units]
    return ik(grid(btns, 3) + [[b("❌ Bekor qilish", "wh:x")]])


def categories_kb(categories: list[str]):
    btns = [b(c[:30], f"wh:ct:{i}") for i, c in enumerate(categories)]
    return ik(grid(btns, 2) + [[b("⏭ O'tkazib yuborish", "wh:sk")], [b("❌ Bekor qilish", "wh:x")]])


def edit_kb(p: dict):
    pid = p["id"]
    return ik(
        [
            [b("Nomi", f"wh:ef:n:{pid}"), b("Kodi", f"wh:ef:c:{pid}")],
            [b("Turi", f"wh:ef:t:{pid}"), b("Birligi", f"wh:ef:u:{pid}")],
            [b("Min. qoldiq", f"wh:ef:m:{pid}")],
            [
                b(
                    "✅ Faollashtirish" if p.get("is_active") is False else "🚫 Faolsizlantirish",
                    f"wh:ea:{pid}",
                )
            ],
            [b("⬅️ Kartaga", f"wh:p:{pid}")],
        ]
    )


def moves_kb(pid: int, res: dict):
    items = res.get("items") or []
    undo = [
        b(f"↩️ #{m['number']}", f"wh:cx:{m['number']}") for m in items if not m.get("is_cancelled")
    ]
    page, pages = int(res.get("page", 1)), int(res.get("pages", 1))
    nav = []
    if page > 1:
        nav.append(b("◀️", f"wh:h:{pid}:{page - 1}"))
    if page < pages:
        nav.append(b("▶️", f"wh:h:{pid}:{page + 1}"))
    return ik(grid(undo, 4) + [nav, [b("⬅️ Kartaga", f"wh:p:{pid}")]])


def cancel_move_kb(number):
    return ik([[b("✅ Ha, bekor qilish", f"wh:cy:{number}"), b("❌ Yo'q", "wh:x")]])


def gallery_kb(photos: list[dict], pid: int):
    rows = []
    for i, ph in enumerate(photos, 1):
        row = []
        if i > 1:
            row.append(b(f"⭐ {i}", f"wh:pc:{ph['id']}"))
        row.append(b(f"🗑 {i}", f"wh:pd:{ph['id']}"))
        rows.append(row)
    rows.append([b("⬅️ Kartaga", f"wh:p:{pid}")])
    return ik(rows)


def delete_kb(photo_id):
    return ik([[b("✅ Ha, o'chirish", f"wh:pdy:{photo_id}"), b("❌ Yo'q", "wh:x")]])


def attach_kb(pid: int):
    return ik([[b("✅ Ha", f"wh:at:{pid}"), b("❌ Yo'q", "wh:atn")]])


REF_PAGE = 8


def orders_kb(d: dict):
    """Client candidates as toggles (2 per row), paging, continue / no-client / cancel."""
    cands = d.get("cands") or []
    v = int(d.get("v") or 0)  # bumped whenever `cands` is replaced: old buttons go stale
    sel = {x["ref"] for x in d.get("sel") or []}
    page = int(d.get("page") or 0)
    pages = max(1, -(-len(cands) // REF_PAGE))
    page = min(max(page, 0), pages - 1)
    btns = []
    for i in range(page * REF_PAGE, min(len(cands), (page + 1) * REF_PAGE)):
        c = cands[i]
        label = f"{c['ref']} · {c.get('client') or ''}".strip(" ·")[:28]
        btns.append(b(("✅ " if c["ref"] in sel else "") + label, f"wh:ot:{v}:{i}"))
    nav = []
    if page > 0:
        nav.append(b("◀️", f"wh:op:{v}:{page - 1}"))
    if page < pages - 1:
        nav.append(b("▶️", f"wh:op:{v}:{page + 1}"))
    return ik(
        grid(btns, 2)
        + [
            nav,
            [b(f"➡️ Davom ({len(sel)})", "wh:on"), b("🚫 Mijozsiz", "wh:o0")],
            [b("❌ Bekor qilish", "wh:x")],
        ]
    )
