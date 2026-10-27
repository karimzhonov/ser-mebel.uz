"""Read-only screens: «Ma'lumot», «Operatsiyalar», months, wallets, checks, Excel, orders
(plus the admin's manual orders)."""

from __future__ import annotations

from bot.backend.client import NotFound, RawResponse, ServiceRefusal
from bot.common.fmt import (
    add_months,
    cur_month,
    cur_name,
    ddmm,
    esc,
    fmt_cur,
    money,
    month_full,
    month_name,
    num,
    signed,
    usd,
)
from bot.common.kb import CANCEL, b, grid, ik
from bot.finance import api as A
from bot.finance import charts
from bot.finance import keyboards as K
from bot.finance import texts as T
from bot.finance.api import D
from bot.finance.ctx import Ctx
from bot.finance.texts import CAT_TRANSFER, OP_INCOME


async def _scope_name(ctx: Ctx, scope: str) -> str | None:
    if scope == "all":
        return None
    if scope == ctx.uid:
        return ctx.name
    m = await A.member(ctx, scope)
    return m["name"] if m else None


# ====================================================================== Ma'lumot
async def info(ctx: Ctx, scope: str, ym: str, side: str):
    if not ctx.admin:
        scope = ctx.uid
    try:
        res = await ctx.get("finance/summary/", month=ym, member=scope)
    except NotFound:
        return await ctx.send("Xodim topilmadi.")
    sm, member = res["summary"], res["member"]
    items = sm["expense_by_category"] if side == "x" else sm["income_by_category"]
    tot = sum(float(i["sum"]) for i in items) or 1
    who = "🏢 Ser mebel (hammasi)" if member is None else f"👤 {esc(member['name'])}"
    lines = [
        f"📊 <b>Ma'lumot · {month_name(ym)}</b>",
        who,
        "",
        f"🔴 Xarajatlar: <b>{num(-float(sm['expense']))}</b>",
        f"🟢 Daromadlar: <b>{num(sm['income'])}</b>",
        f"💠 <b>Balans: {num(sm['balance'])} so'm</b>",
    ]
    if member is None:
        lines.append(
            f"💸 Xodimlarga berildi: <b>{num(sm['given_to_staff'])}</b> <i>(daromad emas)</i>"
        )
        if float(sm["boss_personal"]):
            lines.append(f"👔 Rahbar xarajatlari (alohida): <b>{num(sm['boss_personal'])}</b>")
        if float(sm["home"]):
            lines.append(f"🏠 Uy uchun (alohida): <b>{num(sm['home'])}</b>")
        if float(sm["transfers"]):
            lines.append(f"🔄 Xodimlar o'rtasida o'tkazildi: {num(sm['transfers'])}")
    elif not member["is_admin"]:
        lines.append(f"👛 Hamyonda hozir: <b>{money(res['member_balance'])}</b>")
    lines += ["", "<b>Xarajatlar:</b>" if side == "x" else "<b>Daromadlar:</b>"]
    if not items:
        lines.append("— bu oyda yo'q")
    for i in items[:9]:
        v = float(i["sum"])
        lines.append(
            f"{i['emoji']} {esc(i['name'])} — <b>{num(-v if side == 'x' else v)}</b> · {round(v * 100 / tot)}% · {i['n']} op."
        )
    if len(items) > 9:
        lines.append(f"… yana {len(items) - 9} ta")
    if side == "x" and sm["salary_by_worker"]:
        lines += ["", "<b>👷 Oylik — kimga:</b>"]
        for w in sm["salary_by_worker"][:10]:
            lines.append(f"• {esc(w['name'])} — {num(w['sum'])}")
        if len(sm["salary_by_worker"]) > 10:
            lines.append(f"… yana {len(sm['salary_by_worker']) - 10} kishi")
    top = items[0] if items else None
    png = await charts.donut_png(
        items,
        top["name"] if top else "Ma'lumot yo'q",
        (num(-float(top["sum"]) if side == "x" else top["sum"]) + " UZS") if top else "",
    )
    prev_, next_ = add_months(ym, -1), add_months(ym, 1)
    nav = [b(f"◀️ {month_name(prev_)}", f"inf:{scope}:{prev_}:{side}")]
    if ym < cur_month():
        nav.append(b(f"{month_name(next_)} ▶️", f"inf:{scope}:{next_}:{side}"))
    kb = [
        nav,
        [
            b(("● " if side == "x" else "") + "🔴 Xarajatlar", f"inf:{scope}:{ym}:x"),
            b(("● " if side == "d" else "") + "🟢 Daromadlar", f"inf:{scope}:{ym}:d"),
        ],
        [b("📋 Operatsiyalar", f"ops:{scope}:{ym}:0"), b("📈 Oylar", f"mon:{scope}")],
    ]
    if ctx.admin:
        kb.append(
            [
                (
                    b("👤 Xodim bo'yicha", f"who:{ym}")
                    if scope == "all"
                    else b("🏢 Hammasi", f"inf:all:{ym}:{side}")
                ),
                b("📥 Excel", f"xls:{ym}"),
            ]
        )
    await ctx.show_photo(png, "\n".join(lines), ik(kb))


# ====================================================================== Operatsiyalar
async def ops(ctx: Ctx, scope: str, ym: str, page: int):
    if not ctx.admin:
        scope = ctx.uid
    res = await ctx.get("finance/operations/", month=ym, member=scope)
    rows = res["rows"]
    per = 18
    pages = max(1, -(-len(rows) // per))
    page = max(0, min(int(page or 0), pages - 1))
    scope_all = scope == "all"
    day_tot: dict = {}
    for t in rows:
        if not t["internal"]:
            day_tot[t["date"]] = day_tot.get(t["date"], 0) + float(t["signed_amount"])
    name = await _scope_name(ctx, scope)
    who = "" if scope_all else f" · {esc(name)}"
    lines = [f"📋 <b>Operatsiyalar · {month_name(ym)}</b>{who}"]
    cur = None
    for t in rows[page * per : (page + 1) * per]:
        if t["date"] != cur:
            cur = t["date"]
            lines += [
                "",
                f"📅 <b>{ddmm(t['date'])}</b>   <b>{signed(day_tot.get(t['date'], 0))} UZS</b>",
                "────────────",
            ]
        sign = "🟢 +" if t["kind"] == OP_INCOME else "🔴 −"
        comment = t.get("comment") or ""
        extra = " · ".join(
            x
            for x in [
                f"👤 {esc(t['member']['name'])}" if scope_all else "",
                f"👷 {esc(t['worker'])}" if t.get("worker") else "",
                f"🧾 {esc(t['order_ref'])}" if t.get("order_ref") else "",
                usd(t["orig_amount"]) if t["currency"] == "USD" else "",
                "📎" if t.get("receipt_file_id") else "",
                f"#{t['number']}",
            ]
            if x
        )
        lines += [
            f"{T.cat_label(t['category'])}{' ↔️' if t['internal'] else ''}   {sign}{num(t['amount'])}",
            f"      <i>{(esc(comment[:60]) + ' · ') if comment else ''}{extra}</i>",
        ]
    if not rows:
        lines += ["", "Bu oyda amal yo'q."]
    if pages > 1:
        lines += ["", f"Sahifa {page + 1}/{pages}"]
    pg = []
    if page > 0:
        pg.append(b("⬅️ Oldingi", f"ops:{scope}:{ym}:{page - 1}"))
    if page < pages - 1:
        pg.append(b("Keyingi ➡️", f"ops:{scope}:{ym}:{page + 1}"))
    nav = [b(f"◀️ {month_name(add_months(ym, -1))}", f"ops:{scope}:{add_months(ym, -1)}:0")]
    if ym < cur_month():
        nav.append(b(f"{month_name(add_months(ym, 1))} ▶️", f"ops:{scope}:{add_months(ym, 1)}:0"))
    await ctx.show("\n".join(lines), ik([pg, nav, [b("📊 Ma'lumot", f"inf:{scope}:{ym}:x")]]))


async def months_view(ctx: Ctx, scope: str):
    if not ctx.admin:
        scope = ctx.uid
    res = await ctx.get("finance/months/", member=scope)
    series, member = res["series"], res.get("member")
    lines = ["📈 <b>Oylar bo'yicha</b>" + ("" if not member else f" · {esc(member['name'])}"), ""]
    for x in series:
        lines.append(
            f"<b>{x['label']}</b>: 🟢 {num(x['income'])}  🔴 {num(x['expense'])}  = {signed(float(x['income']) - float(x['expense']))}"
        )
    png = await charts.bars_png(
        [x["label"] for x in series], [x["income"] for x in series], [x["expense"] for x in series]
    )
    await ctx.show_photo(png, "\n".join(lines), ik([[b("📊 Ma'lumot", f"inf:{scope}:{cur_month()}:x")]]))


# ====================================================================== wallets / admin lists
async def wallets_view(ctx: Ctx):
    ym = cur_month()
    res = await ctx.get("finance/wallets/")
    lines, kb = ["👛 <b>Hamyonlar</b>", ""], []
    for r in res["rows"]:
        u, bv = r["member"], float(r["balance"])
        if u["is_admin"]:
            desc = f"kassa, oyda sarfladi: {money(r['month_spent'])}"
        else:
            desc = ("🔴 " if bv < 0 else "") + money(bv)
        lines.append(
            ("💼 " if u["is_admin"] else "👤 ")
            + f"<b>{esc(u['name'])}</b> — {desc}\n      oxirgi yozuv: {ddmm(r.get('last_day'))}"
            + ("" if u["is_admin"] else f" · oylik hisob: {'✅' if r['reported'] else '⏳'}")
        )
        kb.append(
            [
                b(f"📊 {u['name'][:18]}", f"inf:{u['telegram_id']}:{ym}:x"),
                b("📋", f"ops:{u['telegram_id']}:{ym}:0"),
                b("🔔", f"nudge:{u['telegram_id']}"),
            ]
        )
    for p in res["pending"]:
        kb.append(
            [
                b(f"✅ {p['name'][:18]} — qabul qilish", f"approve:{p['telegram_id']}"),
                b("🚫", f"reject:{p['telegram_id']}"),
            ]
        )
    if len(lines) == 2:
        lines.append("Hali hamyon yo'q.")
    lines += [
        "",
        f"💰 Xodimlar qo'lida jami: <b>{money(res['staff_total'])}</b>",
        "",
        "<i>Ismni o'zgartirish: /ism &lt;ID&gt; &lt;Ism&gt;</i>",
    ]
    await ctx.send("\n".join(lines), ik(kb))


async def give_start(ctx: Ctx):
    st = await ctx.get("finance/members/", set="staff")
    if not st:
        return await ctx.send("Hali xodim yo'q. Xodimlar botga /start yozishi kerak.")
    await ctx.send(
        "💸 Kimga pul berdingiz?",
        ik(grid([b(s["name"][:25], f"give:{s['telegram_id']}") for s in st], 2) + [[CANCEL]]),
    )


async def checks(ctx: Ctx):
    await ctx.send(T.checks_text(await ctx.get("finance/checks/")))


async def excel_menu(ctx: Ctx):
    ym = cur_month()
    ms = [add_months(ym, -k) for k in range(4)]
    await ctx.send(
        "📥 Qaysi oy uchun Excel?",
        ik(
            [
                [b(month_name(ms[0]), f"xls:{ms[0]}"), b(month_name(ms[1]), f"xls:{ms[1]}")],
                [b(month_name(ms[2]), f"xls:{ms[2]}"), b(month_name(ms[3]), f"xls:{ms[3]}")],
            ]
        ),
    )


async def send_excel(ctx: Ctx, ym: str):
    await ctx.send("⏳ Excel tayyorlanmoqda…")
    try:
        res: RawResponse = await ctx.api("GET", "finance/excel/", params={"month": ym}, raw=True)
        await ctx.document(
            res.content, res.filename or f"SerMebel-{ym}.xlsx", f"📥 {month_full(ym)} — SerMebel hisoboti"
        )
    except ServiceRefusal as e:
        await ctx.send(f"❗ Excel tayyorlab bo'lmadi: {esc(e.detail)}")


# ====================================================================== orders
async def show_orders(ctx: Ctx):
    allo = await ctx.get("finance/orders/", buckets="jarayonda,yangi,kutish,yakun")
    work = [o for o in allo if o["bucket"] == "jarayonda"]
    fresh = [o for o in allo if o["bucket"] == "yangi"]
    wait = [o for o in allo if o["bucket"] == "kutish"]
    ready = [o for o in allo if o["bucket"] == "yakun"]
    kb = [[b(f"🧾 {o['ref']} · {o['client'][:30]}", f"ocard:{o['ref']}")] for o in work[:30]]
    kb += [
        [b(f"🆕 {o['ref']} · {o['client'][:30]} (faqat kirim)", f"ocard:{o['ref']}")]
        for o in fresh[:20]
    ]
    kb += [
        [b(f"⏳ {o['ref']} · {o['client'][:30]} (ожидание)", f"ocard:{o['ref']}")]
        for o in wait[:20]
    ]
    kb += [
        [b(f"✅ {o['ref']} · {o['client'][:30]} (tayyor, qoldiq)", f"ocard:{o['ref']}")]
        for o in ready[:30]
    ]
    if ctx.admin:
        kb.append([b("➕ Yangi buyurtma (saytda yo'q)", "onew"), b("📁 Tugaganlar", "oclosed")])
    if not (work or fresh or wait or ready):
        return await ctx.send("Faol buyurtma yo'q.", ik(kb))
    text = f"🧾 <b>Faol buyurtmalar</b> ({len(work)})"
    if fresh:
        text += f"\n🆕 Yangi — faqat kirim/avans uchun ({len(fresh)})"
    if wait:
        text += f"\n⏳ Ожидание — avans/qoldiq (kirim) uchun ({len(wait)})"
    if ready:
        text += f"\n✅ Bitgan — qoldiq to'lov (kirim) uchun ({len(ready)})"
    await ctx.send(text, ik(kb))


async def order_card(ctx: Ctx, ref: str):
    try:
        o = await ctx.get(f"finance/orders/{ref}/")
    except NotFound:
        return await ctx.send("Buyurtma topilmadi.")
    await render_order_card(ctx, o)


async def render_order_card(ctx: Ctx, o: dict):
    full = ctx.admin and "total" in o
    st = o["stats"]
    label = {
        "jarayonda": "🟢 Jarayonda",
        "yangi": "🆕 Yangi (Деталировка) — kirim va «Заказ материал» chiqimi",
        "kutish": "⏳ Ожидание — faqat kirim (avans/qoldiq)",
    }.get(o["bucket"])
    if o["bucket"] == "yakun":
        left = o.get("ready_days_left") or 0
        label = f"✅ Bitgan ({ddmm(o.get('ready_date'))}) — qoldiq to'lov (kirim) uchun, {left} kun qoldi"
    lines = [f"🧾 <b>{esc(o['ref'])} — {esc(o['client'])}</b>", label or "✅ Tugagan"]
    if o.get("phone"):
        lines.append(f"📞 {esc(o['phone'])}")
    lines.append("")
    price_uzs = D(o.get("price_uzs"))
    if full:
        lines.append(
            f"💼 Shartnoma: <b>{fmt_cur(o['total'], o['currency'])} {cur_name(o['currency'])}</b>"
            + (f" (≈ {money(o['price_uzs'])})" if o["currency"] == "USD" else "")
        )
        if o.get("paid") is not None:
            lines.append(
                f"💰 Saytda olingan: {fmt_cur(o['paid'], o['currency'])} · qoldiq {fmt_cur(o.get('rest') or 0, o['currency'])}"
            )
    lines.append(f"🔴 Sarflandi: <b>{money(st['spent'])}</b>")
    if float(st["collected"]) or full:
        lines.append(
            f"💰 Botda yozilgan mijoz to'lovlari (avans + qoldiq): {money(st['collected'])}"
        )
    if full and price_uzs:
        pct = round(float(st["spent"]) * 100 / float(price_uzs))
        p = min(10, max(0, pct // 10))
        lines.append("▓" * p + "░" * (10 - p) + f" {pct}% sarflandi")
        profit = price_uzs - D(st["spent"])
        lines.append(("📈 Foyda: <b>" if profit >= 0 else "📉 Zarar: <b>") + money(profit) + "</b>")
    if st["cats"]:
        lines += ["", "<b>Xarajatlar:</b>"]
        for c in st["cats"]:
            lines.append(f"{T.cat_label(c)} — {num(c['sum'])}")
    if st["last_ops"]:
        lines += ["", "<b>Oxirgi amallar:</b>"]
        for t in st["last_ops"]:
            lines.append(
                f"#{t['number']} {ddmm(t['date'])[:5]} {esc(t['member']['name'])}: {'+' if t['kind'] == OP_INCOME else '−'}{num(t['amount'])} {esc((t.get('comment') or '')[:30])}"
            )
    kb = []
    if full:
        kb.append([b("🖼 Hisob-kitob varaqasi", f"oimg:{o['ref']}")])
        if o.get("manual"):
            kb.append(
                [
                    b("✏️ Narx", f"oprice:{o['ref']}"),
                    b(
                        "🔄 Qayta ochish" if o["manual"]["is_closed"] else "✅ Yopish",
                        f"otoggle:{o['ref']}",
                    ),
                ]
            )
    await ctx.send("\n".join(lines), ik(kb))


# ====================================================================== manual orders (admin)
async def parse_price(ctx: Ctx, text: str) -> dict | None:
    """The price typed by the boss: `finance/parse/` (None = not an amount)."""
    try:
        return await ctx.api("POST", "finance/parse/", json={"text": text, "mode": "money"})
    except ServiceRefusal:
        await ctx.send("❗ Dollar kursi yo'q — so'mda yozing yoki /kurs 12050")
        return {}


async def manual_text(ctx: Ctx, d: dict, step: str, text: str):
    if step == "o_id":
        ref = text.strip()[:20]
        if await A.order_label(ctx, ref):
            return await ctx.send("❗ Bu ID band. Boshqasini yozing.")
        d.update(oid=ref, step="o_client")
        await ctx.set_st(d)
        return await ctx.send(
            "👤 Mijoz ismi va buyurtma nomi:\n<i>masalan: Назира — oshxona mebeli</i>",
            ik([[CANCEL]]),
        )
    if step == "o_client":
        d.update(client=text[:80], step="o_phone")
        await ctx.set_st(d)
        return await ctx.send("📞 Mijoz telefoni:", K.skip_kb("phone"))
    if step == "o_phone":
        d.update(phone=text[:30], step="o_price")
        await ctx.set_st(d)
        return await ctx.send("💼 Shartnoma summasi (so'm yoki $):", K.skip_kb("price"))
    if step in ("o_price", "o_newprice"):
        res = await parse_price(ctx, text)
        if res == {}:
            return
        if not res:
            return await ctx.send("❗ Summani tushunmadim.")
        if step == "o_price":
            d["price_text"] = text
            return await finish_order(ctx, d)
        await ctx.clr_st()
        await ctx.api("PATCH", f"finance/manual-orders/{d['oid']}/", json={"price_text": text})
        await ctx.send(f"✅ Narx yangilandi: {money(res['amount'])}")
        return await order_card(ctx, d["oid"])


async def finish_order(ctx: Ctx, d: dict):
    await ctx.clr_st()
    mo = await ctx.api(
        "POST",
        "finance/manual-orders/",
        json={
            "ref": d["oid"],
            "client": d.get("client", ""),
            "phone": d.get("phone", ""),
            "price_text": d.get("price_text") or "",
        },
    )
    await A.drop_cache(f"order:{mo['ref']}")
    await ctx.send(
        f"✅ Buyurtma ochildi: <b>{esc(mo['ref'])}</b> · {esc(mo['client'])}\nEndi xodimlar xarajat yozganda shu ID ni tanlaydi."
    )


async def orders_callback(ctx: Ctx, cmd: str, arg: str, d: dict | None) -> bool:
    if cmd == "ocard":
        await order_card(ctx, arg)
        return True
    if cmd == "oclosed":
        rows = await ctx.get("finance/orders/closed-manual/")
        if not rows:
            await ctx.send(
                "Tugagan (qo'lda kiritilgan) buyurtma yo'q. Saytdagi buyurtmalar saytda."
            )
        else:
            await ctx.send(
                "📁 <b>Tugagan buyurtmalar</b>",
                ik([[b(f"{o['ref']} · {o['client'][:30]}", f"ocard:{o['ref']}")] for o in rows]),
            )
        return True
    if cmd == "skip" and d and arg == "phone" and d.get("step") == "o_phone":
        d["step"] = "o_price"
        await ctx.set_st(d)
        await ctx.show("💼 Shartnoma summasi (so'm yoki $):", K.skip_kb("price"))
        return True
    if cmd == "skip" and d and arg == "price" and d.get("step") == "o_price":
        await ctx.show("✔️ Narx keyinroq kiritiladi")
        await finish_order(ctx, d)
        return True
    if not ctx.admin:
        return False
    if cmd == "onew":
        nid = (await ctx.get("finance/orders/next-ref/"))["ref"]
        await ctx.set_st({"step": "o_id"})
        await ctx.send(
            f"🆕 Saytda yo'q buyurtma raqami: <b>{nid}</b>\nTugmani bosing yoki o'z raqamingizni yozing.\n<i>Saytdagi buyurtmalar avtomatik ko'rinadi — ularni bu yerda ochish shart emas.</i>",
            ik([[b(f"✅ {nid}", f"oid:{nid}")], [CANCEL]]),
        )
        return True
    if cmd == "oid" and d and d.get("step") == "o_id":
        d.update(oid=arg, step="o_client")
        await ctx.set_st(d)
        await ctx.show(
            f"ID: <b>{esc(arg)}</b>\n\n👤 Mijoz ismi va buyurtma nomi:\n<i>masalan: Назира — oshxona mebeli</i>",
            ik([[CANCEL]]),
        )
        return True
    if cmd == "oprice":
        await ctx.set_st({"step": "o_newprice", "oid": arg})
        await ctx.send(f"💼 {esc(arg)} uchun shartnoma summasini yozing (so'm yoki $):")
        return True
    if cmd == "otoggle":
        try:
            o = await ctx.api("PATCH", f"finance/manual-orders/{arg}/", json={"toggle_closed": True})
        except NotFound:
            return True
        await render_order_card(ctx, o)
        return True
    return False


__all__ = ["CAT_TRANSFER"]
