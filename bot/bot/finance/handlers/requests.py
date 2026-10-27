"""Money requests (staff -> boss), transfers between staff and the monthly report."""

from __future__ import annotations

from bot.backend.client import NotFound, ServiceRefusal
from bot.common.fmt import esc, money
from bot.common.kb import CANCEL, b, grid, ik
from bot.finance import api as A
from bot.finance import texts as T
from bot.finance.ctx import Ctx
from bot.finance.handlers.tx import op_text

AMOUNT_ERR = "❗ Summani tushunmadim. Masalan: 500000, 1.5 mln yoki 300$"


async def check_amount(ctx: Ctx, text: str) -> dict | None:
    """The backend's parser: the amount dict, or None after telling the user."""
    try:
        res = await ctx.api("POST", "finance/parse/", json={"text": text, "mode": "money"})
    except ServiceRefusal as e:
        await ctx.send(f"❗ {esc(e.detail)}")
        return None
    if not res:
        await ctx.send(AMOUNT_ERR)
        return None
    return res


# ====================================================================== money requests
async def req_start(ctx: Ctx):
    bal = await A.balance(ctx, ctx.tg_id)
    await ctx.set_st({"step": "req_amount"})
    await ctx.send(
        f"🙏 <b>Rahbardan pul so'rash</b>\n💳 Hamyoningizda hozir: <b>{money(bal)}</b>\n\n💵 Qancha kerak? Summani yozing:\n<i>masalan: 500000, 1.5 mln yoki 300$</i>",
        ik([[CANCEL]]),
    )


async def req_text(ctx: Ctx, d: dict, step: str, text: str):
    if step == "req_amount":
        if not await check_amount(ctx, text):
            return
        d.update(amount_text=text, step="req_reason")
        await ctx.set_st(d)
        return await ctx.send(
            "📝 Nima uchun kerak? Qisqa yozing (masalan: «406 zakazga LDSP», «ustalarga avans»):",
            ik([[b("⏭ O'tkazib yuborish", "skip:reason")], [CANCEL]]),
        )
    if step == "req_reason":
        d["reason"] = text[:300]
        return await req_send(ctx, d)
    if step == "req_custom":
        if not await check_amount(ctx, text):
            return
        await ctx.clr_st()
        return await req_give(ctx, d["req"], text)


async def req_send(ctx: Ctx, d: dict):
    await ctx.clr_st()
    req = await ctx.api(
        "POST",
        "finance/requests/",
        json={"amount_text": d["amount_text"], "reason": d.get("reason") or ""},
    )
    # the admins' messages (with the «berdim» buttons) come from the finance.request_created event
    await ctx.send(
        f"✅ So'rovingiz rahbarga yuborildi (#{req['number']}).\n💵 {T.money_full(req['amount'], req['currency'], req.get('orig_amount'))}"
        + (f"\n📝 {esc(req['reason'])}" if req.get("reason") else "")
        + "\n\nRahbar pul berganda hamyoningizga o'zi yoziladi va sizga xabar keladi.",
        T.kb_for(ctx.member),
    )


async def req_answer(ctx: Ctx, cmd: str, number: int):
    try:
        req = await ctx.get(f"finance/requests/{number}/")
    except NotFound:
        return await ctx.send("❗ So'rov topilmadi.")
    if req["status"] != "pending":
        return await ctx.send(f"ℹ️ Bu so'rovga allaqachon javob berilgan: {req['answer']}")
    if cmd == "rq_ok":
        return await req_give(ctx, number, None)
    if cmd == "rq_amt":
        await ctx.set_st({"step": "req_custom", "req": number})
        return await ctx.send(
            f"✏️ {esc(req['member']['name'])} ga qancha berdingiz? Summani yozing (so'mda yoki $ da, masalan 250$):",
            ik([[CANCEL]]),
        )
    if cmd == "rq_no":
        # the admins' messages are closed and the member told by finance.request_answered
        await ctx.api("POST", f"finance/requests/{number}/reject/")


async def req_give(ctx: Ctx, number: int, amount_text: str | None):
    res = await ctx.api(
        "POST", f"finance/requests/{number}/give/", json={"amount_text": amount_text}
    )
    op, req = res["operation"], res["request"]
    shown = T.money_full(op["amount"], op["currency"], op.get("orig_amount"))
    await ctx.send(
        f"✅ Yozildi: {esc(req['member']['name'])} ga {shown}. Hamyonida: {money(res['balance'])}"
    )


# ====================================================================== transfers
async def tr_start(ctx: Ctx):
    wallets = await ctx.get("finance/members/", set="wallets")
    lst = [u for u in wallets if u["telegram_id"] != ctx.tg_id]
    if not lst:
        return await ctx.send("Boshqa xodim yo'q.")
    bal = await A.balance(ctx, ctx.tg_id)
    await ctx.send(
        f"🔄 Kimga pul berdingiz?\n💳 Hamyoningizda: <b>{money(bal)}</b>",
        ik(
            grid(
                [
                    b(("👔 " if u["is_admin"] else "👤 ") + u["name"][:22], f"trto:{u['telegram_id']}")
                    for u in lst
                ],
                2,
            )
            + [[CANCEL]]
        ),
    )


async def tr_pick(ctx: Ctx, tg: str):
    wallets = await ctx.get("finance/members/", set="wallets")
    to = next((u for u in wallets if str(u["telegram_id"]) == tg), None)
    if not to or not to["has_wallet"] or to["telegram_id"] == ctx.tg_id:
        return
    await ctx.set_st({"step": "tr_amount", "to": to["telegram_id"], "toName": to["name"]})
    await ctx.show(
        f"🔄 <b>{esc(to['name'])}</b> ga qancha berdingiz? Summani yozing:", ik([[CANCEL]])
    )


async def tr_text(ctx: Ctx, d: dict, step: str, text: str):
    if step == "tr_amount":
        try:
            res = await ctx.api("POST", "finance/parse/", json={"text": text, "mode": "money"})
        except ServiceRefusal:
            res = None
        if not res or res["cur"] == "USD":
            return await ctx.send("❗ Summani tushunmadim. Masalan: 300000 yoki 1.5 mln")
        d.update(amount=str(round(float(res["amount"]))), step="tr_com")
        await ctx.set_st(d)
        return await ctx.send(
            "📝 Nima uchun berdingiz? (masalan: «zapravkaga», «406 ga material»):",
            ik([[b("⏭ O'tkazib yuborish", "skip:trcom")], [CANCEL]]),
        )
    if step == "tr_com":
        d["com"] = text[:300]
        return await tr_confirm(ctx, d)
    await ctx.send("«✅ Tasdiqlash» tugmasini bosing yoki /bekor.")


async def tr_confirm(ctx: Ctx, d: dict):
    d["step"] = "tr_confirm"
    await ctx.set_st(d)
    bal = await A.balance(ctx, ctx.tg_id)
    left = bal - A.D(d["amount"])
    await ctx.send(
        f"<b>🔄 Pul berish — tekshiring:</b>\n\n👤 {esc(ctx.name)} → <b>{esc(d['toName'])}</b>\n💵 <b>{money(d['amount'])}</b>"
        + (f"\n📝 {esc(d['com'])}" if d.get("com") else "")
        + f"\n💳 Sizda qoladi: {money(left)}{' ⚠️' if left < 0 else ''}"
        + "\n\n<i>Rahbarga xabar boradi.</i>",
        ik([[b("✅ Tasdiqlash", "trok")], [CANCEL]]),
    )


async def tr_save(ctx: Ctx, d: dict):
    await ctx.clr_st()
    res = await ctx.api(
        "POST",
        "finance/transfers/",
        json={"to_tg": d["to"], "amount": d["amount"], "comment": d.get("com") or ""},
    )
    await ctx.show("✅ Yozildi!\n\n" + await op_text(ctx, res["out"], res["balance"]))


# ====================================================================== monthly report
async def month_start(ctx: Ctx):
    sm = await ctx.get("finance/month-report/")
    ym = sm["month"]
    text = T.month_text(sm)
    if sm.get("submitted"):
        text += "\n\n✅ Bu oy hisobi topshirilgan. Qayta topshirish mumkin."
    await ctx.set_st({"step": "month_confirm", "month": ym, "summary": text})
    await ctx.send(
        text + "\n\nHamma kirim-chiqim kiritilgan bo'lsa, tasdiqlang:",
        ik(
            [
                [b("✅ Tasdiqlayman, topshirish", "msub")],
                [b("📝 Izoh bilan topshirish", "mnote")],
                [CANCEL],
            ]
        ),
    )


async def month_submit(ctx: Ctx, d: dict):
    await ctx.clr_st()
    await ctx.api(
        "POST", "finance/month-report/", json={"month": d["month"], "note": d.get("note") or ""}
    )
    # the admins and the channel are told by finance.month_submitted
    await ctx.send("✅ Oylik hisob topshirildi. Rahmat!", T.kb_for(ctx.member))


async def month_note_text(ctx: Ctx, d: dict, text: str):
    d["note"] = text[:300]
    await month_submit(ctx, d)
