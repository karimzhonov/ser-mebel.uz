"""Duty tasks (site entry, client feedback), duty assignment and the report template."""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError

from bot.backend.client import Conflict, NotFound
from bot.common.fmt import ddmm, esc
from bot.common.kb import b, ik
from bot.finance import texts as T
from bot.finance.ctx import Ctx
from bot.finance.handlers.bonus import send_ready_card

logger = logging.getLogger(__name__)

DUTY_TEXT = {
    "is_site_entry": "🌐 Saytga kirituvchi: mijozdan pul olinganda sizga xabar keladi — saytda «Полученная сумма» ni to'g'rilab, «✅ Saytga kiritdim» ni bosasiz.",
    "is_feedback": "💬 Mijoz fikri: zakaz Готов bo'lganiga 3 kun bo'lganda sizga xabar keladi — mijozdan fikrini olib, «📝 Fikr oldim» ni bosib skrinshot yuborasiz.",
}


async def download(ctx: Ctx, file_id: str) -> bytes | None:
    try:
        buf = await ctx.bot.download(file_id)
        return buf.read() if buf is not None else None
    except TelegramAPIError as e:
        logger.warning("download %s failed: %s", file_id, e)
        return None


async def tasks_view(ctx: Ctx):
    m = ctx.member
    res = await ctx.get("finance/tasks/")
    kb, lines = [], ["📋 <b>Bajarilmagan vazifalar</b>"]
    if m["is_admin"] or m["is_site_entry"]:
        for t in res["site_entry"]:
            lines.append(
                f"🌐 {esc(t['order_ref'])} · {esc(t['client'])} — {esc(t['sum_text'])} ({ddmm(t['date'])})"
            )
            kb.append([b(f"✅ {t['order_ref']} saytga kiritdim", f"skt:{t['code']}")])
    if m["is_admin"] or m["is_feedback"]:
        for f in res["feedback"]:
            lines.append(
                f"💬 {esc(f['order_ref'])} · {esc(f['client'])}"
                + (f" · {esc(f['phone'])}" if f.get("phone") else "")
                + f" (so'ralgan {ddmm(f.get('asked_date'))})"
            )
            kb.append([b(f"📝 {f['order_ref']} fikr oldim", f"fko:{f['order_ref']}")])
    if len(lines) == 1:
        lines += ["", "✅ Hammasi bajarilgan."]
    await ctx.send("\n".join(lines), ik(kb) if kb else T.KB_TASK)


async def sayt_done(ctx: Ctx, code: str):
    m = ctx.member
    if not (m["is_admin"] or m["is_site_entry"]):
        return await ctx.send("ℹ️ Bu tugma saytga kirituvchi menejer uchun.")
    await ctx.clear_kb()
    try:
        task = await ctx.api("POST", f"finance/site-entry/{code}/done/")
    except (Conflict, NotFound):
        return await ctx.send("ℹ️ Bu allaqachon belgilangan.")
    await ctx.send(
        f"✅ Belgilandi: {esc(task['order_ref'])} · {esc(task['client'])} — {esc(task['sum_text'])}. Rahmat!"
    )


async def fikr_btn(ctx: Ctx, ref: str):
    m = ctx.member
    if not (m["is_admin"] or m["is_feedback"]):
        return await ctx.send("ℹ️ Bu tugma mijoz fikri menejeri uchun.")
    try:
        fb = await ctx.get(f"finance/feedback/{ref}/")
        if fb["status"] == "received":
            return await ctx.send(f"ℹ️ {esc(ref)} — fikr allaqachon olingan.")
    except NotFound:
        pass
    await ctx.set_st({"step": "fikr", "id": ref})
    await ctx.send(
        f"📸 <b>{esc(ref)}</b> — mijoz fikrining <b>skrinshotini</b> yuboring.\nRasm izohiga qisqacha fikrni ham yozishingiz mumkin.\n\nBekor qilish: /bekor"
    )


async def fikr_photo(ctx: Ctx, d: dict, fid: str, caption: str):
    await ctx.clr_st()
    content = await download(ctx, fid)
    kw: dict = {"json": {"file_id": fid, "caption": caption}}
    if content:
        kw["files"] = {"file": ("feedback.jpg", content, "image/jpeg")}
    fb = await ctx.api("POST", f"finance/feedback/{d['id']}/", **kw)
    await ctx.send(
        f"✅ Mijoz fikri saqlandi: {esc(fb['order_ref'])} · {esc(fb['client'])}. Rahmat!",
        T.kb_for(ctx.member),
    )


# ====================================================================== duties
async def role_pick(ctx: Ctx, duty: str, title: str):
    cur = await ctx.get("finance/members/", duty=duty)
    act = await ctx.get("finance/members/", set="active")
    await ctx.send(
        f"👥 <b>{title}</b>\nHozir: <b>{esc(', '.join(m['name'] for m in cur) or 'tanlanmagan')}</b>\n\nKim bo'ladi? (xodim avval botga /start yozib, siz qabul qilgan bo'lishi kerak)",
        ik([[b(m["name"][:32], f"rol:{duty}:{m['telegram_id']}")] for m in act]),
    )


async def role_set(ctx: Ctx, arg: str):
    duty, _, tg = arg.partition(":")
    if not ctx.admin or duty not in DUTY_TEXT:
        return
    try:
        m = await ctx.api("POST", f"finance/members/{tg}/duty/", json={"duty": duty})
    except NotFound:
        return
    # the member is told «Sizga yangi vazifa berildi» by finance.duty_assigned
    await ctx.show(f"✅ <b>{esc(m['name'])}</b> tanlandi.\n\n{DUTY_TEXT[duty]}")


# ====================================================================== report template
async def tpl_start(ctx: Ctx):
    await ctx.set_st({"step": "tpl"})
    await ctx.send(
        "🖼 Hisob-kitob varaqasining fon rasmini yuboring (📎 → <b>Fayl</b> qilib yuborsangiz sifati yaxshi bo'ladi).\nOddiy dizaynga qaytish: <code>/shablon oddiy</code>\nBekor qilish: /bekor"
    )


async def tpl_reset(ctx: Ctx):
    await ctx.api("DELETE", "finance/report-template/")
    await ctx.clr_st()
    await ctx.send("✅ Hisob-kitob varaqasi oddiy (bot chizgan) dizaynga qaytarildi.")


async def tpl_from_telegram(ctx: Ctx, fid: str):
    await ctx.send("⏳ Shablon tayyorlanmoqda…")
    content = await download(ctx, fid)
    if not content:
        return await ctx.send("❗ Rasmni yuklab bo'lmadi.")
    await ctx.api(
        "POST",
        "finance/report-template/",
        files={"file": ("background.png", content, "image/png")},
    )
    ready = await ctx.get("finance/orders/", buckets="yakun")
    if ready:
        await send_ready_card(ctx, ready[0]["ref"], test=True)
    await ctx.send("✅ Yangi fon ulandi. Oddiy dizaynga qaytish: <code>/shablon oddiy</code>")
