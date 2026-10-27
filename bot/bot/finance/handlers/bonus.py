"""«Pul oldim» (client money collected for a «Готов» order), handover to the boss,
warranty letters and the payment sheet."""

from __future__ import annotations

import logging

from bot.backend.client import BackendError, NotFound, RawResponse
from bot.common.fmt import cur_name, ddmm, esc, fmt_cur, money, num
from bot.common.kb import CANCEL, b, ik
from bot.finance import keyboards as K
from bot.finance import texts as T
from bot.finance.api import D
from bot.finance.ctx import Ctx
from bot.finance.handlers.requests import check_amount

logger = logging.getLogger(__name__)

NOT_RECEIVER = "ℹ️ Bu tugma faqat bonus oluvchi va rahbar uchun."


def is_receiver(ctx: Ctx) -> bool:
    return ctx.admin or bool((ctx.member or {}).get("is_bonus_receiver"))


async def _waiting_bonus(ctx: Ctx, ref: str) -> dict | None:
    """GET finance/bonuses/{ref}/ when the bonus is still waiting, else None."""
    try:
        res = await ctx.get(f"finance/bonuses/{ref}/")
    except NotFound:
        return None
    return res if res["bonus"]["status"] == "waiting" else None


async def bonus_paid_btn(ctx: Ctx, cmd: str, ref: str):
    if not is_receiver(ctx):
        return await ctx.send(NOT_RECEIVER)
    res = await _waiting_bonus(ctx, ref)
    if not res:
        return await ctx.send(
            f"ℹ️ {esc(ref)} zakazi bo'yicha bonus allaqachon yopilgan (yoki 30 kundan o'tgan)."
        )
    bn, ms = res["bonus"], res["money_state"]
    c = bn["currency"]
    rest = D(ms["rest"])
    tol = D(res["tolerance"])
    if cmd == "bpaid":
        return await ctx.send(
            f"💰 <b>{esc(ref)} · {esc(bn['client'])}</b>\n🧮 Qoldiq: <b>{fmt_cur(rest, c)} {cur_name(c)}</b> ({'saytdan' if ms['src'] == 'sayt' else 'botdan'})\n\nMijozdan qancha oldingiz?",
            ik(
                [
                    [b(f"✅ To'liq oldim — {fmt_cur(rest, c)} {cur_name(c)}", f"bpf:{ref}")],
                    [b("➗ Qisman oldim (summa yozaman)", f"bpq:{ref}")],
                    [CANCEL],
                ]
            ),
        )
    if cmd == "bpq":
        await ctx.set_st({"step": "bpay", "id": ref})
        return await ctx.send(
            f"➗ <b>{esc(ref)}</b> — qancha oldingiz? Summani yozing (so'mda yoki $ da, masalan <code>{'500$' if c == 'USD' else '5000000'}</code>):",
            ik([[CANCEL]]),
        )
    if cmd == "bpf":
        await ctx.clear_kb()
        if rest <= tol:
            return await ctx.api("POST", f"finance/bonuses/{ref}/close/")
        return await bonus_collect(
            ctx, ref, f"{rest}$" if c == "USD" else str(round(rest)), full=True
        )
    if cmd == "bpok":
        if rest > tol:
            return await ctx.send(
                f"❗ Qoldiq hali <b>{fmt_cur(rest, c)} {cur_name(c)}</b> — zakazni faqat qoldiq 0 bo'lganda yopish mumkin. Olgan pulingizni «💰 Pul oldim» orqali kiriting.",
                K.paid_kb(ref),
            )
        await ctx.clear_kb()
        await ctx.api("POST", f"finance/bonuses/{ref}/close/")


async def bonus_pay_text(ctx: Ctx, d: dict, text: str):
    ref = d["id"]
    if not await _waiting_bonus(ctx, ref):
        await ctx.clr_st()
        return await ctx.send("ℹ️ Bu zakaz bo'yicha bonus allaqachon yopilgan.")
    if not await check_amount(ctx, text):
        return
    await ctx.clr_st()
    await bonus_collect(ctx, ref, text, full=False)


async def bonus_collect(ctx: Ctx, ref: str, amount_text: str, full: bool):
    """POST collect: the backend books the money, makes the site-entry task and emits
    the notices (site entry, handover ask, bonus done)."""
    res = await ctx.api(
        "POST",
        f"finance/bonuses/{ref}/collect/",
        json={"amount_text": amount_text, "full": full},
    )
    bn = res["bonus"]
    head = (
        f"✅ Yozildi: {esc(res['sum_text'])}\n🧾 {esc(bn['order_ref'])} · {esc(bn['client'])}"
    )
    if res["full"]:
        return await ctx.send(head + "\n🧮 Qoldiq: <b>0</b> — zakaz yopildi.")
    await ctx.send(
        head
        + f"\n🧮 Qolgan qoldiq: <b>{esc(res['rest_text'])}</b>\n\nQolganini olganingizda yana «💰 Pul oldim» ni bosing.",
        K.paid_kb(bn["order_ref"]),
    )


# ====================================================================== handover (/topshiruv)
async def handover_list(ctx: Ctx):
    lst = await ctx.get("finance/handover/")
    if not lst:
        return await ctx.send(
            "✅ Topshirilmagan pul yo'q — «Pul oldim» orqali olingan hamma pul qabul qilingan yoki belgilangan."
        )
    total = sum(D(t["amount"]) for t in lst)
    await ctx.send(
        f"💵 <b>Rahbarga hali topshirilmagan pullar</b> ({len(lst)} ta, jami {money(total)})\nHar biri uchun tanlang:\n• ✅ qabul qildim — xodim balansidan yechiladi, kassangizga o'tadi\n• 🗑 alohida kiritganman — bu yozuv o'chiriladi (ikki marta hisoblanmasin)"
    )
    for t in lst[:20]:
        amount = (
            f"{num(t['orig_amount'])} $ ({money(t['amount'])})"
            if t["currency"] == "USD"
            else money(t["amount"])
        )
        await ctx.send(
            f"🧾 #{t['number']} · {ddmm(t['date'])}\n👤 {esc(t['member']['name'])} · zakaz <b>{esc(t['order_ref'])}</b>\n💰 <b>{amount}</b>",
            K.handover_kb(t["number"]),
        )


async def handover_do(ctx: Ctx, cmd: str, number: int):
    if not ctx.admin:
        return await ctx.send("ℹ️ Bu tugma faqat rahbar uchun.")
    await ctx.clear_kb()
    try:
        res = await ctx.api("POST", f"finance/handover/{number}/{'drop' if cmd == 'pqd' else 'accept'}/")
    except NotFound:
        return await ctx.send(f"ℹ️ #{number} yozuvi topilmadi yoki o'chirilgan.")
    op = res["operation"]
    name, sum_txt, client = esc(op["member"]["name"]), esc(res["sum_text"]), esc(res["client"])
    if cmd == "pqd":
        return await ctx.send(
            f"🗑 #{op['number']} o'chirildi — {name} balansidan {sum_txt} olib tashlandi. Mijoz to'lovi sizning yozuvingiz bo'yicha hisoblanadi."
        )
    await ctx.send(
        f"✅ Qabul qilindi: {sum_txt} — {esc(op['order_ref'])} · {client}\n👤 {name} balansidan yechildi, kassangizga o'tdi."
    )


# ====================================================================== kafolat
async def kafolat_give(ctx: Ctx, ref: str, from_btn: bool):
    if not is_receiver(ctx):
        return await ctx.send(NOT_RECEIVER)
    w = await ctx.api("POST", f"finance/warranty/{ref}/give/")
    if from_btn:
        await ctx.clear_kb(ik([[b("💰 Pul oldim", f"bpaid:{w['order_ref']}")]]))
    await ctx.send(
        f"📜 ✅ Kafolat xati berildi: <b>{esc(w['order_ref'])} · {esc(w['client'])}</b>\n<i>«Kafolat xatlari» bo'limiga yozildi.</i>"
    )


async def kafolat_list(ctx: Ctx):
    rows = await ctx.get("finance/warranty/", given="0")
    if not rows:
        return await ctx.send("📜 Hamma Готов mijozlarga kafolat xati berilgan ✅")
    await ctx.send(
        f"📜 <b>Kafolat xati berilmaganlar</b> ({len(rows)}):\n"
        + "\n".join(f"• {esc(r['order_ref'])} · {esc(r['client'])}" for r in rows[:40])
        + "\n\nBerganingizda: <code>/kafolat 389</code>",
        ik([[b(f"📜 {r['order_ref']} · {r['client'][:22]} — berdim", f"kfx:{r['order_ref']}")] for r in rows[:20]]),
    )


# ====================================================================== payment sheet (Готов)
async def fetch_card(ctx: Ctx, ref: str) -> bytes | None:
    try:
        res: RawResponse = await ctx.api(
            "GET", f"finance/bonuses/{ref}/card.png", params={"or_temp": 1}, raw=True
        )
        return res.content
    except BackendError:
        logger.exception("report card %s", ref)
        return None


async def send_ready_card(ctx: Ctx, ref: str, test: bool = False):
    """The «Готов» sheet to this chat (order card button, /umidtest)."""
    res = await ctx.get(f"finance/bonuses/{ref}/", or_temp=1)
    png = await fetch_card(ctx, ref)
    text = T.ready_text(res["bonus"], res["money_state"], res["usd_rate"])
    if test:
        kb = ik([[b("💰 Pul oldim", "tst:pul")], [b("📜 Kafolat xati berdim", "tst:kfx")]])
        await ctx.send("🧪 <b>TEST</b> — bonus oluvchiga aynan quyidagi xabar boradi:")
        if png and await ctx.photo(png, text, kb):
            return
        return await ctx.send(text, kb)
    if png and await ctx.photo(png, text):
        return
    await ctx.send(text)
