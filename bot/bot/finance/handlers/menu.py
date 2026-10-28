"""Entry points of the finance bot: the start/join screens, commands, menu buttons, free
text (quick entry and the answers of the running flow) and photos."""

from __future__ import annotations

import re

from aiogram import Bot
from aiogram.fsm.context import FSMContext

from bot.backend.client import NotFound
from bot.common.actor import Actor
from bot.common.fmt import cur_month, esc, money
from bot.common.kb import b, ik
from bot.finance import api as A
from bot.finance import texts as T
from bot.finance.ctx import Ctx, run
from bot.finance.handlers import bonus as BN
from bot.finance.handlers import requests as RQ
from bot.finance.handlers import tasks as TK
from bot.finance.handlers import tx as TX
from bot.finance.handlers import views as V
from bot.finance.texts import OP_EXPENSE, OP_INCOME

JOIN_COMMAND = "/moliya"  # alias of /start


def full_name(user) -> str:
    return (
        " ".join(x for x in [user.first_name, user.last_name] if x)
        or user.username
        or str(user.id)
    )


# ====================================================================== start / join
async def start(ctx: Ctx) -> bool:
    """The finance start screen. False when the sender is not a usable member
    (the caller decides what to do then)."""
    m = ctx.member
    if not m:
        await ctx.send(T.JOIN_TEXT, ik([[b("✅ Ro'yxatdan o'tish", "join")]]))
        return True
    if m["role"] == "pending":
        await ctx.send("⏳ So'rovingiz rahbar tomonidan hali tasdiqlanmagan.")
        return True
    if not ctx.active:
        return False
    await ctx.clr_st()
    if m["is_task_only"]:
        await ctx.send(
            f"Assalomu alaykum, {esc(m['name'])}! 👋\n\n{T.task_role_text(m)}\n\n«📋 Vazifalarim» — bajarilmagan ishlaringiz.",
            T.KB_TASK,
        )
        return True
    bal = await A.balance(ctx, ctx.tg_id)
    await ctx.send(
        f"Assalomu alaykum, {esc(m['name'])}! 👋\nPastdagi tugmalardan foydalaning.\n\n💳 Hamyon: <b>{money(bal)}</b>",
        T.kb_for(m),
    )
    return True


async def finance_start(message, state: FSMContext, actor: Actor, bot: Bot) -> bool:
    """Called by common/start.py (plain /start, /moliya)."""
    ctx = Ctx(bot, actor, state, message.chat.id, msg=message)
    await ctx.load()
    return bool(await run(ctx, start(ctx)))


async def join(ctx: Ctx):
    res = await ctx.api(
        "POST",
        "finance/join/",
        json={"name": full_name(ctx.actor.user), "username": ctx.actor.user.username or ""},
    )
    m = res["member"]
    if not res["created"]:
        return await ctx.show(
            "⏳ So'rovingiz yuborilgan. Rahbar tasdiqlashini kuting."
            if m["role"] == "pending"
            else "Siz allaqachon ro'yxatdasiz. /start"
        )
    # the admins' «Qabul qilish» messages come from finance.join_requested
    await ctx.show("✅ So'rovingiz rahbarga yuborildi. Tasdiqlangach xabar keladi.")


# ====================================================================== commands
async def on_command(ctx: Ctx, text: str):
    parts = text.split()
    cmd, args = parts[0].split("@")[0].lower(), parts[1:]
    if cmd == "/myid":
        return await ctx.send(f"Sizning Telegram ID: <code>{ctx.uid}</code>")
    if not ctx.active:
        await start(ctx)
        return
    m = ctx.member
    if cmd in ("/yordam", "/help"):
        await ctx.send(
            (T.HELP_ADMIN if ctx.admin else (T.task_role_text(m) if m["is_task_only"] else T.HELP_STAFF))
            + T.ver_line(),
            T.kb_for(m),
        )
    elif cmd in ("/bekor", "/cancel"):
        await ctx.clr_st()
        await ctx.send("Bekor qilindi.", T.kb_for(m))
    elif cmd == "/kafolat" and BN.is_receiver(ctx):
        if args:
            await BN.kafolat_give(ctx, args[0], False)
        else:
            await BN.kafolat_list(ctx)
    elif m["is_task_only"] and not ctx.admin:
        await ctx.send(T.task_role_text(m), T.KB_TASK)
    elif cmd == "/ochir":
        n = re.sub(r"\D", "", args[0]) if args else ""
        if not n:
            await ctx.send("Masalan: /ochir 25")
        else:
            await TX.ask_delete(ctx, int(n))
    elif cmd == "/id":
        if args:
            await V.order_card(ctx, " ".join(args))
        else:
            await V.show_orders(ctx)
    elif ctx.admin and cmd == "/ism":
        target = await A.member(ctx, args[0]) if args else None
        if len(args) < 2 or not target:
            await ctx.send("Masalan: /ism 123456789 Jasur (zakupshik)")
        else:
            await ctx.api(
                "POST",
                f"finance/members/{target['telegram_id']}/name/",
                json={"name": " ".join(args[1:])[:255]},
            )
            await ctx.send("✅ Ism o'zgartirildi.")
    elif ctx.admin and cmd == "/kurs":
        try:
            v = float("".join(args).replace(",", ".") or 0)
        except ValueError:
            v = 0
        cfg = await ctx.api("PUT", "finance/config/usd-rate/", json={"rate": str(v)})
        await A.drop_cache("config")
        await ctx.send(
            f"💱 Dollar kursi: 1 USD = {money(v)}"
            if v
            else f"💱 Markaziy bank kursi ishlatiladi: 1 USD = {money(cfg['usd_rate'])}"
        )
    elif ctx.admin and cmd == "/topshiruv":
        await BN.handover_list(ctx)
    elif ctx.admin and cmd == "/saytchi":
        await TK.role_pick(ctx, "is_site_entry", "🌐 Saytga kirituvchi menejer")
    elif ctx.admin and cmd == "/fikrchi":
        await TK.role_pick(ctx, "is_feedback", "💬 Mijoz fikri menejeri")
    elif ctx.admin and cmd == "/shablon":
        if args:
            await TK.tpl_reset(ctx)
        else:
            await TK.tpl_start(ctx)
    elif ctx.admin and cmd == "/umidtest":
        if not args:
            await ctx.send(
                "Masalan: <code>/umidtest 389</code> — bonus oluvchiga boradigan Готов xabarini sizga yuboradi (hech narsa yozilmaydi)."
            )
        elif not await A.order_info(ctx, args[0]):
            await ctx.send(f"❗ {esc(args[0])} buyurtmalarda topilmadi.")
        else:
            await ctx.send("⏳ Rasm tayyorlanmoqda…")
            await BN.send_ready_card(ctx, args[0], test=True)
    else:
        await ctx.send("Bunday buyruq yo'q. /yordam", T.kb_for(m))


# ====================================================================== menu buttons
MENU_STAFF = {
    "➖ Chiqim": lambda c: TX.start_tx(c, OP_EXPENSE, c.member),
    "➕ Kirim": lambda c: TX.start_tx(c, OP_INCOME, c.member),
    "💳 Hamyonim": lambda c: V.info(c, c.uid, cur_month(), "x"),
    "📋 Operatsiyalar": lambda c: V.ops(c, "all" if c.admin else c.uid, cur_month(), 0),
    "🧾 Buyurtmalar": lambda c: V.show_orders(c),
    "📤 Oylik hisob": lambda c: RQ.month_start(c),
    "🙏 Rahbardan pul so'rash": lambda c: RQ.req_start(c),
    "🔄 Xodimga pul berish": lambda c: RQ.tr_start(c),
    "❓ Yordam": lambda c: c.send(
        (T.HELP_ADMIN if c.admin else T.HELP_STAFF) + T.ver_line(), T.kb_for(c.member)
    ),
}
MENU_ADMIN = {
    "📊 Ma'lumot": lambda c: V.info(c, "all", cur_month(), "x"),
    "💸 Pul berish": lambda c: V.give_start(c),
    "👛 Hamyonlar": lambda c: V.wallets_view(c),
    "🔍 Tekshiruv": lambda c: V.checks(c),
    "📥 Excel": lambda c: V.excel_menu(c),
}
MENU_TASK = {"📋 Vazifalarim", "❓ Yordam"}
MENU_TEXTS = set(MENU_STAFF) | set(MENU_ADMIN) | MENU_TASK


async def on_text(ctx: Ctx, text: str):
    if not ctx.active:
        await start(ctx)
        return
    m = ctx.member
    if m["is_task_only"]:
        if text == "📋 Vazifalarim":
            await ctx.clr_st()
            return await TK.tasks_view(ctx)
        if text == "❓ Yordam":
            return await ctx.send(T.task_role_text(m) + T.ver_line(), T.KB_TASK)
        if text in MENU_STAFF:
            await ctx.clr_st()
            return await ctx.send(
                "ℹ️ Siz kirim-chiqim kiritmaysiz. Sizning vazifangiz:\n\n" + T.task_role_text(m),
                T.KB_TASK,
            )
    if text in MENU_STAFF:
        await ctx.clr_st()
        return await MENU_STAFF[text](ctx)
    if ctx.admin and text in MENU_ADMIN:
        await ctx.clr_st()
        return await MENU_ADMIN[text](ctx)

    d = await ctx.st()
    if d:
        step = d.get("step") or ""
        if step in ("amount", "rate", "comment", "ord_text"):
            return await TX.tx_text(ctx, d, step, text)
        if step in ("req_amount", "req_reason", "req_custom"):
            return await RQ.req_text(ctx, d, step, text)
        if step == "bpay":
            return await BN.bonus_pay_text(ctx, d, text)
        if step == "fikr":
            return await ctx.send(
                "📸 Iltimos, mijoz fikrining <b>skrinshotini</b> (rasm) yuboring. Fikr matnini rasm izohiga yozing.\nBekor qilish: /bekor"
            )
        if step.startswith("tr_"):
            return await RQ.tr_text(ctx, d, step, text)
        if step in ("receipt", "attach"):
            return await ctx.send("📎 Rasm yuboring yoki «O'tkazib yuborish»ni bosing.")
        if step.startswith("o_"):
            return await V.manual_text(ctx, d, step, text)
        if step == "month_note":
            return await RQ.month_note_text(ctx, d, text)
        return await ctx.send("Yuqoridagi tugmalardan birini tanlang yoki /bekor.")
    q = await ctx.api("POST", "finance/parse/", json={"text": text, "mode": "quick"})
    if q:
        return await TX.start_tx(ctx, q["kind"], m, q)
    await ctx.send(
        "Tushunmadim 🙂 Tugmalardan foydalaning yoki «350000 furnitura 406» ko'rinishida yozing. /yordam",
        T.kb_for(m),
    )


async def on_photo(ctx: Ctx, fid: str, caption: str):
    if not ctx.active:
        return
    d = await ctx.st()
    if ctx.admin and ((d and d.get("step") == "tpl") or caption.startswith("/shablon")):
        await ctx.clr_st()
        return await TK.tpl_from_telegram(ctx, fid)
    if d and d.get("step") == "fikr":
        return await TK.fikr_photo(ctx, d, fid, caption[:300])
    if d and (d.get("step") == "receipt" or (d.get("step") == "confirm" and d.get("t") == "tx")):
        d["rcpt"], d["ra"] = fid, True
        return await TX.next_step(ctx, d)
    if d and d.get("step") == "attach":
        return await TX.attach_receipt(ctx, d, fid)
    m = ctx.member
    if m["is_task_only"]:
        return await ctx.send(T.task_role_text(m), T.KB_TASK)
    if caption:
        q = await ctx.api("POST", "finance/parse/", json={"text": caption, "mode": "quick"})
        if q:
            q["rcpt"] = fid
            return await TX.start_tx(ctx, q["kind"], m, q)
    await ctx.send(
        "Rasm qaysi amalga tegishli? Avval «➖ Chiqim» bosing yoki rasm ostiga <code>350000 furnitura 406</code> deb yozing."
    )


__all__ = ["NotFound"]
