"""`finance.*` events from the backend (POST /notify): wording, buttons and recipients'
rendering. The backend sends data and recipient ids only (docs/BOT_CONTRACT.md 1.5)."""

from __future__ import annotations

import logging

from bot.backend.client import BackendError, backend
from bot.common.fmt import add_months, cur_name, ddmm, esc, fmt_cur, money, month_full, num
from bot.common.kb import b, ik
from bot.finance import keyboards as K
from bot.finance import texts as T
from bot.finance.api import D
from bot.notify.registry import Notifier, on

logger = logging.getLogger(__name__)


def kb_member(m: dict):
    return T.kb_for(m)


def op_text(op: dict, bal=None) -> str:
    return T.op_card(op, bal)


async def forget_whoami(tg) -> None:
    """The person's roles just changed: drop their cached whoami."""
    from bot.common.rds import get_redis

    try:
        await get_redis().delete(f"whoami:{tg}")
    except Exception:  # noqa: BLE001
        pass


async def channel(n: Notifier, data: dict, text: str, photo_id: str | None = None):
    ch = str(data.get("channel_id") or "").strip()
    if not ch:
        return
    if photo_id:
        await n.photo_or_text(ch, photo_id, text)
    else:
        await n.send(ch, text)


async def duty(n: Notifier, data: dict, text: str, photo=None, kb=None):
    """To the duty holders; `fallback` = they are the admins, with the note."""
    if data.get("fallback"):
        text = T.fallback_prefix(data.get("fallback_who") or "") + text
    for chat in dict.fromkeys(data.get("to") or []):
        if photo is not None:
            if await n.photo_or_text(chat, photo, text, kb):
                continue
        else:
            await n.send(chat, text, kb)


# ------------------------------------------------------------------ operations
@on("finance.operation_created")
async def operation_created(n: Notifier, d: dict):
    op, bal = d["operation"], d["balance"]
    card = op_text(op, bal)
    await channel(
        n, d, ("🌐 <i>Saytdan</i>\n" if d.get("from_site") else "") + card, op.get("receipt_file_id") or None
    )
    if d.get("notify_owner"):
        head = (
            "💸 Sizga pul berildi:\n\n"
            if op["kind"] == T.OP_INCOME
            else "ℹ️ Hamyoningizga yozildi:\n\n"
        )
        await n.send(d["owner_tg"], head + card, T.KB_STAFF)


@on("finance.operation_edited")
async def operation_edited(n: Notifier, d: dict):
    before = d.get("before") or {}
    old = f"{before.get('kind_label', '')} {money(before.get('amount'))} · {before.get('category_name', '')}"
    text = f"✏️ <b>Saytda o'zgartirildi</b> ({esc(d['by_name'])})\nAvval: {esc(old)}\n\n" + op_text(
        d["operation"], d["balance"]
    )
    await channel(n, d, text)
    await n.send(d["operation"]["member"]["telegram_id"], text)
    pair = d.get("pair")
    if pair:
        await n.send(
            pair["operation"]["member"]["telegram_id"],
            f"✏️ <b>O'tkazma saytda o'zgartirildi</b> ({esc(d['by_name'])})\n\n"
            + op_text(pair["operation"], pair["balance"]),
        )


@on("finance.operation_deleted")
async def operation_deleted(n: Notifier, d: dict):
    for t in (d.get("operations") or [])[:1]:
        await channel(n, d, f"🗑 <b>O'chirildi</b> ({esc(d['by_name'])})\n\n" + op_text(t))


@on("finance.receipt_attached")
async def receipt_attached(n: Notifier, d: dict):
    await channel(n, d, "📎 Chek qo'shildi\n\n" + op_text(d["operation"]), d.get("file_id"))


@on("finance.transfer_created")
async def transfer_created(n: Notifier, d: dict):
    out, inc = d["out"], d["inc"]
    await n.send(
        inc["member"]["telegram_id"],
        f"🔄 <b>{esc(out['member']['name'])}</b> sizga pul berdi:\n\n" + op_text(inc, d["inc_balance"]),
        T.kb_for(d.get("inc_member")),
    )
    text = (
        "⚠️ <b>Xodimlar o'rtasida pul berildi</b>\n👤 "
        + f"{esc(out['member']['name'])} → <b>{esc(inc['member']['name'])}</b>\n💵 <b>{money(out['amount'])}</b>"
        + (f"\n📝 {esc(out['comment'])}" if out.get("comment") else "")
        + f"\n🧾 #{out['number']} / #{inc['number']}"
    )
    await n.many(d.get("admins"), text)
    await channel(
        n,
        d,
        f"🔄 O'tkazma: {esc(out['member']['name'])} → {esc(inc['member']['name'])} · {money(out['amount'])}"
        + (f" · {esc(out['comment'])}" if out.get("comment") else ""),
    )


# ------------------------------------------------------------------ members
@on("finance.join_requested")
async def join_requested(n: Notifier, d: dict):
    m = d["member"]
    text = (
        f"🆕 Yangi xodim so'rovi: <b>{esc(m['name'])}</b> (@{esc(m.get('username') or '-')}, ID {m['telegram_id']})"
        + (f"\n🌐 Saytdagi profil: {esc(m['site_user'])}" if m.get("site_user") else "")
    )
    kb = ik(
        [
            [
                b("✅ Qabul qilish", f"approve:{m['telegram_id']}"),
                b("🚫 Rad etish", f"reject:{m['telegram_id']}"),
            ]
        ]
    )
    if d.get("admins"):
        await n.many(d["admins"], text, kb)
    else:
        await n.many(
            d.get("superusers"),
            text
            + "\n\n<i>Moliya botida hali rahbar yo'q — saytda Moliya → Telegram a'zolar bo'limida rol bering.</i>",
        )


@on("finance.member_approved")
async def member_approved(n: Notifier, d: dict):
    m = d["member"]
    await forget_whoami(m["telegram_id"])
    await n.send(
        m["telegram_id"],
        "✅ Rahbar sizni tasdiqladi! Endi kirim-chiqimlarni kiritishingiz mumkin.\n\n" + T.HELP_STAFF,
        T.KB_STAFF,
    )


@on("finance.duty_assigned")
async def duty_assigned(n: Notifier, d: dict):
    m = d["member"]
    await forget_whoami(m["telegram_id"])
    what = (
        "🌐 Saytga kirituvchi: mijozdan pul olinganda sizga xabar keladi — saytda «Полученная сумма» ni to'g'rilab, «✅ Saytga kiritdim» ni bosasiz."
        if d["duty"] == "is_site_entry"
        else "💬 Mijoz fikri: zakaz Готов bo'lganiga 3 kun bo'lganda sizga xabar keladi — mijozdan fikrini olib, «📝 Fikr oldim» ni bosib skrinshot yuborasiz."
    )
    await n.send(
        m["telegram_id"],
        f"👋 Sizga yangi vazifa berildi.\n\n{what}\n\n"
        + ("" if m["is_admin"] else "Siz kirim-chiqim kiritmaysiz, oylik hisob ham so'ralmaydi. ")
        + "«📋 Vazifalarim» — bajarilmagan ishlaringiz.",
        T.kb_for(m),
    )


# ------------------------------------------------------------------ requests, month
@on("finance.request_created")
async def request_created(n: Notifier, d: dict):
    req = d["request"]
    label = f"{num(req['orig_amount'])}$" if req["currency"] == "USD" else num(req["amount"])
    kb = ik(
        [
            [b(f"✅ {label} berdim", f"rq_ok:{req['number']}")],
            [
                b("✏️ Boshqa summa berdim", f"rq_amt:{req['number']}"),
                b("❌ Rad etish", f"rq_no:{req['number']}"),
            ],
        ]
    )
    text = T.req_admin_text(req)
    msgs = []
    for chat in dict.fromkeys(d.get("admins") or []):
        m = await n.send(chat, text, kb)
        if m is not None and m.message_id is not None:
            msgs.append([chat, m.message_id])
    if msgs:
        try:
            await backend.request(
                "POST",
                f"finance/requests/{req['number']}/admin-messages/",
                actor=req["member"]["telegram_id"],
                json={"messages": msgs},
            )
        except BackendError as e:
            logger.warning("admin-messages for #%s not stored: %s", req["number"], e)


@on("finance.request_answered")
async def request_answered(n: Notifier, d: dict):
    req, op = d["request"], d.get("operation")
    if d["status"] == "given" and op:
        shown = T.money_full(op["amount"], op["currency"], op.get("orig_amount"))
        line = f"✅ <b>Berildi: {shown}</b> ({esc(d['by_name'])})"
    else:
        line = f"❌ <b>Rad etildi</b> ({esc(d['by_name'])})"
    base = T.req_admin_text(req)
    for chat, mid in req.get("admin_messages") or []:
        await n.edit(chat, mid, base + "\n\n" + line)
    to = req["member"]["telegram_id"]
    if d["status"] == "given" and op:
        card = op_text(op, d["balance"])
        await n.send(to, f"💸 So'rovingiz #{req['number']} bo'yicha pul berildi:\n\n" + card, T.KB_STAFF)
        if d.get("post_to_channel"):
            await channel(n, d, card)
    else:
        await n.send(
            to,
            f"❌ Pul so'rovingiz #{req['number']} ({T.money_full(req['amount'], req['currency'], req.get('orig_amount'))}) rad etildi. Savol bo'lsa, rahbarga murojaat qiling.",
            T.KB_STAFF,
        )


@on("finance.month_submitted")
async def month_submitted(n: Notifier, d: dict):
    m = d["member"]
    text = (
        f"📤 <b>{esc(m['name'])}</b> oylik hisobni topshirdi.\n\n{T.month_text(d['summary'])}"
        + (f"\n📝 Izoh: {esc(d['note'])}" if d.get("note") else "")
    )
    await n.many(d.get("admins"), text)
    await channel(
        n,
        d,
        f"📤 {esc(m['name'])} — {month_full(d['month'])} hisobi topshirildi. Qoldiq: {money(d['closing'])}",
    )
    # the full month as xlsx: every operation, by category, by order
    ym = d["month"]
    for chat in dict.fromkeys(d.get("admins") or []):
        try:
            res = await backend.request(
                "GET",
                "finance/month-report/excel/",
                actor=chat,
                params={"month": ym, "member": m["telegram_id"]},
                raw=True,
            )
        except BackendError as e:
            logger.warning("month report excel %s/%s failed: %s", m["telegram_id"], ym, e)
            continue
        await n.document(
            chat,
            res.content,
            f"{m['name'].replace('/', '-')} {ym}.xlsx",
            f"📥 {m['name']} — {month_full(ym)} hisobi (Excel)",
        )


# ------------------------------------------------------------------ orders
@on("finance.manual_order_created")
async def manual_order_created(n: Notifier, d: dict):
    mo = d["order"]
    await channel(
        n,
        d,
        f"🆕 Yangi buyurtma <b>{esc(mo['ref'])}</b>\n👤 {esc(mo['client'])}"
        + (f"\n💼 {money(mo['price'])}" if D(mo.get("price")) else ""),
    )


@on("finance.manual_order_closed")
async def manual_order_closed(n: Notifier, d: dict):
    mo = d["order"]
    await channel(
        n,
        d,
        f"✅ <b>Buyurtma yopildi:</b> {esc(mo['ref'] + ' · ' + mo['client'])}\n🔴 Sarflandi: {money(d['spent'])}",
    )


# ------------------------------------------------------------------ money collected
@on("finance.handover_requested")
async def handover_requested(n: Notifier, d: dict):
    who = d["who"]
    await n.many(
        d.get("admins"),
        f"💵 <b>{esc(who)}</b> mijozdan pul oldi — pul hozir uning qo'lida\n🧾 <b>{esc(d['ref'])} · {esc(d['client'])}</b>\n💰 <b>{d['sum_text']}</b>\n🧮 Mijoz qoldig'i: {d['rest_text']}"
        f"\n\nPulni sizga topshirganda «✅ Pulni qabul qildim» ni bosing — {esc(who)} balansidan yechiladi va sizning kassangizga o'tadi.",
        K.handover_kb(d["operation"]["number"]),
    )


@on("finance.handover_resolved")
async def handover_resolved(n: Notifier, d: dict):
    op = d["operation"]
    client, sum_txt = esc(d["client"]), d["sum_text"]
    to = op["member"]["telegram_id"]
    if d["action"] == "drop":
        await n.send(
            to,
            f"🗑 Rahbar <b>{esc(op['order_ref'])} · {client}</b> bo'yicha {sum_txt} yozuvingizni o'chirdi (o'zi alohida kiritgan).\n💳 Hamyon: {money(d['member_balance'])}",
        )
    else:
        await n.send(
            to,
            f"✅ Rahbar <b>{esc(op['order_ref'])} · {client}</b> bo'yicha {sum_txt} ni qabul qildi.\n💳 Hamyoningiz: {money(d['member_balance'])}",
        )


@on("finance.warranty_given")
async def warranty_given(n: Notifier, d: dict):
    w = d["letter"]
    await n.many(
        d.get("admins"),
        f"📜 {esc(d['by_name'])} <b>{esc(w['order_ref'])} · {esc(w['client'])}</b> mijoziga kafolat xatini berdi.",
    )


@on("finance.site_entry_created")
async def site_entry_created(n: Notifier, d: dict):
    t = d["task"]
    await duty(
        n,
        d,
        f"🌐 <b>Saytga kiriting</b>\n🧾 <b>{esc(t['order_ref'])} · {esc(t['client'])}</b>"
        f"\n💰 {esc(d['collector_name'])} mijozdan oldi: <b>{esc(t['sum_text'])}</b>\n🧮 Yangi qoldiq: <b>{esc(t['rest_text'])}</b>"
        "\n\nSaytda shu zakazning «Полученная сумма» ni to'g'rilang, keyin tugmani bosing.",
        kb=K.site_done_kb(t["code"]),
    )


@on("finance.site_entry_done")
async def site_entry_done(n: Notifier, d: dict):
    t = d["task"]
    await n.many(
        d.get("admins"),
        f"🌐 ✅ <b>{esc(d['by_name'])}</b> saytga kiritdi\n🧾 <b>{esc(t['order_ref'])} · {esc(t['client'])}</b>"
        f"\n💰 {esc(t['sum_text'])} ({esc(t['taken_by'])} olgan)\n🧮 Qoldiq: {esc(t['rest_text'])}",
    )


@on("finance.feedback_received")
async def feedback_received(n: Notifier, d: dict):
    fb = d["feedback"]
    text = (
        f"💬 <b>Mijoz fikri olindi</b>\n🧾 <b>{esc(fb['order_ref'])} · {esc(fb['client'])}</b>\n👤 {esc(d['by_name'])}"
        + (f"\n📝 {esc(d['caption'])}" if d.get("caption") else "")
    )
    for chat in dict.fromkeys(d.get("admins") or []):
        if d.get("file_id"):
            await n.photo_or_text(chat, d["file_id"], text)
        else:
            await n.send(chat, text)


@on("finance.bonus_done")
async def bonus_done(n: Notifier, d: dict):
    text = T.bonus_done_text(d["bonus"])
    await duty(n, d, text)
    await n.many(d.get("also_admins"), text)


# ------------------------------------------------------------------ follow-up
async def _card_png(bn: dict, actor) -> bytes | None:
    """The backend wants a receiver/admin as actor: use the first recipient."""
    try:
        res = await backend.request(
            "GET",
            f"finance/bonuses/{bn['order_ref']}/card.png",
            actor=actor,
            params={"or_temp": 1},
            raw=True,
        )
        return res.content
    except BackendError:
        logger.warning("ready card %s not available", bn["order_ref"])
        return None


@on("finance.ready_card")
async def ready_card(n: Notifier, d: dict):
    bn = d["bonus"]
    ref = bn["order_ref"]
    png = await _card_png(bn, (d.get("to") or [None])[0])
    kb = ik(
        [[b("💰 Pul oldim", f"bpaid:{ref}")], [b("📜 Kafolat xati berdim", f"kfx:{ref}")]]
    )
    await duty(n, d, T.ready_text(bn, d["money_state"], d.get("usd_rate")), png, kb)


@on("finance.bonus_zero")
async def bonus_zero(n: Notifier, d: dict):
    bn, ms, days = d["bonus"], d["money_state"], d["days"]
    await duty(
        n,
        d,
        f"✅ <b>{esc(bn['order_ref'])} · {esc(bn['client'])}</b>\n🧮 Qoldiq 0 "
        f"({'saytda' if ms['src'] == 'sayt' else 'botda'}). Zakazni yopasizmi? "
        f"Bonus: <b>{float(D(d['percent'])):g}%</b> ({days} kun)",
        kb=ik([[b("✅ Zakazni yopish", f"bpok:{bn['order_ref']}")]]),
    )


@on("finance.bonus_term_reminder")
async def bonus_term_reminder(n: Notifier, d: dict):
    bn = d["bonus"]
    await duty(
        n,
        d,
        f"⏳ <b>Ertaga {d['label']} muddat tugaydi</b>\n🧾 {esc(bn['order_ref'])} · {esc(bn['client'])}"
        f"\n🧮 Qoldiq: <b>{fmt_cur(d['rest'], bn['currency'])} {cur_name(bn['currency'])}</b>"
        f"\n🎁 Bugun-ertaga to'liq yopilsa — {d['pct']}% bonus."
        "\n\n❗ Menejerlardan so'rang: yana pul qo'shilmaganmi?\n<i>Pulni olganingizda «💰 Pul oldim» ni bosing.</i>",
        kb=K.paid_kb(bn["order_ref"]),
    )


@on("finance.feedback_ask")
async def feedback_ask(n: Notifier, d: dict):
    fb = d["feedback"]
    await duty(
        n,
        d,
        f"💬 <b>Mijoz fikrini bilish kerak</b>\n🧾 <b>{esc(fb['order_ref'])} · {esc(fb['client'])}</b>"
        + (f"\n📞 {esc(fb['phone'])}" if fb.get("phone") else "")
        + f"\n📅 Готов: {ddmm(fb.get('ready_date'))} (3 kun o'tdi)\n\nMijozga qo'ng'iroq qiling yoki yozing, fikrini oling. "
        "Keyin «📝 Fikr oldim» ni bosib, <b>skrinshot</b> yuboring.",
        kb=K.feedback_kb(fb["order_ref"]),
    )


@on("finance.feedback_remind")
async def feedback_remind(n: Notifier, d: dict):
    fb = d["feedback"]
    await duty(
        n,
        d,
        f"⏰ <b>Eslatma: mijoz fikri hali olinmagan</b>\n🧾 <b>{esc(fb['order_ref'])} · {esc(fb['client'])}</b>"
        + (f"\n📞 {esc(fb['phone'])}" if fb.get("phone") else ""),
        kb=K.feedback_kb(fb["order_ref"]),
    )


@on("finance.site_entry_remind")
async def site_entry_remind(n: Notifier, d: dict):
    t = d["task"]
    await duty(
        n,
        d,
        f"⏰ <b>Eslatma: saytga hali kiritilmagan</b>\n🧾 <b>{esc(t['order_ref'])} · {esc(t['client'])}</b>"
        f"\n💰 {esc(t['sum_text'])}\n🧮 Qoldiq: {esc(t['rest_text'])}",
        kb=K.site_done_kb(t["code"]),
    )


@on("finance.deadline")
async def deadline(n: Notifier, d: dict):
    from urllib.parse import quote

    o, left = d["order"], d["left_days"]
    head = (
        f"🧾 <b>{esc(o['ref'])} · {esc(o['client'])}</b>\n📅 Topshirish sanasi: <b>{ddmm(o.get('end_date'))}</b>"
        + (f"\n📌 Holat: {esc(o['status_label'])}" if o.get("status_label") else "")
    )
    left_txt = "bugun" if left == 0 else f"{left} kun qoldi"
    if d["key"] == "3":
        q = quote(f"{o.get('address') or o['client']}, Toshkent")
        text = (
            f"📍 <b>Srok: {left_txt}</b>\n{head}\n📞 Telefon: {esc(o.get('phone') or '—')}\n🏠 Manzil: {esc(o.get('address') or '—')}"
            f'\n🗺 <a href="https://www.google.com/maps/search/?api=1&query={q}">Xaritada ochish</a>'
        )
    else:
        text = f"⏰ <b>Srok yaqinlashmoqda — {left_txt}</b>\n{head}"
    await duty(n, d, text)


# ------------------------------------------------------------------ scheduled jobs
@on("finance.daily_reminder")
async def daily_reminder(n: Notifier, d: dict):
    m = d["member"]
    await n.send(
        m["telegram_id"],
        f"📝 <b>{esc(m['name'])}</b>, bugungi kirim-chiqimlarni kiritdingizmi?\n💳 Hamyonda: {money(d['balance'])}",
        ik([[b("➖ Chiqim kiritish", "go:chiqim")], [b("✅ Bugun xarajat bo'lmadi", "noexp")]]),
    )


@on("finance.month_end_reminder")
async def month_end_reminder(n: Notifier, d: dict):
    left = d["left_days"]
    when = "bugun oyning oxirgi kuni" if left == 0 else f"oy tugashiga {left + 1} kun qoldi"
    await n.send(
        d["member"]["telegram_id"],
        f"📅 <b>Diqqat: {when}!</b>\n\n1) Barcha kirim-chiqimlarni kiriting\n2) «📤 Oylik hisob» tugmasi orqali hisobni topshiring\n\n💳 Hamyonda: {money(d['balance'])}",
        T.KB_STAFF,
    )


@on("finance.month_late")
async def month_late(n: Notifier, d: dict):
    await n.send(
        d["member"]["telegram_id"],
        f"⏰ <b>{month_full(d['month'])} hisobi hali topshirilmagan!</b>\n«📤 Oylik hisob» tugmasini bosing.",
        T.KB_STAFF,
    )


@on("finance.month_late_admins")
async def month_late_admins(n: Notifier, d: dict):
    await n.many(
        d.get("admins"),
        f"⏰ {month_full(d['month'])} hisobini topshirmaganlar:\n"
        + "\n".join(f"• {esc(x)}" for x in d["names"]),
    )


@on("finance.admin_daily")
async def admin_daily(n: Notifier, d: dict):
    sm = d["summary"]
    lines = [
        f"🌙 <b>Kun yakuni · {ddmm(d['date'])}</b>",
        "",
        f"🔴 Xarajat: <b>{num(-float(sm['expense']))}</b>",
        f"🟢 Daromad: <b>{num(sm['income'])}</b>",
        f"💸 Xodimlarga berildi: {num(sm['given_to_staff'])}",
        f"📝 Amallar: {d['ops_count']}",
    ]
    if float(sm["boss_personal"]):
        lines.append(f"👔 Rahbar xarajatlari (alohida): {num(sm['boss_personal'])}")
    if float(sm["home"]):
        lines.append(f"🏠 Uy uchun (alohida): {num(sm['home'])}")
    if d.get("by_member"):
        lines += ["", "<b>Kim qancha sarfladi:</b>"] + [
            f"• {esc(x['name'])} — {num(x['sum'])}" for x in d["by_member"]
        ]
    if d.get("silent"):
        lines += ["", "😶 Bugun yozmaganlar: " + ", ".join(esc(x) for x in d["silent"])]
    ch = d.get("checks") or {}
    if ch.get("count"):
        lines += [
            "",
            f"🔍 Tekshiruv: {ch['count']} ta kamchilik"
            + (f", 🔴 {ch['high']} ta jiddiy" if ch.get("high") else "")
            + " — «🔍 Tekshiruv» tugmasi",
        ]
    await n.many(
        d.get("admins"), "\n".join(lines), ik([[b("📊 Oy ma'lumoti", f"inf:all:{d['month']}:x")]])
    )


@on("finance.month_excel")
async def month_excel(n: Notifier, d: dict):
    ym = d["month"]
    for chat in dict.fromkeys(d.get("admins") or []):
        try:
            res = await backend.request(
                "GET", "finance/excel/", actor=chat, params={"month": ym}, raw=True
            )
        except BackendError as e:
            logger.warning("excel for %s failed: %s", ym, e)
            await n.send(chat, f"❗ {month_full(ym)} Excel faylini tayyorlab bo'lmadi. Keyinroq «📥 Excel» tugmasini bosing.")
            continue
        await n.document(
            chat, res.content, res.filename or f"SerMebel-{ym}.xlsx", f"📥 {month_full(ym)} — oylik hisobot"
        )


__all__ = ["add_months"]
