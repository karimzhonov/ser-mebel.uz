"""Message texts and cards of the finance bot (same wording as code.txt)."""

from __future__ import annotations

from oauth.models import TelegramMember

from .. import services as S
from ..text import ddmm, esc, money, num, usd
from ..constants import CAT_SALARY, CAT_TRANSFER, OpKind
from ..models import Operation, Worker
from .api import reply_kb

VERSION = "site-1"

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
    ]
)
KB_TASK = reply_kb([["📋 Vazifalarim"], ["❓ Yordam"]])


def kb_for(m: TelegramMember | None):
    if m and m.is_admin:
        return KB_ADMIN
    if m and m.is_task_only:
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


def ver_line() -> str:
    return f"\n\n<i>Bot versiyasi: {VERSION}</i>"


def cat_label(code_or_cat) -> str:
    c = S.category(code_or_cat) if isinstance(code_or_cat, str) else code_or_cat
    if not c:
        return f"📦 {code_or_cat or '—'}"
    return f"{c.emoji} {c.name}".strip()


def amount_line(amount, cur: str, orig=None, rate=None) -> str:
    s = f"💵 <b>{money(amount)}</b>"
    if cur == "USD":
        s += f"  <i>({usd(orig)} × {num(rate)})</i>"
    return s


def order_line(ref: str | None) -> str:
    info = S.order_info(ref) if ref else None
    if info:
        return f"🧾 {esc(info.ref + ' · ' + info.client)}"
    return f"🧾 {esc(ref)}" if ref else "🧾 Umumiy (buyurtmasiz)"


def pay_label(p: str) -> str:
    return "🧾 <b>Oylik</b>" if p == "Oylik" else "💵 <b>Avans</b>"


def worker_line(name: str) -> str:
    if not name:
        return ""
    w = Worker.objects.filter(name=name).first()
    extra = ""
    if w:
        g = w.group.split("(")[0].strip()
        extra = f" ({esc(g)}{', ' + esc(w.position) if w.position else ''})"
    return f"👷 → <b>{esc(name)}</b>{extra}"


def sub_line(kind: str, cat_code: str, worker: str, pay: str, ord_ref: str, no_order: bool) -> str:
    if cat_code == CAT_TRANSFER:
        return f"🔄 {'→ ' if kind == OpKind.EXPENSE else '← '}<b>{esc(worker)}</b>"
    if cat_code == "zapravka" and worker:
        return f"🚗 → <b>{esc(worker)}</b>"
    if worker:
        return worker_line(worker) + (
            f"\n{pay_label(pay or 'Avans')}"
            if kind == OpKind.EXPENSE and cat_code == CAT_SALARY
            else ""
        )
    if kind == OpKind.EXPENSE and no_order and not ord_ref:
        return ""
    return order_line(ord_ref)


def op_card(t: Operation, bal=None) -> str:
    head = "➕ <b>KIRIM</b>" if t.kind == OpKind.INCOME else "➖ <b>CHIQIM</b>"
    lines = [
        f"{head}  #{t.number}",
        f"👤 {esc(t.member.name)}",
        amount_line(t.amount, t.currency, t.orig_amount, t.rate),
        cat_label(t.category),
        sub_line(t.kind, t.category.code, t.worker, t.pay_type, t.order_ref, t.category.no_order),
    ]
    lines = [x for x in lines if x]
    if t.comment:
        lines.append(f"📝 {esc(t.comment)}")
    if bal is not None:
        lines.append(f"💳 Hamyonda: {money(bal)}")
    lines.append(
        f"🕒 {ddmm(t.date)} {t.time.strftime('%H:%M') if t.time else ''}{'  📎' if t.receipt_file_id else ''}"
    )
    return "\n".join(lines)


def draft_card(d: dict) -> str:
    m = S.member_by_tg(d["uid"])
    cat = S.category(d.get("cat") or "")
    lines = [
        f"<b>{'➕ Kirim' if d['kind'] == OpKind.INCOME else '➖ Chiqim'} — tekshiring:</b>",
        "",
        f"👤 {esc(m.name if m else d['uid'])}",
        amount_line(d.get("amount"), d.get("cur", "UZS"), d.get("orig"), d.get("rate")),
        cat_label(cat or d.get("cat")),
        sub_line(
            d["kind"],
            d.get("cat") or "",
            d.get("worker") or "",
            d.get("pay") or "",
            d.get("ord") or "",
            bool(cat and cat.no_order),
        ),
        f"📝 {esc(d.get('com') or '—')}",
    ]
    out = [x for i, x in enumerate(lines) if i < 2 or x != ""]
    if d.get("rcpt"):
        out.append("📎 Chek bor")
    return "\n".join(out)


def task_role_text(m: TelegramMember) -> str:
    out = []
    if m.is_site_entry:
        out.append(
            "🌐 <b>Saytga kiritish</b>: mijozdan pul olinganda xabar keladi — saytda «Полученная сумма» ni to'g'rilab, «✅ Saytga kiritdim» ni bosasiz."
        )
    if m.is_feedback:
        out.append(
            "💬 <b>Mijoz fikri</b>: zakaz Готов bo'lganiga 3 kun bo'lganda xabar keladi — mijoz fikrini olib, «📝 Fikr oldim» ni bosib skrinshot yuborasiz."
        )
    return "\n\n".join(out) or "Vazifa belgilanmagan."
