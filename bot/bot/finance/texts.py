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
        ["📕 Qarzlar"],
    ]
)
KB_ADMIN = reply_kb(
    [
        ["➖ Chiqim", "➕ Kirim"],
        ["📊 Ma'lumot", "📋 Operatsiyalar"],
        ["💸 Pul berish", "👛 Hamyonlar"],
        ["🧾 Buyurtmalar", "🔍 Tekshiruv"],
        ["📥 Excel", "❓ Yordam"],
        ["🕘 Davomat", "📕 Qarzlar"],
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
    "📕 <b>Qarzlar</b> — o'zingiz yozgan, kreditga olingan narsalar (do'kondan qarzga olingan LDSP, furnitura…): ro'yxat, yangi qarz yozish va to'lash. To'lov o'z hamyoningizdan chiqim bo'lib yoziladi.\n"
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
WAREHOUSE_CAT = "_ombor"  # pseudo-category of the warehouse spending on an order


def cat_label(cat, fallback_code: str | None = None) -> str:
    if isinstance(cat, dict):
        if cat.get("code") == WAREHOUSE_CAT and not cat.get("name"):
            return "📦 Furnitura (ombor)"
        return f"{cat.get('emoji', '')} {cat.get('name', '')}".strip()
    code = cat or fallback_code
    if code == WAREHOUSE_CAT:
        return "📦 Furnitura (ombor)"
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


PAY_HOME = "Uy uchun"  # only on the boss's own salary (Worker.is_boss)


def pay_label(p: str) -> str:
    if p == PAY_HOME:
        return "🏠 <b>Uy uchun</b>"
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


# ------------------------------------------------------------------ qarzlar (debts)
def debt_age_icon(days, status: str = "open") -> str:
    if status == "closed":
        return "✅"
    days = int(days or 0)
    return "🟢" if days <= 7 else ("🟡" if days <= 30 else "🔴")


def debt_sum(v, cur: str) -> str:
    """«1 500 000 so'm» or «300.00 $» (the debt's own currency)."""
    return f"{fmt_cur(v, cur)} $" if cur == "USD" else money(v)


def _debt_order(d: dict) -> str:
    ref, client = d.get("order_ref"), d.get("client")
    return f"🧾 {esc(ref)}" + (f" {esc(client)}" if client else "")


def debt_line(d: dict) -> str:
    cur = d.get("currency") or "UZS"
    return (
        f"{debt_age_icon(d.get('days'), d.get('status', 'open'))} #{d['number']} · {d.get('days', 0)} kun"
        f" · {esc(d['creditor'])} — {esc(str(d['item'])[:40])} · {_debt_order(d)}"
        f" · qoldiq {debt_sum(d.get('remaining'), cur)}"
    )


DEBT_PAGE = 20  # debts per page of the list (text lines and buttons)


def debt_page_rows(rows: list[dict], page: int) -> tuple[list[dict], int, int]:
    """(rows of the page, clamped page, pages)."""
    pages = max(1, -(-len(rows) // DEBT_PAGE))
    pg = max(0, min(page, pages - 1))
    return rows[pg * DEBT_PAGE : (pg + 1) * DEBT_PAGE], pg, pages


def debt_list_text(res: dict, closed: bool = False, page: int = 0) -> str:
    rows = res.get("rows") or []
    t = res.get("totals") or {}
    part, pg, pages = debt_page_rows(rows, page)
    pager = f" · {pg + 1}/{pages}-bet" if pages > 1 else ""
    if closed:
        head = "📗 <b>Yopilgan qarzlar</b> (oxirgi 30 ta)" + pager
        if not rows:
            return head + "\n\nHali yopilgan qarz yo'q."
        return head + "\n\n" + "\n".join(debt_line(d) for d in part)
    head = "📕 <b>Ochiq qarzlar</b>"
    if not rows:
        return head + "\n\n✅ Ochiq qarz yo'q."
    tot = f"💰 Jami qoldiq: <b>{money(t.get('open_uzs'))}</b>"
    if float(t.get("open_usd") or 0) > 0:
        tot += f" + <b>{debt_sum(t.get('open_usd'), 'USD')}</b>"
    lines = "\n".join(debt_line(d) for d in part)
    return head + f" ({t.get('open_count', len(rows))} ta){pager}\n" + tot + "\n\n" + lines


def debt_card(d: dict) -> str:
    cur = d.get("currency") or "UZS"
    lines = [
        f"📕 <b>Qarz #{d['number']}</b>",
        f"🏪 Kimdan: <b>{esc(d['creditor'])}</b>",
        f"📦 Nima olindi: {esc(d['item'])}",
        f"🗂 Kategoriya: {esc(cat_label(d.get('category')))}",
        _debt_order(d),
        f"📅 Olingan sana: {ddmm(d.get('date'))}",
        f"💰 Summa: <b>{debt_sum(d.get('total'), cur)}</b>",
        f"💸 To'langan: {debt_sum(d.get('paid'), cur)}",
        f"🧮 Qoldiq: <b>{debt_sum(d.get('remaining'), cur)}</b>",
    ]
    if d.get("status") == "closed":
        lines.append(f"✅ {d.get('days', 0)} kunda yopildi ({ddmm(d.get('closed_at'))[:5]})")
    else:
        lines.append(f"{debt_age_icon(d.get('days'))} {d.get('days', 0)} kun")
    if d.get("comment"):
        lines.append(f"📝 {esc(d['comment'])}")
    if d.get("by_name"):
        lines.append(f"👤 Kiritdi: {esc(d['by_name'])}")
    pays = d.get("payments") or []
    if pays:
        lines += ["", "<b>To'lovlar:</b>"]
        for p in pays:
            who = (p.get("member") or {}).get("name") or ""
            lines.append(
                f"• #{p['number']} · {ddmm(p.get('date'))[:5]} · {money_text(p)}"
                + (f" · {esc(who)}" if who else "")
            )
    return "\n".join(lines)


def debt_draft_card(d: dict) -> str:
    """The add-flow confirmation (draft keys: creditor, item, preview, cat_label, ord, client)."""
    return "\n".join(
        [
            "📕 <b>Yangi qarz</b>",
            f"🏪 Kimdan: <b>{esc(d['creditor'])}</b>",
            f"📦 Nima olindi: {esc(d['item'])}",
            f"💰 Summa: <b>{esc(d['preview'])}</b>",
            f"🗂 Kategoriya: {esc(d['cat_label'])}",
            _debt_order({"order_ref": d["ord"], "client": d.get("client")}),
            "",
            "To'lov keyinroq o'z hamyoningizdan, shu buyurtma chiqimiga yoziladi.",
        ]
    )


def debt_pay_card(d: dict) -> str:
    return "\n".join(
        [
            f"💸 To'lov: <b>{esc(d['pay_preview'])}</b>",
            f"📕 Qarz #{d['n']}: {esc(d['item'])} — {esc(d['creditor'])}",
            f"{_debt_order({'order_ref': d['ord'], 'client': d.get('client')})}",
            "👛 Hamyon: sizniki",
        ]
    )
