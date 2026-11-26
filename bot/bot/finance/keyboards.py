"""Inline keyboards of the finance bot. callback_data strings are the same as the old
bot's, so buttons from old chat messages keep working."""

from __future__ import annotations

import re

from bot.common.fmt import ddmm
from bot.common.kb import CANCEL, b, grid, ik
from bot.finance.texts import CAT_ADVANCE, CAT_FROM_BOSS, CAT_REST, OP_EXPENSE, OP_INCOME


def wallet_may_use(c: dict, wallet_tg) -> bool:
    """`only_tg` (additive, finance/categories/): only these wallets book it; [] = all."""
    only = c.get("only_tg") or []
    return not only or wallet_tg in only


def cat_kb(cats: list[dict], admin: bool, wallet_tg=None):
    """Expense categories (`cats` = kind expense) the draft's wallet may book."""
    cs = [c for c in cats if (admin or not c["admin_only"]) and wallet_may_use(c, wallet_tg)]
    return ik(
        grid([b(f"{c['emoji']} {c['name']}", f"cat:{c['code']}") for c in cs], 2) + [[CANCEL]]
    )


def src_kb(cats: list[dict]):
    # «Rahbardan» is not here: only the boss books it, through «💸 Pul berish».
    cs = [c for c in cats if c["code"] != CAT_FROM_BOSS]
    return ik([[b(f"{c['emoji']} {c['name']}", f"cat:{c['code']}")] for c in cs] + [[CANCEL]])


ORDER_ICONS = {"yangi": "🆕 ", "yakun": "✅ ", "jarayonda": "🧾 ", "kutish": "⏳ "}


def order_buckets(kind: str, cat_code: str) -> tuple[list[str], bool]:
    """(which order buckets to offer, whether «Umumiy» is offered)."""
    general = True
    if kind != OP_INCOME:
        want = ["jarayonda", "yangi"] if cat_code == "material" else ["jarayonda"]
    elif cat_code == CAT_ADVANCE:
        want, general = ["yangi", "jarayonda", "kutish"], False
    elif cat_code == CAT_REST:
        want, general = ["kutish", "yakun"], False
    else:
        want = ["yangi", "jarayonda", "kutish", "yakun"]
    return want, general


def order_kb(kind: str, cat: dict | None, cat_code: str, orders: list[dict], general: bool):
    rows = [
        [b(f"{ORDER_ICONS.get(o['bucket'], '')}{o['ref']} · {o['client'][:28]}", f"ord:{o['ref']}")]
        for o in orders[:60]
    ]
    if general or not orders:
        rows.append([b("🏭 Umumiy (buyurtmasiz)", "ord:-")])
    if kind == OP_EXPENSE and cat and cat.get("archive"):
        rows.append([b("🗄 Arxiv ID (Готов, oxirgi 4 oy)", "oarx:0")])
    rows.append([CANCEL])
    return ik(rows)


def arx_kb(orders: list[dict], page: int):
    n = 30
    pages = max(1, -(-len(orders) // n))
    pg = max(0, min(page, pages - 1))
    rows = [
        [
            b(
                f"🗄 {x['ref']} · {x['client'][:24]} ({ddmm(x.get('ready_date'))[:5]})",
                f"ord:{x['ref']}",
            )
        ]
        for x in orders[pg * n : pg * n + n]
    ]
    nav = []
    if pg > 0:
        nav.append(b("◀️", f"oarx:{pg - 1}"))
    if (pg + 1) * n < len(orders):
        nav.append(b("▶️", f"oarx:{pg + 1}"))
    rows += [nav, [b("⬅️ Orqaga (faol buyurtmalar)", "oarx:back")], [CANCEL]]
    return ik(rows), len(orders), pg, pages


def skip_kb(tag: str):
    return ik([[b("⏭ O'tkazib yuborish", f"skip:{tag}")], [CANCEL]])


# ------------------------------------------------------------------ worker pick
def worker_groups(workers: list[dict]) -> list[str]:
    out: list[str] = []
    for w in workers:
        if w["group"] not in out:
            out.append(w["group"])
    return out


def is_team(g: str) -> bool:
    return bool(re.search(r"komanda|команда|brigada|бригада", g, re.I))


def short_group(g: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", g)


def team_name(g: str) -> str:
    return "👥 " + short_group(g) + " (butun komanda)"


def group_label(g: str, workers: list[dict]) -> str:
    gl = g.lower()
    icon = (
        "🔧"
        if is_team(g)
        else (
            "🏭"
            if re.search(r"zavod|завод|sex|цех", gl)
            else (
                "🎨"
                if re.search(r"molyar|маляр|bo'yoq", gl)
                else "🗂" if re.search(r"ofis|офис", gl) else "👥"
            )
        )
    )
    boss = None
    if is_team(g):
        boss = next(
            (
                w
                for w in workers
                if w["group"] == g
                and re.search(r"bosh|бош|глав|brigadir", w.get("position") or "", re.I)
            ),
            None,
        )
    return f"{icon} {short_group(g)}" + (f" · {boss['name']}" if boss else "")


def group_kb(workers: list[dict]):
    groups = worker_groups(workers)
    return ik([[b(group_label(g, workers), f"wg:{i}")] for i, g in enumerate(groups)] + [[CANCEL]])


def worker_kb(workers: list[dict], gi: int):
    groups = worker_groups(workers)
    if gi >= len(groups):
        return group_kb(workers)
    g = groups[gi]
    rows = []
    for w in workers:
        if w["group"] != g:
            continue
        pos = w.get("position") or ""
        crown = "👑 " if re.search(r"bosh|бош|глав", pos, re.I) else ""
        rows.append([b(crown + w["name"] + (f" — {pos}" if pos else ""), f"wk:{w['id']}")])
    if is_team(g):
        rows.append([b(team_name(g), f"wt:{gi}")])
    rows.append([b("⬅️ Orqaga", "wb"), CANCEL])
    return ik(rows)


# ------------------------------------------------------------------ small ones
def handover_kb(number: int):
    return ik(
        [
            [b("✅ Pulni qabul qildim", f"pqk:{number}")],
            [b("🗑 Men buni alohida kiritganman", f"pqd:{number}")],
        ]
    )


def advance_kb(adv_id: int):
    return ik(
        [
            [b("✅ Pulni qabul qildim", f"avk:{adv_id}")],
            [b("✏️ Boshqa summa oldim", f"avs:{adv_id}")],
            [b("❌ Pul kelmadi", f"avn:{adv_id}")],
        ]
    )


def paid_kb(ref: str):
    return ik([[b("💰 Pul oldim", f"bpaid:{ref}")]])


def feedback_kb(ref: str):
    return ik([[b("📝 Fikr oldim", f"fko:{ref}")]])


def site_done_kb(code: str):
    return ik([[b("✅ Saytga kiritdim", f"skt:{code}")]])


def saved_kb(number: int, with_receipt: bool):
    btns = [b("🗑 O'chirish", f"del:{number}")]
    if with_receipt:
        btns.insert(0, b("📎 Chek qo'shish", f"rcpt:{number}"))
    return ik([btns])


# ------------------------------------------------------------------ qarzlar (callback prefix «qz:»)
DEBT_SKIP_CATS = {"oylik", "zapravka"}  # same filter as the site's debt form


def debt_cats(cats: list[dict], admin: bool) -> list[dict]:
    return [
        c
        for c in cats
        if c.get("kind", "expense") == "expense"
        and c.get("is_active", True)
        and not c.get("no_order")
        and not c.get("excluded")
        and c["code"] not in DEBT_SKIP_CATS
        and (admin or not c.get("admin_only"))
    ]


def debts_kb(rows: list[dict], closed: bool, page: int = 0):
    from bot.finance.texts import debt_page_rows

    part, pg, pages = debt_page_rows(rows, page)
    key = "z" if closed else "l"
    btns = [
        [b(f"#{d['number']} · {d['creditor'][:20]} · {d['item'][:18]}", f"qz:v:{d['number']}")]
        for d in part
    ]
    nav = []
    if pg > 0:
        nav.append(b("◀️", f"qz:{key}:{pg - 1}"))
    if pg + 1 < pages:
        nav.append(b("▶️", f"qz:{key}:{pg + 1}"))
    btns.append(nav)
    btns.append(
        [
            b("➕ Yangi qarz", "qz:n"),
            b("📕 Ochiqlar", "qz:l") if closed else b("📗 Yopilganlar", "qz:z"),
        ]
    )
    return ik(btns)


def debt_card_kb(d: dict):
    rows = []
    if d.get("status", "open") == "open" and d.get("can_pay", True):
        rows.append([b("💸 To'lash", f"qz:p:{d['number']}")])
    if d.get("can_delete"):  # the backend's verdict; a missing flag means no button
        rows.append([b("🗑 O'chirish", f"qz:d:{d['number']}")])
    rows.append([b("⬅️ Ro'yxat", "qz:l")])
    return ik(rows)


def debt_delete_kb(number: int):
    """Confirmation. «Yo'q» is `qz:v` (not the shared cancel: that would wipe a debt draft)."""
    return ik(
        [[b("🗑 Ha, o'chirish", f"qz:dy:{number}"), b("Yo'q", f"qz:v:{number}")]],
    )


def debt_gone_kb():
    return ik([[b("⬅️ Ro'yxat", "qz:l")]])


def debt_back_kb(number: int):
    return ik([[b("⬅️ Qarzga qaytish", f"qz:v:{number}")]])


def debt_cat_kb(cats: list[dict], admin: bool):
    cs = debt_cats(cats, admin)
    return ik(
        grid([b(f"{c['emoji']} {c['name']}", f"qz:k:{c['code']}") for c in cs], 2) + [[CANCEL]]
    )


def _row_buttons(rows: list[dict] | None) -> list[list]:
    """«❌ 406» per entered order (`qz:x:{row id}`; row ids are digits, never the ref)."""
    return [[b(f"❌ {r['r'][:24]}", f"qz:x:{r['i']}")] for r in rows or []]


def debt_order_kb(orders: list[dict], rows: list[dict] | None = None):
    """Order picker. Orders already in `rows` are left out; an order whose `qz:o:` data
    would not fit Telegram's 64 BYTES is left out too (it can still be typed)."""
    used = {r["r"].casefold() for r in rows or []}
    out = []
    for o in orders[:60]:
        data = f"qz:o:{o['ref']}"
        if o["ref"].casefold() in used or len(data.encode()) > 64:
            continue
        label = f"{ORDER_ICONS.get(o['bucket'], '')}{o['ref']} · {o['client'][:28]}"
        out.append([b(label, data)])
    out += _row_buttons(rows)
    out.append([b("⌨️ ID yozish", "qz:ot")])
    out.append([CANCEL])
    return ik(out)


def debt_share_kb(rem_text: str):
    return ik(
        [
            [b(f"✅ Hammasi shu ID ga: {rem_text}", "qz:wa")],
            [b("⬅️ Boshqa ID", "qz:sb")],
            [CANCEL],
        ]
    )


def debt_confirm_kb(rows: list[dict] | None = None):
    return ik([[b("✅ Saqlash", "qz:s")], *_row_buttons(rows), [CANCEL]])


def debt_pay_order_kb(deb: dict, rem_text: str):
    """Pay picker of a split debt: one button per UNPAID order + «Hammasi»."""
    from bot.finance.texts import debt_sum

    cur = deb.get("currency") or "UZS"
    n = deb["number"]
    rows = [
        [
            b(
                f"🧾 {str(a.get('order_ref'))[:24]} — qoldiq {debt_sum(a.get('remaining'), cur)}",
                f"qz:po:{n}:{a['id']}",
            )
        ]
        for a in deb.get("allocations") or []
        if a.get("id") is not None and float(a.get("remaining") or 0) > 0
    ]
    rows.append([b(f"✅ Hammasi: {rem_text}", f"qz:pw:{n}")])
    rows.append([b("⬅️ Qarzga qaytish", f"qz:v:{n}")])
    return ik(rows)


def debt_pay_amount_kb(rem_text: str, nonce: str = ""):
    """`qz:pf:{nonce}`: the nonce ties the button to the prompt it came with (bare = old)."""
    return ik([[b(f"✅ To'liq: {rem_text}", f"qz:pf:{nonce}" if nonce else "qz:pf")], [CANCEL]])


def debt_pay_confirm_kb(nonce: str = ""):
    return ik([[b("✅ To'lash", f"qz:py:{nonce}" if nonce else "qz:py")], [CANCEL]])
