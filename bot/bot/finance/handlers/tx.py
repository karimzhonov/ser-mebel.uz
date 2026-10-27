"""Kirim / chiqim flow: draft -> steps -> confirm -> POST finance/operations/.

The draft dict keeps the old keys (`t`, `kind`, `uid`, `author`, `amount`, `cur`, `orig`,
`rate`, `cat`, `ord`, `com`, `rcpt`, `oa`/`ca`/`ra` = «already asked», `worker`, `pay`,
`step`) in the FSM data. The write call happens after the draft is cleared, so a Telegram
retry can't book twice.
"""

from __future__ import annotations

import re
from decimal import Decimal

from bot.backend.client import BackendError, Forbidden, NotFound, ServiceRefusal
from bot.common.fmt import esc, money
from bot.common.kb import CANCEL, b, ik
from bot.finance import api as A
from bot.finance import keyboards as K
from bot.finance import texts as T
from bot.finance.api import D
from bot.finance.ctx import Ctx
from bot.finance.texts import (
    CAT_FROM_BOSS,
    CAT_FUEL,
    CAT_REST,
    CAT_REWORK,
    CAT_SALARY,
    OP_EXPENSE,
    OP_INCOME,
)

USD_WORDS = re.compile(r"\$|usd|dollar|доллар", re.I)


def new_draft(kind: str, uid: int, uname: str, author: int) -> dict:
    return {
        "t": "tx",
        "kind": kind,
        "uid": uid,
        "uname": uname,
        "author": author,
        "amount": None,
        "cur": "UZS",
        "orig": None,
        "rate": None,
        "cat": None,
        "ord": None,
        "com": None,
        "rcpt": None,
        "oa": False,
        "ca": False,
        "ra": False,
    }


async def op_text(ctx: Ctx, op: dict, bal=None) -> str:
    extras = await A.resolve_op_extras(ctx, op)
    return T.op_card(op, bal, extras["order"], extras["workers"])


async def draft_text(ctx: Ctx, d: dict) -> str:
    cat = await A.category(ctx, d.get("cat"))
    order = await A.order_label(ctx, d.get("ord")) if d.get("ord") else None
    workers = await A.workers(ctx) if d.get("worker") else []
    return T.draft_card(d, d.get("uname"), cat, order, workers)


def find_worker(text: str | None, workers: list[dict]) -> str | None:
    t = f" {str(text or '').lower()} "
    for w in workers:
        n = w["name"].lower().split(" ")[0]
        if len(n) > 2 and n in t:
            return w["name"]
    return None


async def start_tx(ctx: Ctx, kind: str, target: dict, q: dict | None = None):
    m = ctx.member
    if m.get("is_task_only"):
        return await ctx.send(T.task_role_text(m), T.KB_TASK)
    d = new_draft(kind, target["telegram_id"], target["name"], ctx.tg_id)
    if q:
        cat = await A.category(ctx, q["cat"]) if q.get("cat") else None
        if q.get("cat") == CAT_SALARY and kind == OP_EXPENSE:
            w = find_worker(q.get("com"), await A.workers(ctx))
            if w:
                d["worker"] = w
        if q["cur"] == "USD":
            d.update(cur="USD", orig=str(q["val"]))
        else:
            d["amount"] = str(round(D(q["val"])))
        if cat and not (cat["admin_only"] and not ctx.admin):
            d["cat"] = cat["code"]
        if q.get("ord") and not (cat and cat["no_order"]) and q.get("cat") != CAT_SALARY:
            d["ord"], d["oa"] = q["ord"], True
        if q.get("com"):
            d["com"], d["ca"] = q["com"], True
        if q.get("rcpt"):
            d["rcpt"], d["ra"] = q["rcpt"], True
    return await next_step(ctx, d)


async def next_step(ctx: Ctx, d: dict):
    async def say(text, kb=None):
        await ctx.set_st(d)
        return await ctx.send(text, kb)

    kind = d["kind"]
    if not d.get("amount") and not d.get("orig"):
        d["step"] = "amount"
        return await say(
            f"💵 {'Chiqim' if kind == OP_EXPENSE else 'Kirim'} summasini yozing:\n<i>masalan: 250000, 250 ming, 1.5 mln yoki 100$</i>",
            ik([[CANCEL]]),
        )
    if d.get("cur") == "USD" and not d.get("amount"):
        if not d.get("rate") and not d.get("mr"):
            r = await A.usd_rate(ctx)
            d["rate"] = str(r) if r else None
        if not d.get("rate"):
            d["step"] = "rate"
            return await say("💱 1 USD necha so'm? Kursni yozing (masalan 12050):", ik([[CANCEL]]))
        d["amount"] = str(round(D(d["orig"]) * D(d["rate"])))
    if not d.get("cat"):
        if d.get("give"):
            d["cat"] = CAT_FROM_BOSS
        else:
            d["step"] = "category"
            if kind == OP_EXPENSE:
                return await say(
                    "🗂 Nimaga sarflandi?",
                    K.cat_kb(await A.categories(ctx, "expense"), ctx.admin),
                )
            return await say("📥 Pul qayerdan keldi?", K.src_kb(await A.categories(ctx, "income")))
    cat = await A.category(ctx, d["cat"])
    if kind == OP_EXPENSE and d["cat"] == CAT_SALARY and not d.get("worker"):
        d["step"] = "worker"
        return await say(
            "👷 Kimga oylik berildi? Bo'limni tanlang:", K.group_kb(await A.workers(ctx))
        )
    if kind == OP_EXPENSE and d["cat"] == CAT_SALARY and not d.get("pay"):
        if not ctx.admin:
            d["pay"] = "Avans"
        else:
            d["step"] = "paytype"
            return await say(
                "💵 Bu <b>avansmi</b> yoki <b>oylik</b>?",
                ik([[b("💵 Avans", "pay:Avans"), b("🧾 Oylik", "pay:Oylik")], [CANCEL]]),
            )
    if kind == OP_EXPENSE and d["cat"] == CAT_FUEL and not d.get("worker"):
        d["step"] = "car"
        cars = await A.cars(ctx)
        return await say(
            "⛽ Qaysi mashina / kim uchun?",
            ik([[b(f"🚗 {c['name']}", f"car:{c['id']}")] for c in cars] + [[CANCEL]]),
        )
    no_order = kind == OP_EXPENSE and (d["cat"] == CAT_SALARY or bool(cat and cat["no_order"]))
    if no_order:
        d["oa"], d["ord"] = True, None
    if kind == OP_EXPENSE and d["cat"] == CAT_REWORK and not d.get("oa"):
        d["step"] = "ord_text"
        return await say(
            "🔁 Peredelka — qaysi mijoz uchun?\n🧾 Buyurtma ID raqamini yozing (masalan <b>406</b>):",
            ik([[CANCEL]]),
        )
    if not d.get("oa") and not (kind == OP_INCOME and d["cat"] == CAT_FROM_BOSS):
        d["step"] = "order"
        q = (
            "🧾 Qaysi bitgan buyurtma (oxirgi 30 kun)?"
            if d["cat"] == CAT_REST
            else (
                "🧾 Qaysi yangi buyurtma (mijoz ID)?"
                if d["cat"] == "avans"
                else "🧾 Qaysi buyurtma (mijoz ID) uchun?"
            )
        )
        return await say(q, await order_choice_kb(ctx, d, cat))
    if not d.get("ca"):
        d["step"] = "comment"
        if kind == OP_EXPENSE and cat and cat["no_order"]:
            return await say("📝 Tavsif yozing — nima uchun sarflandi:", ik([[CANCEL]]))
        return await say(
            f"📝 Qisqa izoh yozing ({'nima olindi, nechta' if kind == OP_EXPENSE else 'izoh'}):",
            K.skip_kb("comment"),
        )
    d["step"] = "confirm"
    rows = [
        [b("✅ Saqlash", "save")],
        [b("✏️ Summa", "edit:amount"), b("🗂 Kategoriya", "edit:category")]
        + ([] if no_order else [b("🧾 Buyurtma", "edit:order")]),
    ]
    if d.get("cur") == "USD":
        rows.append([b("💱 Kursni o'zgartirish", "edit:rate")])
    rows.append([CANCEL])
    return await say(await draft_text(ctx, d), ik(rows))


async def order_choice_kb(ctx: Ctx, d: dict, cat: dict | None):
    want, general = K.order_buckets(d["kind"], d["cat"])
    orders = await ctx.get("finance/orders/", buckets=",".join(want))
    return K.order_kb(d["kind"], cat, d["cat"], orders, general)


async def save_tx(ctx: Ctx, d: dict | None):
    if not d or d.get("step") != "confirm":
        return
    await ctx.clr_st()
    res = await ctx.api(
        "POST",
        "finance/operations/",
        json={
            "member_tg": d["uid"],
            "kind": d["kind"],
            "amount": d["amount"],
            "category": d["cat"],
            "currency": d.get("cur") or "UZS",
            "orig_amount": d.get("orig") or None,
            "rate": d.get("rate") or None,
            "order_ref": d.get("ord") or None,
            "comment": d.get("com") or "",
            "receipt_file_id": d.get("rcpt") or "",
            "worker": d.get("worker") or "",
            "pay_type": d.get("pay") or "",
        },
    )
    op, bal = res["operation"], res["balance"]
    await ctx.show(
        "✅ Saqlandi!\n\n" + await op_text(ctx, op, bal),
        K.saved_kb(
            op["number"], op["kind"] == OP_EXPENSE and not op.get("receipt_file_id")
        ),
    )
    if (
        D(bal) < 0
        and op["kind"] == OP_EXPENSE
        and int(d["uid"]) == ctx.tg_id
    ):
        await ctx.send(
            f"⚠️ Hamyoningiz manfiy: {money(bal)}. Kirim yozilmay qolgan bo'lsa yoki pul kerak bo'lsa, rahbardan so'rang.",
            ik([[b("🙏 Rahbardan pul so'rash", "go:req")]]),
        )


# ====================================================================== text / photo steps
async def tx_text(ctx: Ctx, d: dict, step: str, text: str):
    if step == "amount":
        return await amount_text(ctx, d, text)
    if step == "rate":
        try:
            r = float(re.sub(r"\s", "", text).replace(",", "."))
        except ValueError:
            r = 0
        if r <= 0:
            return await ctx.send("❗ Kursni raqam bilan yozing, masalan: 12050")
        d["rate"] = str(r)
        d["amount"] = str(round(D(d["orig"]) * D(r)))
        return await next_step(ctx, d)
    if step == "comment":
        d["com"], d["ca"] = text[:300], True
        return await next_step(ctx, d)
    if step == "ord_text":
        ref = text.lstrip("#").strip()[:20]
        if not re.fullmatch(r"[\w\-А-Яа-яЁё]+", ref):
            return await ctx.send("❗ Faqat ID raqamini yozing, masalan: 406")
        info_ = await A.order_label(ctx, ref)
        d["ord"], d["oa"] = (info_["ref"] if info_ else ref), True
        await ctx.send(
            "✔️ "
            + (
                T.order_line(info_["ref"], info_)
                if info_
                else f"🧾 {esc(ref)} <i>(ro'yxatda yo'q — shu ID bilan yoziladi)</i>"
            )
        )
        return await next_step(ctx, d)
    return await ctx.send("Yuqoridagi tugmalardan birini tanlang yoki /bekor.")


async def amount_text(ctx: Ctx, d: dict, text: str):
    """Amount typed in the «amount» step: parsed by the backend (`finance/parse/`)."""
    err = "❗ Summani tushunmadim. Masalan: 250000, 1.5 mln yoki 100$"
    try:
        res = await ctx.api("POST", "finance/parse/", json={"text": text, "mode": "money"})
    except ServiceRefusal:
        # dollars without any rate: take the number as typed, then ask for the rate
        res = None
        if USD_WORDS.search(text):
            plain = await ctx.api(
                "POST", "finance/parse/", json={"text": USD_WORDS.sub(" ", text), "mode": "money"}
            )
            if plain:
                d.update(cur="USD", orig=str(plain["amount"]), amount=None, rate=None)
                return await next_step(ctx, d)
        return await ctx.send(err)
    if not res:
        return await ctx.send(err)
    if res["cur"] == "USD":
        d.update(cur="USD", orig=res["orig"], rate=res["rate"], amount=str(round(D(res["amount"]))))
    else:
        d.update(cur="UZS", orig=None, rate=None, amount=str(round(D(res["amount"]))))
    return await next_step(ctx, d)


async def attach_receipt(ctx: Ctx, d: dict, fid: str):
    await ctx.clr_st()
    op = await ctx.api("POST", f"finance/operations/{d['tx']}/receipt/", json={"file_id": fid})
    await ctx.send(f"📎 Chek #{op['number']} ga biriktirildi.")


# ====================================================================== callbacks of the flow
async def ask_delete(ctx: Ctx, number: int):
    msg = "❗ Bu amalni o'chira olmaysiz (topilmadi, sizniki emas yoki 2 kundan eski — rahbarga murojaat qiling)."
    try:
        op = await ctx.get(f"finance/operations/{number}/")
    except (NotFound, Forbidden):
        return await ctx.send(msg)
    if not op.get("can_delete"):
        return await ctx.send(msg)
    await ctx.send(
        "🗑 Rostdan o'chirilsinmi?\n\n" + await op_text(ctx, op),
        ik([[b("🗑 Ha, o'chirish", f"delok:{number}"), b("Yo'q", "cancel")]]),
    )


async def delete_ok(ctx: Ctx, number: int):
    try:
        res = await ctx.api("DELETE", f"finance/operations/{number}/")
    except (Forbidden, ServiceRefusal, NotFound):
        return await ctx.show("❗ O'chirib bo'lmadi.")
    n = len(res.get("deleted") or [])
    await ctx.show(f"🗑 #{number} o'chirildi." + (" (o'tkazmaning ikkala tomoni)" if n > 1 else ""))


async def receipt_start(ctx: Ctx, number: int):
    try:
        op = await ctx.get(f"finance/operations/{number}/")
        ok = bool(op.get("can_attach"))
    except (NotFound, Forbidden):
        ok = False
    if not ok:
        return await ctx.send("❗ Bu amalga chek qo'sha olmaysiz.")
    await ctx.set_st({"step": "attach", "tx": number})
    await ctx.send(f"📎 #{number} uchun chek rasmini yuboring.")


async def tx_callback(ctx: Ctx, cmd: str, arg: str, d: dict | None) -> bool:
    """Buttons of the draft. True when handled."""
    edit = ctx.show
    if d and d.get("step") == "worker":
        if cmd == "wg":
            workers = await A.workers(ctx)
            groups = K.worker_groups(workers)
            gi = int(arg)
            await ctx.set_st(d)
            await ctx.show(f"👷 {esc(groups[gi] if gi < len(groups) else '')}:", K.worker_kb(workers, gi))
            return True
        if cmd == "wb":
            await ctx.show("👷 Kimga oylik berildi? Bo'limni tanlang:", K.group_kb(await A.workers(ctx)))
            return True
        if cmd in ("wk", "wt"):
            workers = await A.workers(ctx)
            if cmd == "wk":
                w = next((x for x in workers if str(x["id"]) == arg), None)
                name = w["name"] if w else ""
            else:
                groups = K.worker_groups(workers)
                name = K.team_name(groups[int(arg)]) if int(arg) < len(groups) else ""
            if not name:
                return True
            d["worker"] = name
            await edit("✔️ " + T.worker_line(name, workers))
            await next_step(ctx, d)
            return True
    if cmd == "pay" and d and d.get("step") == "paytype" and arg in ("Avans", "Oylik"):
        d["pay"] = arg
        await edit("✔️ " + T.pay_label(arg))
        await next_step(ctx, d)
        return True
    if cmd == "car" and d and d.get("step") == "car":
        car = next((c for c in await A.cars(ctx) if str(c["id"]) == arg), None)
        d["worker"] = car["name"] if car else ""
        await edit(f"✔️ 🚗 {esc(d['worker'])}")
        await next_step(ctx, d)
        return True
    if cmd == "cat" and d and d.get("step") == "category":
        c = await A.category(ctx, arg)
        if not c or (c["admin_only"] and not ctx.admin):
            return True
        d["cat"] = arg
        await edit("✔️ " + T.cat_label(c))
        await next_step(ctx, d)
        return True
    if cmd == "oarx" and d and d.get("step") == "order":
        if arg == "back":
            cat = await A.category(ctx, d["cat"])
            await ctx.show("🧾 Qaysi buyurtma (mijoz ID) uchun?", await order_choice_kb(ctx, d, cat))
            return True
        orders = await ctx.get("finance/orders/archive/")
        kb, n, pg, pages = K.arx_kb(orders, int(arg or 0))
        if not n:
            await ctx.show(
                "🗄 Arxiv hozircha bo'sh (oxirgi 4 oyda «Готов» bo'lgan buyurtma topilmadi).", kb
            )
        else:
            await ctx.show(
                f"🗄 <b>Arxiv</b> — oxirgi 4 oyda «Готов» bo'lgan buyurtmalar ({n})"
                + (f" · {pg + 1}/{pages}" if pages > 1 else "")
                + ":",
                kb,
            )
        return True
    if cmd == "ord" and d and d.get("step") == "order":
        d["ord"], d["oa"] = (None if arg == "-" else arg), True
        info_ = await A.order_label(ctx, d["ord"]) if d["ord"] else None
        await edit("✔️ " + T.order_line(d["ord"], info_))
        await next_step(ctx, d)
        return True
    if cmd == "save":
        await save_tx(ctx, d)
        return True
    if cmd == "edit" and d and d.get("step") == "confirm":
        if arg == "amount":
            d.update(amount=None, orig=None, cur="UZS", rate=None, mr=False)
        if arg == "rate":
            d.update(rate=None, amount=None, mr=True)
        if arg == "category":
            d.update(
                cat=None,
                give=False,
                worker=None,
                pay=None,
                oa=bool(d.get("ord")),
                ca=bool(d.get("com")),
            )
        if arg == "order":
            d["oa"] = False
        await ctx.clear_kb()
        await next_step(ctx, d)
        return True
    return False


async def skip_callback(ctx: Ctx, arg: str, d: dict | None) -> bool:
    """«⏭ O'tkazib yuborish» of the tx steps; the other tags live with their flows."""
    if not d:
        return True
    step = d.get("step")
    if arg == "comment" and step == "comment":
        d["ca"] = True
    elif arg == "receipt" and step == "receipt":
        d["ra"] = True
    else:
        return False
    await ctx.show("⏭ O'tkazildi")
    await next_step(ctx, d)
    return True


__all__ = [
    "Decimal",
    "BackendError",
    "start_tx",
    "next_step",
    "save_tx",
    "tx_text",
    "tx_callback",
    "skip_callback",
]
