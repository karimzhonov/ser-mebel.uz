"""Inline keyboards of the finance bot. callback_data strings are the same as the old
bot's, so buttons from old chat messages keep working."""

from __future__ import annotations

import re

from bot.common.fmt import ddmm
from bot.common.kb import CANCEL, b, grid, ik
from bot.finance.texts import CAT_ADVANCE, CAT_FROM_BOSS, CAT_REST, OP_EXPENSE, OP_INCOME


def cat_kb(cats: list[dict], admin: bool):
    """Expense categories (`cats` = kind expense)."""
    cs = [c for c in cats if admin or not c["admin_only"]]
    return ik(grid([b(f"{c['emoji']} {c['name']}", f"cat:{c['code']}") for c in cs], 2) + [[CANCEL]])


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
        [b(f"🗄 {x['ref']} · {x['client'][:24]} ({ddmm(x.get('ready_date'))[:5]})", f"ord:{x['ref']}")]
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
                if w["group"] == g and re.search(r"bosh|бош|глав|brigadir", w.get("position") or "", re.I)
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
