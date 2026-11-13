"""«📕 Qarzlar»: the list of credit purchases, the add flow and the pay flow.

Draft (FSM data) keys: `t` = "qz", `step` (qz_*), add flow: `creditor`, `item`,
`amount_text`, `preview`, `cat`, `cat_label`, `ord`, `client`; pay flow: `n`, `cur`,
`rem_text`, `creditor`, `item`, `ord`, `client`, `amount_text` (None = the full remainder),
`pay_preview`. Every rule (roles, wallet, currency, overpay) is the backend's; the
draft is cleared BEFORE the write call so a Telegram retry can't book twice.
"""

from __future__ import annotations

import logging
import re

from bot.backend.client import Conflict, NotFound, ServiceRefusal
from bot.common.fmt import esc, money
from bot.common.kb import CANCEL, ik
from bot.finance import api as A
from bot.finance import keyboards as K
from bot.finance import texts as T
from bot.finance.api import D
from bot.finance.ctx import Ctx

logger = logging.getLogger(__name__)

AMOUNT_HINT = "masalan: 250000, 1.5 mln yoki 300$"


# ====================================================================== views
async def show_list(ctx: Ctx, closed: bool = False, page: int = 0):
    res = await ctx.get("finance/debts/", status="closed" if closed else "open")
    await ctx.show(
        T.debt_list_text(res, closed, page), K.debts_kb(res.get("rows") or [], closed, page)
    )


async def show_card(ctx: Ctx, number: int):
    try:
        d = await ctx.get(f"finance/debts/{number}/")
    except NotFound:
        return await ctx.send("❗ Bunday qarz topilmadi.")
    await ctx.show(T.debt_card(d), K.debt_card_kb(d))


# ====================================================================== add flow
async def start_add(ctx: Ctx):
    m = ctx.member or {}
    if not (m.get("has_wallet") or m.get("is_admin")):  # the backend enforces it too
        return await ctx.send(
            "❗ Qarz yozish uchun hamyoningiz bo'lishi kerak. Rahbarga murojaat qiling."
        )
    await ctx.set_st({"t": "qz", "step": "qz_from"})
    await ctx.send("🏪 Kimdan olindi? (do'kon / ta'minotchi)", ik([[CANCEL]]))


async def _parse_money(ctx: Ctx, text: str) -> dict | None:
    try:
        res = await ctx.api("POST", "finance/parse/", json={"text": text, "mode": "money"})
    except ServiceRefusal:
        return None
    return res or None


async def _ask_order(ctx: Ctx, d: dict):
    d["step"] = "qz_order"
    await ctx.set_st(d)
    orders = await ctx.get("finance/orders/", buckets="yangi,jarayonda")
    await ctx.send("🧾 Qaysi buyurtma (mijoz ID) uchun?", K.debt_order_kb(orders))


async def _to_confirm(ctx: Ctx, d: dict):
    d["step"] = "qz_confirm"
    await ctx.set_st(d)
    await ctx.send(T.debt_draft_card(d), K.debt_confirm_kb())


async def _text_add(ctx: Ctx, d: dict, step: str, text: str):
    if step == "qz_from":
        d.update(creditor=text[:255], step="qz_item")
        await ctx.set_st(d)
        return await ctx.send("📦 Nima olindi? (masalan: LDSP 10 list)", ik([[CANCEL]]))
    if step == "qz_item":
        d.update(item=text[:500], step="qz_amount")
        await ctx.set_st(d)
        return await ctx.send(f"💵 Qarz summasini yozing:\n<i>{AMOUNT_HINT}</i>", ik([[CANCEL]]))
    if step == "qz_amount":
        res = await _parse_money(ctx, text)
        if not res:
            return await ctx.send(f"❗ Summani tushunmadim. {AMOUNT_HINT}")
        d.update(
            amount_text=text[:60],
            preview=T.money_full(res["amount"], res["cur"], res.get("orig")),
            step="qz_cat",
        )
        await ctx.set_st(d)
        return await ctx.send(
            "🗂 Nima uchun olindi (kategoriya)?",
            K.debt_cat_kb(await A.categories(ctx, "expense"), ctx.admin),
        )
    if step == "qz_ord_text":
        ref = text.lstrip("#").strip()[:32]
        if not re.fullmatch(r"[\w\-А-Яа-яЁё]+", ref):
            return await ctx.send("❗ Faqat ID raqamini yozing, masalan: 406")
        info = await A.order_info(ctx, ref)
        if not info:
            return await ctx.send(
                f"❗ Bunday buyurtma topilmadi: {esc(ref)}. ID ni tekshirib qayta yozing."
            )
        d.update(ord=info["ref"], client=info.get("client") or "")
        return await _to_confirm(ctx, d)
    return await ctx.send("Yuqoridagi tugmalardan birini tanlang yoki /bekor.")


async def save_debt(ctx: Ctx, d: dict):
    await ctx.clr_st()
    res = await ctx.api(
        "POST",
        "finance/debts/",
        json={
            "creditor": d["creditor"],
            "item": d["item"],
            "amount_text": d["amount_text"],
            "category": d["cat"],
            "order_ref": d["ord"],
            "comment": d.get("com") or "",
        },
    )
    await ctx.show(f"✅ Qarz #{res['number']} yozildi\n\n" + T.debt_card(res), K.debt_card_kb(res))


# ====================================================================== pay flow
async def start_pay(ctx: Ctx, number: int):
    try:
        deb = await ctx.get(f"finance/debts/{number}/")
    except NotFound:
        return await ctx.send("❗ Bunday qarz topilmadi.")
    if deb.get("status") == "closed":
        return await ctx.send("❗ Bu qarz allaqachon to'langan.")
    if not deb.get("can_pay"):
        return await ctx.send("❗ To'lash uchun hamyoningiz bo'lishi kerak.")
    cur = deb.get("currency") or "UZS"
    rem = T.debt_sum(deb.get("remaining"), cur)
    await ctx.set_st(
        {
            "t": "qz",
            "step": "qz_pay_amount",
            "n": number,
            "cur": cur,
            "rem_text": rem,
            "creditor": deb["creditor"],
            "item": deb["item"],
            "ord": deb.get("order_ref"),
            "client": deb.get("client") or "",
            "amount_text": None,
        }
    )
    await ctx.send(
        f"💸 Qancha to'laysiz? Qoldiq: <b>{esc(rem)}</b>\n<i>{AMOUNT_HINT}</i>",
        K.debt_pay_amount_kb(rem),
    )


async def _pay_confirm(ctx: Ctx, d: dict):
    d["step"] = "qz_pay_confirm"
    await ctx.set_st(d)
    await ctx.send(T.debt_pay_card(d), K.debt_pay_confirm_kb())


async def _text_pay(ctx: Ctx, d: dict, text: str):
    res = await _parse_money(ctx, text)
    if not res:
        return await ctx.send(f"❗ Summani tushunmadim. {AMOUNT_HINT}")
    if res["cur"] != d["cur"]:
        return await ctx.send(
            "❗ Qarz dollarda — summani $ bilan yozing (masalan 300$)."
            if d["cur"] == "USD"
            else "❗ Qarz so'mda — summani so'mda yozing (masalan 500000)."
        )
    d.update(
        amount_text=text[:60],
        pay_preview=T.debt_sum(res["orig"] if d["cur"] == "USD" else res["amount"], d["cur"]),
    )
    return await _pay_confirm(ctx, d)


async def do_pay(ctx: Ctx, d: dict):
    await ctx.clr_st()
    try:
        res = await ctx.api(
            "POST", f"finance/debts/{d['n']}/pay/", json={"amount_text": d.get("amount_text")}
        )
    except Conflict:
        return await ctx.show("❗ Bu qarz allaqachon to'langan.")
    deb, op, bal = res["debt"], res["operation"], res["balance"]
    cur = deb.get("currency") or "UZS"
    if deb.get("status") == "closed":
        text = f"✅ Qarz #{deb['number']} to'liq yopildi ({deb.get('days', 0)} kun)\n💸 Chiqim #{op['number']}"
    else:
        text = (
            f"✅ To'landi — chiqim #{op['number']}.\n"
            f"🧮 Qoldiq: <b>{esc(T.debt_sum(deb.get('remaining'), cur))}</b>"
        )
    await ctx.show(text, K.debt_card_kb(deb))
    if D(bal) < 0:
        await ctx.send(
            f"⚠️ Hamyoningiz manfiy: {money(bal)}. Kirim yozilmay qolgan bo'lsa yoki pul kerak bo'lsa, rahbardan so'rang."
        )


# ====================================================================== dispatchers
async def on_text(ctx: Ctx, d: dict, step: str, text: str):
    if d.get("t") != "qz":
        return await ctx.send("Yuqoridagi tugmalardan birini tanlang yoki /bekor.")
    if step == "qz_pay_amount":
        return await _text_pay(ctx, d, text)
    if step in ("qz_cat", "qz_order", "qz_confirm", "qz_pay_confirm"):
        return await ctx.send("Yuqoridagi tugmalardan birini tanlang yoki /bekor.")
    return await _text_add(ctx, d, step, text)


async def on_callback(ctx: Ctx, arg: str, d: dict | None):
    """`qz:<arg>` buttons. Draft buttons are ignored unless the draft is at their step."""
    act, _, rest = arg.partition(":")
    step = d.get("step") if d and d.get("t") == "qz" else None
    if act in ("l", "z"):  # plain `qz:l` / `qz:z` (old buttons) = page 0
        return await show_list(ctx, act == "z", int(rest) if rest.isdigit() else 0)
    if act == "v" and rest.isdigit():
        return await show_card(ctx, int(rest))
    if act == "n":
        return await start_add(ctx)
    if act == "p" and rest.isdigit():
        return await start_pay(ctx, int(rest))
    if not step:
        return
    if act == "k" and step == "qz_cat":
        cats = K.debt_cats(await A.categories(ctx, "expense"), ctx.admin)
        c = next((x for x in cats if x["code"] == rest), None)
        if not c:
            return
        d.update(cat=c["code"], cat_label=T.cat_label(c))
        await ctx.show("✔️ " + esc(d["cat_label"]))
        return await _ask_order(ctx, d)
    if act == "o" and step == "qz_order" and rest:
        info = await A.order_info(ctx, rest)
        if not info:
            return await ctx.send("❗ Bunday buyurtma topilmadi.")
        d.update(ord=info["ref"], client=info.get("client") or "")
        await ctx.show(f"✔️ 🧾 {esc(info['ref'])} · {esc(d['client'])}")
        return await _to_confirm(ctx, d)
    if act == "ot" and step == "qz_order":
        d["step"] = "qz_ord_text"
        await ctx.set_st(d)
        return await ctx.send(
            "🧾 Buyurtma ID raqamini yozing (masalan <b>406</b>):", ik([[CANCEL]])
        )
    if act == "s" and step == "qz_confirm":
        return await save_debt(ctx, d)
    if act == "pf" and step == "qz_pay_amount":
        d.update(amount_text=None, pay_preview=d["rem_text"])
        return await _pay_confirm(ctx, d)
    if act == "py" and step == "qz_pay_confirm":
        return await do_pay(ctx, d)
