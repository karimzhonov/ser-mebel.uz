"""The button dispatcher (port of on_callback): one handler, `callback_data` strings are
the old bot's, so buttons in old chat messages keep working."""

from __future__ import annotations

from bot.backend.client import NotFound
from bot.common.fmt import esc
from bot.common.kb import CANCEL, b, grid, ik
from bot.finance import api as A
from bot.finance import texts as T
from bot.finance.ctx import Ctx
from bot.finance.handlers import bonus as BN
from bot.finance.handlers import menu as MN
from bot.finance.handlers import requests as RQ
from bot.finance.handlers import tasks as TK
from bot.finance.handlers import tx as TX
from bot.finance.handlers import views as V
from bot.finance.texts import OP_EXPENSE, OP_INCOME


async def cancel_flow(ctx: Ctx):
    ids = list(ctx.flow0)
    if ctx.cb_msg:
        ids.append(ctx.cb_msg)
    await ctx.clr_st()
    ctx.done = True  # nothing of this update is remembered for a later cancel
    ok = 0
    for mid in dict.fromkeys(i for i in ids if i):
        if await ctx.delete(mid):
            ok += 1
    if not ok:
        await ctx.show("❌ Bekor qilindi.")


async def on_callback(ctx: Ctx, data: str):
    p = data.split(":")
    cmd, arg = p[0], ":".join(p[1:])
    if cmd == "join":
        return await MN.join(ctx)
    if not ctx.active:
        return
    d = await ctx.st()

    if cmd == "cancel":
        return await cancel_flow(ctx)
    if cmd in ("bpaid", "bpok", "bpf", "bpq"):
        return await BN.bonus_paid_btn(ctx, cmd, arg)
    if cmd == "kfx":
        return await BN.kafolat_give(ctx, arg, True)
    if cmd == "skt":
        return await TK.sayt_done(ctx, arg)
    if cmd in ("pqk", "pqd"):
        return await BN.handover_do(ctx, cmd, int(arg))
    if cmd == "fko":
        return await TK.fikr_btn(ctx, arg)
    if cmd == "rol":
        return await TK.role_set(ctx, arg)
    if cmd == "tst":
        return await ctx.send(
            "🧪 Namuna. Bu tugma «✅ To'liq oldim — qoldiq» yoki «➗ Qisman oldim» ni so'raydi."
            if arg == "pul"
            else "🧪 Namuna. Bu tugma «Kafolat xatlari» ga ✅ Berildi deb yozadi."
        )
    # --- the draft's own buttons
    if cmd == "skip":
        if await TX.skip_callback(ctx, arg, d):
            return
        if d:
            step = d.get("step")
            if arg == "reason" and step == "req_reason":
                await ctx.show("⏭ Sababsiz")
                return await RQ.req_send(ctx, d)
            if arg == "trcom" and step == "tr_com":
                await ctx.show("⏭ Izohsiz")
                d["com"] = ""
                return await RQ.tr_confirm(ctx, d)
            if await V.orders_callback(ctx, cmd, arg, d):
                return
        return
    if await TX.tx_callback(ctx, cmd, arg, d):
        return
    # --- operations
    if cmd == "rcpt":
        return await TX.receipt_start(ctx, int(arg))
    if cmd == "del":
        return await TX.ask_delete(ctx, int(arg))
    if cmd == "delok":
        return await TX.delete_ok(ctx, int(arg))
    # --- views
    if cmd == "inf":
        return await V.info(ctx, p[1], p[2], p[3] if len(p) > 3 else "x")
    if cmd == "ops":
        return await V.ops(ctx, p[1], p[2], int(p[3]) if len(p) > 3 else 0)
    if cmd == "mon":
        return await V.months_view(ctx, p[1])
    if cmd in ("ocard", "oclosed"):
        return await V.orders_callback(ctx, cmd, arg, d)
    # --- month report
    if cmd == "msub" and d and d.get("step") == "month_confirm":
        await ctx.clear_kb()
        return await RQ.month_submit(ctx, d)
    if cmd == "mnote" and d and d.get("step") == "month_confirm":
        d["step"] = "month_note"
        await ctx.set_st(d)
        return await ctx.send(
            "📝 Izohingizni yozing (masalan: «200 ming naqd rahbarga qaytardim»):"
        )
    if cmd == "noexp":
        return await ctx.show("👍 Qabul qilindi. Rahmat!")
    if cmd == "trto":
        return await RQ.tr_pick(ctx, arg)
    if cmd == "trok" and d and d.get("step") == "tr_confirm":
        return await RQ.tr_save(ctx, d)
    if cmd == "go" and arg == "req":
        await ctx.clear_kb()
        return await RQ.req_start(ctx)
    if cmd == "go":
        await ctx.clear_kb()
        return await TX.start_tx(ctx, OP_EXPENSE, ctx.member)
    if cmd in ("rq_ok", "rq_amt", "rq_no"):
        if not ctx.admin:
            return
        return await RQ.req_answer(ctx, cmd, int(arg))

    if not ctx.admin:
        return
    # --- admin only
    if await V.orders_callback(ctx, cmd, arg, d):
        return
    if cmd == "oimg":
        if not await A.order_info(ctx, arg):
            return
        await ctx.send("⏳ Rasm tayyorlanmoqda…")
        return await BN.send_ready_card(ctx, arg)
    if cmd == "give":
        u = await A.member(ctx, arg)
        if not u:
            return
        await ctx.show(f"💸 {esc(u['name'])} ga")
        nd = TX.new_draft(OP_INCOME, u["telegram_id"], u["name"], ctx.tg_id)
        nd.update(oa=True, ra=True, give=True)
        return await TX.next_step(ctx, nd)
    if cmd == "who":
        wallets = await ctx.get("finance/members/", set="wallets")
        return await ctx.send(
            "👤 Kimning hamyoni?",
            ik(grid([b(u["name"][:22], f"inf:{u['telegram_id']}:{arg}:x") for u in wallets], 2)),
        )
    if cmd == "xls":
        return await V.send_excel(ctx, arg)
    if cmd == "nudge":
        u = await A.member(ctx, arg)
        sent = await ctx.dm(
            arg,
            "🔔 Rahbar eslatmasi: iltimos, barcha kirim-chiqimlarni kiriting va kerak bo'lsa oylik hisobni topshiring.",
            T.kb_for(u),
        )
        return await ctx.send(
            "🔔 Eslatma yuborildi."
            if sent
            else "❗ Yuborib bo'lmadi (xodim botni bloklagan bo'lishi mumkin)."
        )
    if cmd in ("approve", "reject"):
        try:
            u = await ctx.api(
                "POST",
                f"finance/members/{arg}/role/",
                json={"role": "staff" if cmd == "approve" else "blocked"},
            )
        except NotFound:
            return
        # the new member gets «Rahbar sizni tasdiqladi» from finance.member_approved
        return await ctx.show(
            ("✅ Qabul qilindi: " if cmd == "approve" else "🚫 Rad etildi: ") + esc(u["name"])
        )


__all__ = ["CANCEL", "OP_EXPENSE", "on_callback"]
