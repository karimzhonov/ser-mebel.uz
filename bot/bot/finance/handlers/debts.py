"""«📕 Qarzlar»: the list of credit purchases, the add flow and the pay flow.

Draft (FSM data) keys: `t` = "qz", `step` (qz_*), add flow: `creditor`, `item`,
`amount_text`, `preview`, `cat`, `cat_label`, `cur` + `tot` (the total in the debt's own
currency, decimal string), `al` = the orders entered so far `[{i: row id, r: ref, c: client,
a: share}]`, `nx` (next row id, never reused), `cr` (the order being entered, `{r, c}`); a
draft saved before the split feature has no `al` and goes on as a single order through `ord`
+ `client`. Pay flow: `n`, `cur`, `rem_text`, `creditor`, `item`, `ord`, `client`,
`amount_text` (None = the full remainder), `pay_preview`, and for a split debt `sp` (picked
from the order picker) + `alloc` (the chosen DebtAllocation id; none = «Hammasi»). Every rule (roles, wallet, currency, overpay) is the backend's; the
draft is cleared BEFORE the write call so a Telegram retry can't book twice.
"""

from __future__ import annotations

import logging
import re
import uuid
from decimal import Decimal

from bot.backend.client import Conflict, Forbidden, NotFound, ServiceRefusal
from bot.common.fmt import esc, money
from bot.common.kb import CANCEL, ik
from bot.finance import api as A
from bot.finance import keyboards as K
from bot.finance import texts as T
from bot.finance.api import D
from bot.finance.ctx import Ctx

logger = logging.getLogger(__name__)

AMOUNT_HINT = "masalan: 250000, 1.5 mln yoki 300$"
MAX_ROWS = 10  # orders one debt can be split over (the backend caps it too)


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


# ====================================================================== delete flow
# Stateless on purpose: no FSM step, so an open debt draft survives `qz:d` / «Yo'q».
async def ask_delete(ctx: Ctx, number: int):
    try:
        d = await ctx.get(f"finance/debts/{number}/")
    except NotFound:
        return await ctx.show(T.debt_gone(number), K.debt_gone_kb())
    if not d.get("can_delete"):
        return await ctx.show(T.debt_card(d) + "\n\n" + T.DEBT_NO_DELETE, K.debt_card_kb(d))
    await ctx.show(T.DEBT_ASK_DELETE + "\n\n" + T.debt_card(d), K.debt_delete_kb(number))


async def do_delete(ctx: Ctx, number: int):
    try:
        await ctx.api("DELETE", f"finance/debts/{number}/")
    except NotFound:
        return await ctx.show(T.debt_gone(number), K.debt_gone_kb())
    except (Conflict, Forbidden) as e:
        return await ctx.show(f"ℹ️ {esc(e.detail)}", K.debt_back_kb(number))
    logger.info("debt #%s deleted from the bot by tg %s", number, ctx.tg_id)
    await ctx.show(T.debt_deleted(number), K.debt_gone_kb())


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
    d.pop("cr", None)
    await ctx.set_st(d)
    orders = await ctx.get("finance/orders/", buckets="yangi,jarayonda")
    await ctx.send(T.debt_order_prompt(d), K.debt_order_kb(orders, d.get("al")))


async def _to_confirm(ctx: Ctx, d: dict):
    d["step"] = "qz_confirm"
    await ctx.set_st(d)
    await ctx.send(T.debt_draft_card(d), K.debt_confirm_kb(d.get("al")))


def _used(d: dict, ref: str) -> bool:
    return any(r["r"].casefold() == ref.casefold() for r in d.get("al") or [])


def _cur_mismatch(cur: str, debt_cur: str) -> str | None:
    if cur == debt_cur:
        return None
    return (
        "❗ Qarz dollarda — summani $ bilan yozing (masalan 300$)."
        if debt_cur == "USD"
        else "❗ Qarz so'mda — summani so'mda yozing (masalan 500000)."
    )


async def _picked(ctx: Ctx, d: dict, info: dict):
    """An order was chosen (button or typed): ask for its share."""
    ref = info["ref"]
    if _used(d, ref):
        await ctx.send(f"❗ {esc(ref)} allaqachon qo'shilgan. Boshqa ID tanlang.")
        return await _ask_order(ctx, d)
    d.update(cr={"r": ref, "c": (info.get("client") or "")[:28]}, step="qz_share")
    await ctx.set_st(d)
    last = len(d["al"]) >= MAX_ROWS - 1
    await ctx.send(
        T.debt_share_prompt(d, last), K.debt_share_kb(T.debt_sum(T.debt_rem(d), d["cur"]))
    )


async def _add_row(ctx: Ctx, d: dict, share: Decimal):
    """The order being entered (`cr`) gets `share`; everything given -> confirm, else next ID."""
    cr = d.pop("cr")
    d["al"].append({"i": d["nx"], "r": cr["r"], "c": cr["c"], "a": f"{share:.2f}"})
    d["nx"] += 1
    if T.debt_rem(d) == 0:
        return await _to_confirm(ctx, d)
    await _ask_order(ctx, d)


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
            cur=res["cur"],
            tot=str(T._dq(res["orig"] if res["cur"] == "USD" else res["amount"])),
            al=[],
            nx=1,
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
        if "al" in d:
            return await _picked(ctx, d, info)
        d.update(ord=info["ref"], client=info.get("client") or "")
        return await _to_confirm(ctx, d)
    return await ctx.send("Yuqoridagi tugmalardan birini tanlang yoki /bekor.")


async def _text_share(ctx: Ctx, d: dict, text: str):
    if not d.get("cr") or "al" not in d:
        return await ctx.send("Yuqoridagi tugmalardan birini tanlang yoki /bekor.")
    if len(d["al"]) >= MAX_ROWS - 1:
        return await ctx.send("❗ Oxirgi ID: «✅ Hammasi shu ID ga» tugmasini bosing.")
    res = await _parse_money(ctx, text)
    if not res:
        return await ctx.send(f"❗ Summani tushunmadim. {AMOUNT_HINT}")
    if bad := _cur_mismatch(res["cur"], d["cur"]):
        return await ctx.send(bad)
    share = T._dq(res["orig"] if d["cur"] == "USD" else res["amount"])
    rem = T.debt_rem(d)
    if share <= 0:
        return await ctx.send(f"❗ Summa noldan katta bo'lsin. {AMOUNT_HINT}")
    if share > rem:
        return await ctx.send(
            f"❗ Qoldiqdan oshib ketdi. Qoldi: <b>{T.debt_sum(rem, d['cur'])}</b>"
        )
    await _add_row(ctx, d, share)


async def save_debt(ctx: Ctx, d: dict):
    rows = d.get("al")
    body = {
        "creditor": d["creditor"],
        "item": d["item"],
        "amount_text": d["amount_text"],
        "category": d["cat"],
    }
    if rows and len(rows) > 1:  # split: `order_ref` is omitted, the backend wants exactly one
        body["allocations"] = [{"ref": r["r"], "amount": r["a"]} for r in rows]
    else:  # one order: today's exact payload
        body["order_ref"] = rows[0]["r"] if rows else d["ord"]
    body["comment"] = d.get("com") or ""
    await ctx.clr_st()
    try:
        res = await ctx.api("POST", "finance/debts/", json=body)
    except ServiceRefusal as e:  # a 400 wrote nothing: keep the (maybe long) draft
        d["step"] = "qz_confirm"
        await ctx.set_st(d)
        await ctx.send(f"❗ {esc(e.detail)}")
        return await ctx.send(T.debt_draft_card(d), K.debt_confirm_kb(d.get("al")))
    await ctx.show(f"✅ Qarz #{res['number']} yozildi\n\n" + T.debt_card(res), K.debt_card_kb(res))


# ====================================================================== pay flow
def _pay_draft(deb: dict, **over) -> dict:
    cur = deb.get("currency") or "UZS"
    d = {
        "t": "qz",
        "step": "qz_pay_amount",
        "n": deb["number"],
        "cur": cur,
        "rem_text": T.debt_sum(deb.get("remaining"), cur),
        "creditor": deb["creditor"],
        "item": deb["item"],
        "ord": deb.get("order_ref"),
        "client": deb.get("client") or "",
        "amount_text": None,
    }
    return {**d, **over}


async def _payable(ctx: Ctx, number: int) -> dict | None:
    """The debt when it can be paid now, else tell why and return None."""
    try:
        deb = await ctx.get(f"finance/debts/{number}/")
    except NotFound:
        await ctx.send("❗ Bunday qarz topilmadi.")
        return None
    if deb.get("status") == "closed":
        await ctx.send("❗ Bu qarz allaqachon to'langan.")
        return None
    if not deb.get("can_pay"):
        await ctx.send("❗ To'lash uchun hamyoningiz bo'lishi kerak.")
        return None
    return deb


def _nonce() -> str:
    return uuid.uuid4().hex[:8]


async def _ask_pay_amount(ctx: Ctx, d: dict, label: str = ""):
    d["nz"] = _nonce()  # every prompt gets its own: buttons of an older prompt go stale
    await ctx.set_st(d)
    await ctx.send(
        f"💸 Qancha to'laysiz?{label} Qoldiq: <b>{esc(d['rem_text'])}</b>\n<i>{AMOUNT_HINT}</i>",
        K.debt_pay_amount_kb(d["rem_text"], d["nz"]),
    )


async def start_pay(ctx: Ctx, number: int):
    deb = await _payable(ctx, number)
    if not deb:
        return
    if T.debt_split(deb):  # split debt: the payer picks the order each time (no FSM step)
        rem = T.debt_sum(deb.get("remaining"), deb.get("currency") or "UZS")
        return await ctx.send(
            f"🧾 Qaysi buyurtma uchun to'laysiz? Qarz #{number}, qoldiq: <b>{esc(rem)}</b>",
            K.debt_pay_order_kb(deb, rem),
        )
    await _ask_pay_amount(ctx, _pay_draft(deb))


async def pick_pay_order(ctx: Ctx, number: int, alloc_id: int):
    """`qz:po:{n}:{allocation id}`: the amount step for one order of a split debt."""
    deb = await _payable(ctx, number)
    if not deb:
        return
    a = next((x for x in deb.get("allocations") or [] if x.get("id") == alloc_id), None)
    if not a or float(a.get("remaining") or 0) <= 0:
        await ctx.send("ℹ️ Bu buyurtma bo'yicha qoldiq yo'q (qarz o'zgargan).")
        return await show_card(ctx, number)
    cur = deb.get("currency") or "UZS"
    d = _pay_draft(
        deb,
        rem_text=T.debt_sum(a["remaining"], cur),
        ord=a.get("order_ref"),
        client=a.get("client") or "",
        sp=True,
        alloc=alloc_id,
    )
    await _ask_pay_amount(ctx, d, f" 🧾 {esc(a.get('order_ref'))}")


async def pay_whole(ctx: Ctx, number: int):
    """`qz:pw:{n}`: «Hammasi» - the whole remainder, the backend pays every unpaid order."""
    deb = await _payable(ctx, number)
    if not deb:
        return
    d = _pay_draft(deb, sp=True)
    d["pay_preview"] = d["rem_text"]
    await _pay_confirm(ctx, d)


async def _pay_confirm(ctx: Ctx, d: dict):
    d["step"] = "qz_pay_confirm"
    d["nz"] = _nonce()
    await ctx.set_st(d)
    await ctx.send(T.debt_pay_card(d), K.debt_pay_confirm_kb(d["nz"]))


async def _text_pay(ctx: Ctx, d: dict, text: str):
    res = await _parse_money(ctx, text)
    if not res:
        return await ctx.send(f"❗ Summani tushunmadim. {AMOUNT_HINT}")
    if bad := _cur_mismatch(res["cur"], d["cur"]):
        return await ctx.send(bad)
    d.update(
        amount_text=text[:60],
        pay_preview=T.debt_sum(res["orig"] if d["cur"] == "USD" else res["amount"], d["cur"]),
    )
    return await _pay_confirm(ctx, d)


async def do_pay(ctx: Ctx, d: dict):
    await ctx.clr_st()
    body = {"amount_text": d.get("amount_text")}
    if d.get("alloc") is not None:
        body["allocation"] = d["alloc"]
    try:
        res = await ctx.api("POST", f"finance/debts/{d['n']}/pay/", json=body)
    except Conflict:
        return await ctx.show("❗ Bu qarz allaqachon to'langan.")
    except ServiceRefusal as e:
        if not d.get("sp"):
            raise
        await show_card(ctx, d["n"])  # stale picker: nothing was written
        return await ctx.send(f"ℹ️ {esc(e.detail)}")
    deb, bal = res["debt"], res["balance"]
    ops = res.get("operations") or [res["operation"]]
    await ctx.show(T.debt_paid_text(deb, ops), K.debt_card_kb(deb))
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
    if step == "qz_share":
        return await _text_share(ctx, d, text)
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
    if act == "po":
        n, _, aid = rest.partition(":")
        if n.isdigit() and aid.isdigit():
            return await pick_pay_order(ctx, int(n), int(aid))
        return
    if act == "pw" and rest.isdigit():
        return await pay_whole(ctx, int(rest))
    if act == "d" and rest.isdigit():
        return await ask_delete(ctx, int(rest))
    if act == "dy" and rest.isdigit():
        return await do_delete(ctx, int(rest))
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
        await ctx.show(f"✔️ 🧾 {esc(info['ref'])} · {esc(info.get('client') or '')}")
        if "al" in d:
            return await _picked(ctx, d, info)
        d.update(ord=info["ref"], client=info.get("client") or "")  # draft from before the split
        return await _to_confirm(ctx, d)
    if act == "wa" and step == "qz_share" and d.get("cr") and "al" in d:
        return await _add_row(ctx, d, T.debt_rem(d))
    if act == "sb" and step == "qz_share" and "al" in d:
        return await _ask_order(ctx, d)
    if act == "x" and rest.isdigit() and step in ("qz_order", "qz_confirm") and "al" in d:
        gone = next((r for r in d["al"] if r["i"] == int(rest)), None)
        if not gone:  # a stale button
            return
        d["al"] = [r for r in d["al"] if r is not gone]
        await ctx.show(f"✖️ 🧾 {esc(gone['r'])} olib tashlandi")
        return await _ask_order(ctx, d)
    if act == "ot" and step == "qz_order":
        d["step"] = "qz_ord_text"
        await ctx.set_st(d)
        return await ctx.send(
            "🧾 Buyurtma ID raqamini yozing (masalan <b>406</b>):", ik([[CANCEL]])
        )
    if act == "s" and step == "qz_confirm":
        return await save_debt(ctx, d)
    if act in ("pf", "py"):
        nz = rest  # a bare `qz:pf` / `qz:py` (old message) passes only on a draft without a nonce
        if (nz or d.get("nz")) and nz != d.get("nz"):
            return await ctx.send(
                "ℹ️ Bu tasdiq eskirgan — oxirgi xabardagi tugmani bosing yoki qaytadan boshlang."
            )
    if act == "pf" and step == "qz_pay_amount":
        d.update(amount_text=None, pay_preview=d["rem_text"])
        return await _pay_confirm(ctx, d)
    if act == "py" and step == "qz_pay_confirm":
        return await do_pay(ctx, d)
