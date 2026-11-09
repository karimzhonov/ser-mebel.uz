"""Kirim (stock in) and chiqim (stock out) flows. Prices, stock checks and the average cost
are the backend's: chiqim sends no price (the backend uses avg_cost) but one or more client
IDs with a quantity each; kirim needs a price."""

from __future__ import annotations

import logging
import re
from decimal import Decimal

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api
from .. import keyboards as K
from .. import photos as P
from .. import texts as T
from ..parse import parse_price, parse_qty
from ..states import WhIn, WhOut
from . import util as U

log = logging.getLogger("bot.warehouse.handlers.move")

IN_RE = re.compile(r"^wh:i:(\d+)$")
OUT_RE = re.compile(r"^wh:o:(\d+)$")
OT_RE = re.compile(r"^wh:ot:(\d+):(\d+)$")
OP_RE = re.compile(r"^wh:op:(\d+):(\d+)$")
ID_RE = re.compile(r"^[#№]?[\w-]{1,32}$")
TXT = F.text & ~F.text.startswith("/")


def _last_text(last: dict | None) -> str:
    if not last:
        return ""
    if last.get("currency") == "USD" and last.get("orig_price"):
        return T.price_line(last["orig_price"], "USD")
    return T.price_line(last.get("unit_price") or 0, "UZS") if last.get("unit_price") else ""


def _price_kb(last: dict | None):
    extra = []
    if _last_text(last):
        extra.append(K.b(f"♻️ {_last_text(last)}", "wh:lp"))
    return K.cancel_kb() if not extra else K.ik([extra, [K.b("❌ Bekor qilish", "wh:x")]])


def _party_kb(last: dict | None):
    extra = []
    if last and last.get("counterparty"):
        extra.append(K.b(f"♻️ {last['counterparty'][:40]}", "wh:lc"))
    return K.skip_kb(*extra)


async def _ask_confirm(target, state: FSMContext, d: dict, kind: str) -> None:
    """Send the confirm screen (`target` is a Message to answer on)."""
    await U.update(state, WhIn.confirm if kind == "in" else WhOut.confirm)
    text = T.confirm_in(d) if kind == "in" else T.confirm_out(d)
    await target.answer(text, reply_markup=K.confirm_kb())


def build() -> Router:
    r = Router(name="warehouse_move")

    # ================================================================ start
    async def _start(cb: CallbackQuery, state: FSMContext, pid: int, kind: str):
        uid = cb.from_user.id
        try:
            res = await U.get_product(uid, pid)
            meta = await api.call("GET", "warehouse/meta/", actor=uid)
        except api.BackendError as e:
            await U.alert(cb, e)
            return
        p = res["product"]
        draft = {
            "pid": pid,
            "name": p["name"],
            "unit": p.get("unit_label", ""),
            "stock": str(p.get("quantity") or "0"),
            "avg": str(p.get("avg_cost") or "0"),
            "rate": str(meta.get("usd_rate") or "0"),
            "last": res.get("last_in") if kind == "in" else None,
        }
        if kind == "out":
            try:
                res = await api.call("GET", "warehouse/orders/", actor=uid)
            except api.BackendError as e:
                await U.alert(cb, e)
                return
            draft.update(
                cands=(res or {}).get("items") or [], sel=[], page=0, allocs=[], idx=0, v=0
            )
            await U.begin(state, WhOut.refs, **draft)
            await cb.answer()
            await U.drop_kb(cb)
            msg = await cb.message.answer(
                T.ask_refs(draft["unit"], p.get("quantity")), reply_markup=K.orders_kb(draft)
            )
            await U.update(state, list_mid=msg.message_id)
            return
        await U.begin(state, WhIn.qty, **draft)
        await cb.answer()
        await U.drop_kb(cb)
        await cb.message.answer(T.ask_in_qty(p["name"], draft["unit"]), reply_markup=K.cancel_kb())

    @r.callback_query(F.data.regexp(IN_RE))
    async def start_in(cb: CallbackQuery, state: FSMContext):
        await _start(cb, state, int(IN_RE.match(cb.data).group(1)), "in")

    @r.callback_query(F.data.regexp(OUT_RE))
    async def start_out(cb: CallbackQuery, state: FSMContext):
        await _start(cb, state, int(OUT_RE.match(cb.data).group(1)), "out")

    # ================================================================ kirim
    @r.message(StateFilter(WhIn.qty), TXT)
    async def in_qty(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, d = gate
        qty = parse_qty(text)
        if qty is None:
            await message.answer(T.BAD_QTY, reply_markup=K.cancel_kb())
            return
        await U.update(state, WhIn.price, qty=str(qty))
        await message.answer(
            T.ask_price(d["rate"], _last_text(d.get("last"))), reply_markup=_price_kb(d.get("last"))
        )

    async def _after_price(target, state: FSMContext, amount, cur: str) -> None:
        d = await U.update(state, WhIn.party, price=str(amount), cur=cur)
        await target.answer(T.ASK_IN_PARTY, reply_markup=_party_kb(d.get("last")))

    @r.message(StateFilter(WhIn.price), TXT)
    async def in_price(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, d = gate
        parsed = parse_price(text)
        if parsed is None:
            await message.answer(T.BAD_PRICE, reply_markup=_price_kb(d.get("last")))
            return
        await _after_price(message, state, *parsed)

    @r.callback_query(F.data == "wh:lp", StateFilter(WhIn.price))
    async def in_last_price(cb: CallbackQuery, state: FSMContext):
        d = await U.cb_gate(cb, state)
        if d is None:
            return
        last = d.get("last") or {}
        if last.get("currency") == "USD" and last.get("orig_price"):
            amount, cur = Decimal(str(last["orig_price"])), "USD"
        elif last.get("unit_price"):
            amount, cur = Decimal(str(last["unit_price"])), "UZS"
        else:
            await cb.answer(T.GONE, show_alert=True)
            return
        await cb.answer()
        await U.drop_kb(cb)
        await _after_price(cb.message, state, amount, cur)

    @r.message(StateFilter(WhIn.party), TXT)
    async def in_party(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, _ = gate
        d = await U.update(state, party=text[:120])
        await _ask_confirm(message, state, d, "in")

    @r.callback_query(F.data.in_({"wh:lc", "wh:sk"}), StateFilter(WhIn.party))
    async def in_party_btn(cb: CallbackQuery, state: FSMContext):
        d = await U.cb_gate(cb, state)
        if d is None:
            return
        party = ((d.get("last") or {}).get("counterparty") or "") if cb.data == "wh:lc" else ""
        d = await U.update(state, party=party)
        await cb.answer()
        await U.drop_kb(cb)
        await _ask_confirm(cb.message, state, d, "in")

    # ================================================================ chiqim
    async def _redraw(target, state: FSMContext, d: dict, note: str = "") -> None:
        """Send the picker as a NEW message; the previous one loses its buttons."""
        old = d.get("list_mid")
        if old:
            try:
                await target.bot.edit_message_reply_markup(
                    chat_id=target.chat.id, message_id=old, reply_markup=None
                )
            except TelegramAPIError:
                pass
        msg = await target.answer(
            T.ask_refs(d["unit"], d["stock"], d.get("sel"), note), reply_markup=K.orders_kb(d)
        )
        await U.update(state, list_mid=msg.message_id)

    def _add_ref(d: dict, item: dict) -> None:
        """Make `item` selected (and a visible candidate)."""
        if not any(c["ref"] == item["ref"] for c in d["cands"]):
            d["cands"].append(item)
        if not any(x["ref"] == item["ref"] for x in d["sel"]):
            d["sel"].append({"ref": item["ref"], "client": item.get("client") or ""})
            d["page"] = (len(d["cands"]) - 1) // K.REF_PAGE

    @r.message(StateFilter(WhOut.refs), TXT)
    async def out_refs_text(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, d = gate
        uid = message.from_user.id
        tokens = [t for t in re.split(r"[\s,;]+", text) if t]
        try:
            if tokens and all(ID_RE.match(t) and re.search(r"\d", t) for t in tokens):
                res = await api.call(
                    "POST", "warehouse/orders/resolve/", actor=uid, json={"text": text}
                )
                for item in (res or {}).get("items") or []:
                    _add_ref(d, item)
                unknown = (res or {}).get("unknown") or []
                note = T.UNKNOWN.format(refs=T.esc(", ".join(unknown))) if unknown else ""
            else:
                res = await api.call("GET", "warehouse/orders/", actor=uid, params={"q": text[:60]})
                found = (res or {}).get("items") or []
                for x in d["sel"]:  # keep the selected ones visible
                    if not any(c["ref"] == x["ref"] for c in found):
                        found.append(x)
                d["cands"], d["page"] = found, 0
                d["v"] = int(d.get("v") or 0) + 1
                note = "" if found else T.NOTHING
        except api.BackendError as e:
            await message.answer(api.err_text(e))
            return
        d = await U.update(
            state, cands=d["cands"], sel=d["sel"], page=d.get("page", 0), v=d.get("v", 0)
        )
        await _redraw(message, state, d, note)

    async def _refs_cb(cb: CallbackQuery, state: FSMContext):
        d = await U.cb_gate(cb, state)
        if d is None:
            return None
        return d

    @r.callback_query(F.data.regexp(OT_RE), StateFilter(WhOut.refs))
    async def out_toggle(cb: CallbackQuery, state: FSMContext):
        d = await _refs_cb(cb, state)
        if d is None:
            return
        v, i = (int(x) for x in OT_RE.match(cb.data).groups())
        if v != int(d.get("v") or 0) or i >= len(d["cands"]):
            await cb.answer(T.GONE, show_alert=True)
            return
        c = d["cands"][i]
        if any(x["ref"] == c["ref"] for x in d["sel"]):
            d["sel"] = [x for x in d["sel"] if x["ref"] != c["ref"]]
        else:
            d["sel"].append({"ref": c["ref"], "client": c.get("client") or ""})
        d = await U.update(state, sel=d["sel"])
        await cb.answer()
        await _set_markup(cb, d)

    @r.callback_query(F.data.regexp(OP_RE), StateFilter(WhOut.refs))
    async def out_page(cb: CallbackQuery, state: FSMContext):
        d = await _refs_cb(cb, state)
        if d is None:
            return
        v, page = (int(x) for x in OP_RE.match(cb.data).groups())
        if v != int(d.get("v") or 0):
            await cb.answer(T.GONE, show_alert=True)
            return
        d = await U.update(state, page=page)
        await cb.answer()
        await _set_markup(cb, d)

    async def _set_markup(cb: CallbackQuery, d: dict) -> None:
        try:
            await cb.message.edit_text(
                T.ask_refs(d["unit"], d["stock"], d.get("sel")), reply_markup=K.orders_kb(d)
            )
        except TelegramAPIError:
            log.info("refs redraw failed", exc_info=True)

    @r.callback_query(F.data == "wh:o0", StateFilter(WhOut.refs))
    async def out_no_client(cb: CallbackQuery, state: FSMContext):
        d = await _refs_cb(cb, state)
        if d is None:
            return
        await U.update(state, WhOut.qty, sel=[], allocs=[])
        await cb.answer()
        await U.drop_kb(cb)
        await cb.message.answer(
            T.ask_out_qty(d["name"], d["unit"], d["stock"]), reply_markup=K.cancel_kb()
        )

    async def _ask_alloc(target, d: dict) -> None:
        done = sum((Decimal(a["qty"]) for a in d["allocs"]), Decimal(0))
        left = Decimal(d["stock"]) - done
        await target.answer(
            T.ask_alloc(d["sel"][d["idx"]], left, d["unit"]), reply_markup=K.cancel_kb()
        )

    @r.callback_query(F.data == "wh:on", StateFilter(WhOut.refs))
    async def out_go(cb: CallbackQuery, state: FSMContext):
        d = await _refs_cb(cb, state)
        if d is None:
            return
        if not d["sel"]:
            await cb.answer(T.NO_REFS, show_alert=True)
            return
        d = await U.update(state, WhOut.alloc, allocs=[], idx=0)
        await cb.answer()
        await U.drop_kb(cb)
        await _ask_alloc(cb.message, d)

    @r.message(StateFilter(WhOut.alloc), TXT)
    async def out_alloc(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, d = gate
        qty = parse_qty(text)
        if qty is None:
            await message.answer(T.BAD_QTY, reply_markup=K.cancel_kb())
            return
        done = sum((Decimal(a["qty"]) for a in d["allocs"]), Decimal(0))
        left = Decimal(d["stock"]) - done
        if qty > left:
            await message.answer(
                T.NOT_ENOUGH.format(left=T.q(left), unit=T.esc(d["unit"])),
                reply_markup=K.cancel_kb(),
            )
            return
        ref = d["sel"][d["idx"]]
        allocs = d["allocs"] + [{"ref": ref["ref"], "client": ref["client"], "qty": str(qty)}]
        idx = d["idx"] + 1
        d = await U.update(state, allocs=allocs, idx=idx)
        if idx < len(d["sel"]):
            await _ask_alloc(message, d)
        else:
            await U.update(state, WhOut.party)
            await message.answer(T.ASK_OUT_PARTY, reply_markup=K.skip_kb())

    @r.message(StateFilter(WhOut.qty), TXT)
    async def out_qty(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, _ = gate
        qty = parse_qty(text)
        if qty is None:
            await message.answer(T.BAD_QTY, reply_markup=K.cancel_kb())
            return
        await U.update(state, WhOut.party, qty=str(qty))
        await message.answer(T.ASK_OUT_PARTY, reply_markup=K.skip_kb())

    @r.message(StateFilter(WhOut.party), TXT)
    async def out_party(message: Message, state: FSMContext):
        gate = await U.text_gate(message, state)
        if gate is None:
            return
        text, _ = gate
        d = await U.update(state, party=text[:120])
        await _ask_confirm(message, state, d, "out")

    @r.callback_query(F.data == "wh:sk", StateFilter(WhOut.party))
    async def out_skip(cb: CallbackQuery, state: FSMContext):
        d = await U.cb_gate(cb, state)
        if d is None:
            return
        await cb.answer()
        await U.drop_kb(cb)
        d = await U.update(state, party="")
        await _ask_confirm(cb.message, state, d, "out")

    # ================================================================ save
    @r.callback_query(F.data == "wh:ok", StateFilter(WhIn.confirm, WhOut.confirm))
    async def save(cb: CallbackQuery, state: FSMContext):
        d = await U.cb_gate(cb, state)
        if d is None:
            return
        kind = "in" if (await state.get_state()) == WhIn.confirm.state else "out"
        body: dict = {"product": d["pid"], "kind": kind}
        if kind == "in":
            body["quantity"] = d["qty"]
            body["currency"] = d["cur"]
            body["orig_price" if d["cur"] == "USD" else "unit_price"] = d["price"]
            if d.get("party"):
                body["counterparty"] = d["party"]
        else:
            if d.get("allocs"):
                body["allocations"] = [{"ref": a["ref"], "quantity": a["qty"]} for a in d["allocs"]]
            else:
                body["quantity"] = d["qty"]
            if d.get("party"):
                body["counterparty"] = d["party"]
        uid = cb.from_user.id
        try:
            res = await api.call("POST", "warehouse/movements/", actor=uid, json=body)
        except api.BackendError as e:
            log.info("movement failed for %s: %s", uid, e)
            if isinstance(e, api.ServiceRefusal) and await _reask(cb, state, kind, e):
                return
            await U.clear(state)
            await cb.answer()
            await U.drop_kb(cb)
            await cb.message.answer(api.err_text(e))
            return
        await U.clear(state)
        await cb.answer(T.SAVED)
        await U.drop_kb(cb)
        await P.show_card(cb.bot, U.chat_id(cb), uid, res["product"])

    async def _reask(cb: CallbackQuery, state: FSMContext, kind: str, e: api.BackendError) -> bool:
        """A 400 about the field of an earlier step: go back to that step."""
        d = await state.get_data()
        err = api.err_text(e)
        by_client = kind == "out" and bool(d.get("allocs"))
        steps = {
            "in": {"quantity": WhIn.qty, "unit_price": WhIn.price, "orig_price": WhIn.price},
            "out": {"quantity": WhOut.qty},
        }[kind]
        if not (by_client and e.field in ("allocations", "quantity")) and e.field not in steps:
            return False
        await cb.answer()
        await U.drop_kb(cb)
        if by_client and e.field == "allocations":
            d = await U.update(state, WhOut.refs, allocs=[], idx=0)
            await _redraw(cb.message, state, d, err)
        elif by_client:
            stock = d.get("stock")
            try:  # the stock may have moved: «qoldi» must be right
                stock = str((await U.get_product(cb.from_user.id, d["pid"]))["product"]["quantity"])
            except (api.BackendError, KeyError):
                log.info("stock refresh failed for product %s", d.get("pid"))
            d = await U.update(state, WhOut.alloc, allocs=[], idx=0, stock=stock)
            await cb.message.answer(err)
            await _ask_alloc(cb.message, d)
        else:
            target = steps[e.field]
            d = await U.update(state, target)
            prompts = {
                WhIn.qty.state: T.ask_in_qty(d["name"], d["unit"]),
                WhOut.qty.state: T.ask_out_qty(d["name"], d["unit"], d["stock"]),
                WhIn.price.state: T.ask_price(d["rate"], _last_text(d.get("last"))),
            }
            kb = {WhIn.price.state: _price_kb(d.get("last"))}.get(target.state, K.cancel_kb())
            await cb.message.answer(f"{err}\n\n{prompts[target.state]}", reply_markup=kb)
        return True

    return r
