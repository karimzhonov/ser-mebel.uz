"""Texts of the omborchi part (Uzbek Latin, HTML). Shapes: docs/BOT_CONTRACT.md (WhProduct,
WhMovement, summary). Backend numbers are Decimal strings."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from bot.common.fmt import clip, ddmm, esc, fmt_cur, money, num

MENU_BTN = "📦 Ombor"
MAX_PHOTOS = 5

MENU = "📦 <b>Ombor</b>\nNima qilamiz? Mahsulot nomini yozsangiz ham qidiraman."
STALE = "⏳ Amal eskirib qoldi. Qaytadan boshlang."
NOT_KEEPER = "Ombor faqat omborchi uchun."
BUSY = "Avval ochiq amalni tugating yoki /bekor ni bosing."
CANCELLED = "Bekor qilindi."
GONE = "Bu tugma eskirgan."
ASK_QUERY = "🔍 Mahsulot nomi, kodi yoki turini yozing:"
QUERY_GONE = "Qidiruv eskirgan. Qaytadan yozing."
NOTHING = "Hech narsa topilmadi."
ASK_NAME = "➕ <b>Yangi mahsulot</b>\nNomini yozing:"
ASK_UNIT = "Birligini tanlang:"
ASK_CATEGORY = "Turini tanlang yoki yozing:"
ASK_CODE = "Kodini yozing (yoki o'tkazib yuboring):"
ASK_MIN = "Minimal qoldiqni yozing (yoki o'tkazib yuboring):"
ASK_PHOTO = "📷 Rasm yuboring (JPG, PNG, WEBP; bir nechta bo'lishi mumkin) yoki o'tkazib yuboring."
PHOTO_ONLY = "Rasm yuboring (JPG, PNG, WEBP) yoki «✅ Tayyor» ni bosing."
PHOTO_BAD = "Bu fayl rasm emas. JPG, PNG yoki WEBP yuboring."
PHOTO_BIG = "Rasm 10 MB dan katta."
PHOTO_FAIL = "❗ Rasmni yuklab bo'lmadi. Qayta yuboring."
BAD_QTY = "Miqdorni raqam bilan yozing, masalan: 12 yoki 1,5"
BAD_PRICE = "Narxni yozing, masalan: 120000, 1.2mln yoki 12.5$"
NOT_ENOUGH = "Omborda yetarli emas (qoldi: {left} {unit})."
NO_REFS = "Kamida bitta ID tanlang yoki «Mijozsiz» ni bosing."
UNKNOWN = "❗ Topilmadi: {refs}"
BAD_MIN = "Raqam yozing, masalan: 5 (yoki o'tkazib yuboring)."
ASK_EDIT_CODE = "Yangi kodni yozing (o'chirish uchun «-»):"
ASK_EDIT_CATEGORY = "Yangi turini yozing (o'chirish uchun «-»):"
ASK_EDIT_NAME = "Yangi nomini yozing:"
ASK_EDIT_MIN = "Yangi minimal qoldiqni yozing:"
ASK_EDIT_UNIT = "Yangi birlikni tanlang:"
SAVED = "✅ Saqlandi."
DELETE_ASK = "🗑 Bu rasmni o'chiraymi?"
CANCEL_ASK = "↩️ Harakat #{n} bekor qilinsinmi? Qoldiq qaytadan hisoblanadi."
CANCEL_DONE = "↩️ Bekor qilindi."
LIMIT = "Bitta mahsulotga {n} tadan ortiq rasm bo'lmaydi."
NO_PRODUCT = "Mahsulot topilmadi."
NO_MOVES = "Harakatlar yo'q."


def q(v) -> str:
    """Quantity without trailing zeros: «12.500» -> «12.5»."""
    try:
        d = Decimal(str(v if v not in (None, "") else 0))
    except InvalidOperation:
        return str(v)
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def price_line(amount, cur: str) -> str:
    return f"{fmt_cur(amount, 'USD')} $" if cur == "USD" else money(amount)


def btn_label(p: dict) -> str:
    low = " ⚠️" if p.get("low") else ""
    return f"{clip(p.get('name', ''), 28)} · {q(p.get('quantity'))} {p.get('unit_label', '')}{low}"


def cut(s, n: int) -> str:
    """Raw-text clip (call BEFORE esc)."""
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


def card(p: dict) -> str:
    """Caption <= 1024. Raw fields are clipped BEFORE escaping, so a cut never lands inside
    an HTML entity / tag."""
    text = _card(p, 120, 40, 60)
    if len(text) > 1024:
        text = _card(p, 40, 0, 0)
    return text


def _card(p: dict, n_name: int, n_code: int, n_cat: int) -> str:
    unit = esc(cut(p.get("unit_label", ""), 20))
    low = " ⚠️ kam qoldi" if p.get("low") else ""
    lines = [f"📦 <b>{esc(cut(p.get('name') or '', n_name))}</b>"]
    if p.get("code") and n_code:
        lines.append(f"🔖 Kod: <code>{esc(cut(p['code'], n_code))}</code>")
    if p.get("category") and n_cat:
        lines.append(f"🏷 Turi: {esc(cut(p['category'], n_cat))}")
    lines.append(f"📊 Qoldiq: <b>{q(p.get('quantity'))} {unit}</b>{low}")
    if Decimal(str(p.get("min_quantity") or 0)) > 0:
        lines.append(f"🔻 Minimal: {q(p['min_quantity'])} {unit}")
    lines.append(f"💰 O'rtacha narx: {money(p.get('avg_cost'))}")
    lines.append(f"💵 Qiymati: {money(p.get('value'))}")
    if p.get("is_active") is False:
        lines.append("🚫 Faol emas")
    return "\n".join(lines)


def move_line(m: dict) -> str:
    kind = "➕" if m.get("kind") == "in" else "➖"
    head = f"{kind} <b>#{esc(m.get('number'))}</b> {ddmm(m.get('date'))} · "
    body = f"{q(m.get('quantity'))} {esc(m.get('unit_label', ''))}"
    if m.get("currency") == "USD" and m.get("orig_price"):
        body += f" × {price_line(m['orig_price'], 'USD')}"
    elif m.get("unit_price"):
        body += f" × {money(m['unit_price'])}"
    extra = []
    if m.get("counterparty"):
        extra.append(esc(m["counterparty"]))
    allocs = m.get("allocations") or []
    if allocs:
        extra.append(", ".join(f"{esc(a.get('ref'))}×{q(a.get('quantity'))}" for a in allocs))
    if extra:
        body += " · " + ", ".join(extra)
    if m.get("is_cancelled"):
        return f"<s>{head}{body}</s> (bekor qilingan)"
    return head + body


def moves_text(p_name: str, res: dict) -> str:
    items = res.get("items") or []
    head = f"📜 <b>{esc(p_name)}</b> — harakatlar ({res.get('page', 1)}/{res.get('pages', 1)})"
    if not items:
        return head + "\n\n" + NO_MOVES
    return head + "\n\n" + "\n".join(move_line(m) for m in items)


def list_title(kind: str, res: dict, query: str = "") -> str:
    name = {"s": f"🔍 «{esc(query)}»", "lo": "⚠️ Kam qolganlar", "al": "📋 Barcha mahsulotlar"}[
        kind
    ]
    return f"{name} — {res.get('total', 0)} ta ({res.get('page', 1)}/{res.get('pages', 1)})"


def summary_text(s: dict) -> str:
    names = {"today": "bugun", "week": "shu hafta", "month": "shu oy"}
    return "\n".join(
        [
            f"📊 <b>Ombor hisoboti</b> — {names.get(s.get('period'), '')}",
            f"{ddmm(s.get('start'))} — {ddmm(s.get('end'))}",
            "",
            f"📦 Mahsulotlar: {num(s.get('products'))} ta",
            f"💵 Ombor qiymati: <b>{money(s.get('stock_value'))}</b>",
            f"⚠️ Kam qolgan: {num(s.get('low_count'))} ta",
            f"➕ Kirim: {money(s.get('period_in'))}",
            f"➖ Chiqim: {money(s.get('period_out'))}",
            f"Kurs: 1$ = {num(s.get('usd_rate'))} so'm",
        ]
    )


# ---------------------------------------------------------------- movement prompts
def ask_in_qty(name: str, unit: str) -> str:
    return f"➕ <b>Kirim</b> — {esc(name)}\nNecha {esc(unit)} kirim bo'ldi?"


def ask_out_qty(name: str, unit: str, stock) -> str:
    return (
        f"➖ <b>Chiqim</b> — {esc(name)}\nOmborda: {q(stock)} {esc(unit)}\n"
        f"Necha {esc(unit)} chiqdi?"
    )


def ask_price(rate, last: str = "") -> str:
    s = "💰 Narxi (1 birlik uchun): masalan 120000, 1.2mln yoki 12.5$\n"
    s += f"Kurs: 1$ = {num(rate)} so'm (Moliya)"
    if last:
        s += f"\nOxirgi kirim: {last}"
    return s


ASK_IN_PARTY = "Kimdan (yetkazib beruvchi)? Yozing yoki o'tkazib yuboring."
ASK_OUT_PARTY = "Kimga berildi? Yozing yoki o'tkazib yuboring."


def confirm_in(d: dict) -> str:
    qty = Decimal(d["qty"])
    amount, cur = Decimal(d["price"]), d["cur"]
    rate = Decimal(str(d.get("rate") or 0))
    per_uzs = amount * rate if cur == "USD" else amount
    total = qty * per_uzs
    stock, avg = Decimal(d.get("stock") or "0"), Decimal(d.get("avg") or "0")
    new_avg = (stock * avg + total) / (stock + qty) if stock + qty > 0 else per_uzs
    lines = [
        f"➕ <b>Kirim</b> — {esc(d['name'])}",
        f"Miqdor: <b>{q(qty)} {esc(d['unit'])}</b>",
        f"Narx: {price_line(amount, cur)}",
        f"Jami: ≈ {money(total)}",
    ]
    if d.get("party"):
        lines.append(f"Kimdan: {esc(d['party'])}")
    lines.append(f"Yangi o'rtacha narx (taxminan): {money(new_avg)}")
    return "\n".join(lines)


def confirm_out(d: dict) -> str:
    avg = Decimal(d.get("avg") or "0")
    allocs = d.get("allocs") or []
    qty = sum((Decimal(a["qty"]) for a in allocs), Decimal(0)) if allocs else Decimal(d["qty"])
    lines = [f"➖ <b>Chiqim</b> — {esc(d['name'])}"]
    if allocs:
        for a in allocs:
            who = f" {esc(cut(a.get('client'), 30))}" if a.get("client") else ""
            lines.append(
                f"{esc(a['ref'])}{who} — {q(a['qty'])} {esc(d['unit'])}"
                f" ≈ {money(Decimal(a['qty']) * avg)}"
            )
        lines.append(f"Jami: <b>{q(qty)} {esc(d['unit'])}</b> ≈ {money(qty * avg)}")
    else:
        lines += [
            f"Miqdor: <b>{q(qty)} {esc(d['unit'])}</b>",
            f"Narx: o'rtacha {money(avg)}",
            f"Jami: ≈ {money(qty * avg)}",
        ]
    if d.get("party"):
        lines.append(f"Kimga: {esc(d['party'])}")
    return "\n".join(lines)


def ask_refs(unit: str, stock, selected: list[dict] | None = None, note: str = "") -> str:
    s = (
        "Kimlar uchun? ID larni yozing (masalan: 406 410 SM-003) yoki tanlang.\n"
        f"Omborda: {q(stock)} {esc(unit)}"
    )
    if selected:
        s += "\nTanlangan: " + ", ".join(esc(x["ref"]) for x in selected)
    return (note + "\n\n" if note else "") + s


def ask_alloc(ref: dict, left, unit: str) -> str:
    who = f" · {esc(cut(ref.get('client'), 40))}" if ref.get("client") else ""
    return f"<b>{esc(ref['ref'])}</b>{who} — miqdor? (qoldi: {q(left)} {esc(unit)})"


def photo_added(n: int) -> str:
    return f"📷 {n}/{MAX_PHOTOS} qo'shildi"


def attach_ask(name: str) -> str:
    return f"Bu rasmni «{esc(name)}» ga qo'shaymi?"
