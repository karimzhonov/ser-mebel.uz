"""Message texts and cards of the finance bot (same wording as before), built from the
backend's DTO dicts (docs/BOT_CONTRACT.md section 1.2)."""

from __future__ import annotations

from bot.common.fmt import cur_name, ddmm, esc, fmt_cur, money, month_full, num, usd
from bot.common.kb import reply_kb

VERSION = "bot-1"

CAT_SALARY = "oylik"
CAT_FUEL = "zapravka"
CAT_REWORK = "peredelka"
CAT_TRANSFER = "otkazma"
CAT_FROM_BOSS = "rahbar"
CAT_ADVANCE = "avans"
CAT_REST = "qoldiq"
OP_EXPENSE = "expense"
OP_INCOME = "income"

KB_STAFF = reply_kb(
    [
        ["➖ Chiqim", "➕ Kirim"],
        ["💳 Hamyonim", "📋 Operatsiyalar"],
        ["🧾 Buyurtmalar", "📤 Oylik hisob"],
        ["🔄 Xodimga pul berish", "🙏 Rahbardan pul so'rash"],
    ]
)
KB_ADMIN = reply_kb(
    [
        ["➖ Chiqim", "➕ Kirim"],
        ["📊 Ma'lumot", "📋 Operatsiyalar"],
        ["💸 Pul berish", "👛 Hamyonlar"],
        ["🧾 Buyurtmalar", "🔍 Tekshiruv"],
        ["📥 Excel", "❓ Yordam"],
        ["🕘 Davomat"],
    ]
)
KB_TASK = reply_kb([["📋 Vazifalarim"], ["❓ Yordam"]])


def kb_for(m: dict | None):
    if m and m.get("is_admin"):
        return KB_ADMIN
    if m and m.get("is_task_only"):
        return KB_TASK
    return KB_STAFF


HELP_STAFF = (
    "<b>Qanday ishlatiladi</b>\n\n"
    "➖ <b>Chiqim</b> — pul sarfladingiz: summa → nimaga → qaysi buyurtma → izoh → chek rasmi.\n"
    "➕ <b>Kirim</b> — sizga pul berildi yoki mijozdan avans oldingiz.\n\n"
    "⚡ <b>Tezkor yozuv</b> — bitta xabar bilan:\n"
    "<code>1200000 mashina umid</code>\n<code>130000 наклейка лабо</code>\n<code>1.1mln завод продукта 406</code>\n"
    "<code>4200$ avans Назира 406</code>  (dollar avtomatik so'mga o'tadi)\n"
    "<code>2000000 oylik Dilmurod</code>  (oylik — ism bilan)\n\n"
    "📎 Chek rasmi shart emas. Xohlasangiz rasm ostiga <code>350000 furnitura 406</code> deb yuborsangiz ham bo'ladi\n\n"
    "💳 <b>Hamyonim</b> — qo'lingizda qancha pul qolgani va nimalarga ketgani.\n"
    "📤 <b>Oylik hisob</b> — oy oxirida hisobni tasdiqlab topshirish.\n"
    "🙏 <b>Rahbardan pul so'rash</b> — pul kerak bo'lsa, summa va sababini yozasiz, rahbarga boradi.\n"
    "🔄 <b>Xodimga pul berish</b> — boshqa xodimga pul bersangiz, ikkalangizning hamyoniga yoziladi (rahbar xabardor bo'ladi).\n"
    "🗑 Xato yozuvni o'chirish: /ochir 25  (25 — amal raqami)"
)
HELP_ADMIN = HELP_STAFF + (
    "\n\n<b>Rahbar uchun</b>\n"
    "📊 Ma'lumot — oy bo'yicha xarajat/daromad diagrammasi\n"
    "💸 Pul berish — xodimga pul berganingizni yozish\n👛 Hamyonlar — har bir xodim qo'lidagi pul\n"
    "🧾 Buyurtmalar — mijoz ID, har biri bo'yicha xarajat, foyda, mijoz qarzi\n"
    "🔍 Tekshiruv — kamchiliklar va yechimlar\n📥 Excel — oylik hisobot fayli\n"
    "/id 406 — buyurtma kartasi · /ism &lt;ID&gt; &lt;Ism&gt; — ismni o'zgartirish · /kurs 12050 — dollar kursi (/kurs 0 — Markaziy bank)\n"
    "/saytchi · /fikrchi — vazifa xodimlarini tanlash · /topshiruv — rahbarga topshirilmagan pullar · /kafolat — kafolat xatlari\n"
    "🌐 Hammasi saytda ham: «Moliya» bo'limi."
)

JOIN_TEXT = (
    "Assalomu alaykum! 👋\nBu ser-mebel.uz boti.\n\n💰 <b>Moliya</b> (kirim-chiqim, hamyon) "
    "bo'limidan foydalanish uchun ro'yxatdan o'ting — rahbar tasdiqlaydi."
)


def ver_line() -> str:
    return f"\n\n<i>Bot versiyasi: {VERSION}</i>"


def help_text(m: dict | None) -> str:
    return HELP_ADMIN if (m or {}).get("is_admin") else HELP_STAFF


def money_text(op: dict) -> str:
    """«250 000 so'm» or «100 $» for an Operation DTO (handover lines)."""
    if op.get("currency") == "USD":
        return f"{num(op.get('orig_amount'))} $"
    return money(op.get("amount"))


def money_full(amount, cur: str, orig=None) -> str:
    """«300 USD (≈ 3 540 000 so'm)» or «500 000 so'm» (S.money_text of the old service)."""
    if cur == "USD":
        return f"{num(orig)} USD (≈ {money(amount)})"
    return money(amount)


# ------------------------------------------------------------------ operation cards
def cat_label(cat, fallback_code: str | None = None) -> str:
    if isinstance(cat, dict):
        return f"{cat.get('emoji', '')} {cat.get('name', '')}".strip()
    code = cat or fallback_code
    return f"📦 {code or '—'}"


def amount_line(amount, cur: str, orig=None, rate=None) -> str:
    s = f"💵 <b>{money(amount)}</b>"
    if cur == "USD":
        s += f"  <i>({usd(orig)} × {num(rate)})</i>"
    return s


def order_line(ref: str | None, info: dict | None = None) -> str:
    if info and ref:
        return f"🧾 {esc(info['ref'] + ' · ' + info['client'])}"
    return f"🧾 {esc(ref)}" if ref else "🧾 Umumiy (buyurtmasiz)"


def pay_label(p: str) -> str:
    return "🧾 <b>Oylik</b>" if p == "Oylik" else "💵 <b>Avans</b>"


def worker_line(name: str, workers: list[dict] | None = None) -> str:
    if not name:
        return ""
    w = next((x for x in (workers or []) if x["name"] == name), None)
    extra = ""
    if w:
        g = (w.get("group") or "").split("(")[0].strip()
        pos = w.get("position") or ""
        extra = f" ({esc(g)}{', ' + esc(pos) if pos else ''})"
    return f"👷 → <b>{esc(name)}</b>{extra}"


def sub_line(
    kind: str,
    cat_code: str,
    worker: str,
    pay: str,
    ord_ref: str | None,
    no_order: bool,
    order: dict | None = None,
    workers: list[dict] | None = None,
) -> str:
    if cat_code == CAT_TRANSFER:
        return f"🔄 {'→ ' if kind == OP_EXPENSE else '← '}<b>{esc(worker)}</b>"
    if cat_code == "zapravka" and worker:
        return f"🚗 → <b>{esc(worker)}</b>"
    if worker:
        return worker_line(worker, workers) + (
            f"\n{pay_label(pay or 'Avans')}"
            if kind == OP_EXPENSE and cat_code == CAT_SALARY
            else ""
        )
    if kind == OP_EXPENSE and no_order and not ord_ref:
        return ""
    return order_line(ord_ref, order)


def op_card(
    t: dict, bal=None, order: dict | None = None, workers: list[dict] | None = None
) -> str:
    head = "➕ <b>KIRIM</b>" if t["kind"] == OP_INCOME else "➖ <b>CHIQIM</b>"
    cat = t["category"]
    lines = [
        f"{head}  #{t['number']}",
        f"👤 {esc(t['member']['name'])}",
        amount_line(t["amount"], t["currency"], t.get("orig_amount"), t.get("rate")),
        cat_label(cat),
        sub_line(
            t["kind"],
            cat["code"],
            t.get("worker") or "",
            t.get("pay_type") or "",
            t.get("order_ref"),
            bool(cat.get("no_order")),
            order,
            workers,
        ),
    ]
    lines = [x for x in lines if x]
    if t.get("comment"):
        lines.append(f"📝 {esc(t['comment'])}")
    if bal is not None:
        lines.append(f"💳 Hamyonda: {money(bal)}")
    lines.append(
        f"🕒 {ddmm(t.get('date'))} {t.get('time') or ''}{'  📎' if t.get('receipt_file_id') else ''}"
    )
    return "\n".join(lines)


def draft_card(
    d: dict,
    member_name: str | None,
    cat: dict | None,
    order: dict | None = None,
    workers: list[dict] | None = None,
) -> str:
    lines = [
        f"<b>{'➕ Kirim' if d['kind'] == OP_INCOME else '➖ Chiqim'} — tekshiring:</b>",
        "",
        f"👤 {esc(member_name or d['uid'])}",
        amount_line(d.get("amount"), d.get("cur", "UZS"), d.get("orig"), d.get("rate")),
        cat_label(cat, d.get("cat")),
        sub_line(
            d["kind"],
            d.get("cat") or "",
            d.get("worker") or "",
            d.get("pay") or "",
            d.get("ord") or "",
            bool(cat and cat.get("no_order")),
            order,
            workers,
        ),
        f"📝 {esc(d.get('com') or '—')}",
    ]
    out = [x for i, x in enumerate(lines) if i < 2 or x != ""]
    if d.get("rcpt"):
        out.append("📎 Chek bor")
    return "\n".join(out)


def task_role_text(m: dict) -> str:
    out = []
    if m.get("is_site_entry"):
        out.append(
            "🌐 <b>Saytga kiritish</b>: mijozdan pul olinganda xabar keladi — saytda «Полученная сумма» ni to'g'rilab, «✅ Saytga kiritdim» ni bosasiz."
        )
    if m.get("is_feedback"):
        out.append(
            "💬 <b>Mijoz fikri</b>: zakaz Готов bo'lganiga 3 kun bo'lganda xabar keladi — mijoz fikrini olib, «📝 Fikr oldim» ni bosib skrinshot yuborasiz."
        )
    return "\n\n".join(out) or "Vazifa belgilanmagan."


def checks_text(issues: list[dict], limit: int = 15) -> str:
    if not issues:
        return "✅ Tekshiruv: kamchilik topilmadi."
    lv = {"h": "🔴", "m": "🟠", "l": "🟡"}
    cnt = {"h": 0, "m": 0, "l": 0}
    for i in issues:
        cnt[i["level"]] += 1
    s = f"🔍 <b>Tekshiruv natijasi</b>\n🔴 Jiddiy: {cnt['h']}   🟠 O'rta: {cnt['m']}   🟡 Kichik: {cnt['l']}\n"
    for i in issues[:limit]:
        s += f"\n{lv[i['level']]} <b>{esc(i['title'])}</b>\n   {esc(i['detail'])}\n   💡 {esc(i['fix'])}\n"
    if len(issues) > limit:
        s += f"\n…yana {len(issues) - limit} ta — to'liq ro'yxat saytda: Moliya → Tekshiruv."
    return s


def req_admin_text(req: dict) -> str:
    return (
        f"🙏 <b>Pul so'rovi #{req['number']}</b>\n👤 {esc(req['member']['name'])}\n💵 <b>{money_full(req['amount'], req['currency'], req.get('orig_amount'))}</b>"
        + (f"\n📝 {esc(req['reason'])}" if req.get("reason") else "")
        + f"\n💳 Hamyonida hozir: {money(req.get('member_balance'))}\n🕒 {_dm_hm(req.get('created_at'))}"
    )


def _dm_hm(iso: str | None) -> str:
    """'2026-10-27T10:15:00' -> '27.10 10:15'."""
    if not iso or len(iso) < 16:
        return "—"
    return f"{iso[8:10]}.{iso[5:7]} {iso[11:16]}"


# ------------------------------------------------------------------ bonus / «Готов»
def bonus_line(bn: dict, usd_rate) -> str:
    total = float(bn.get("total") or 0)
    if not total:
        return ""
    som = total * float(usd_rate or 0) if bn["currency"] == "USD" else total
    return (
        "🎁 <b>Bonus</b> (to'liq yopilsa): 3 kun ichida 0.5% (≈"
        + num(som * 0.005)
        + " so'm), 7 kungacha 0.4%, 30 kungacha 0.3%, keyin 0%."
    )


def ready_text(bn: dict, ms: dict, usd_rate) -> str:
    c = bn["currency"]
    if float(bn.get("total") or 0):
        money_part = (
            f"\n💼 Umumiy summa: <b>{fmt_cur(bn['total'], c)} {cur_name(c)}</b>"
            f"\n💰 To'langan ({'saytdan' if ms['src'] == 'sayt' else 'botdan'}): {fmt_cur(ms['paid'], c)}"
            f"\n🧮 Qoldiq: <b>{fmt_cur(ms['rest'], c)} {cur_name(c)}</b>"
        )
    else:
        money_part = "\n⚠️ Saytda buyurtma summasi kiritilmagan."
    return (
        f"✅ <b>Zakaz tayyor (Готов)</b>\n🧾 <b>{esc(bn['order_ref'])} · {esc(bn['client'])}</b>"
        + money_part
        + "\n\n❗ <b>Menejerlardan so'rang: yana pul qo'shilmaganmi?</b> (qo'shimcha ish, o'zgarish, skidka)\n\n"
        + bonus_line(bn, usd_rate)
        + "\n\n<i>Mijozdan pulni olganingizda «💰 Pul oldim» ni bosing: to'liq yoki qisman. To'liq olingan kun bo'yicha bonus hisoblanadi.</i>"
    )


def bonus_done_text(bn: dict) -> str:
    pct = bn.get("percent")
    pct_txt = f"{float(pct):g}" if pct not in (None, "") else "0"
    return (
        f"🎉 <b>{esc(bn['order_ref'])} · {esc(bn['client'])}</b> — mijozdan pul to'liq olindi ({bn.get('days')} kunda)"
        f"\n🎁 Bonus: <b>{pct_txt}% = {money(bn.get('bonus') or 0)}</b>\n📝 {esc(bn.get('note'))}"
        + (
            "\n<i>«Bonuslar» bo'limiga yozildi. Saytda qoldiqni ham tekshirib qo'ying.</i>"
            if float(pct or 0)
            else "\n<i>30 kundan o'tgani uchun bonus yo'q.</i>"
        )
    )


def fallback_prefix(who: str) -> str:
    return (
        f"⚠️ <i>{who} belgilanmagan (saytda Moliya → Telegram a'zolar). Xabar sizga keldi:</i>\n\n"
    )


def month_text(sm: dict) -> str:
    """The monthly-report block (MonthSummary DTO)."""
    return (
        f"📤 <b>{month_full(sm['month'])} — oylik hisob</b>\n\nOy boshida: {money(sm['opening'])}"
        f"\n🟢 Kirim: {money(sm['income'])}"
        f"\n🔴 Chiqim: {money(sm['expense'])}\n👛 Oy oxiriga qoldiq: <b>{money(sm['closing'])}</b>"
        f"\nAmallar soni: {sm['count']}\n"
    )


def _register_buttons() -> None:
    """Tell HR's pending-answer handler which texts are finance menu buttons."""
    from bot.hr import register_menu_buttons

    texts = [t.text for kb in (KB_STAFF, KB_ADMIN, KB_TASK) for row in kb.keyboard for t in row]
    register_menu_buttons(*texts)


_register_buttons()
