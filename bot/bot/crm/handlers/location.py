"""Telegram location -> the right lead / metering.

A location (own or forwarded) from a person who may set locations asks «Qaysi mijoz?»,
lists the candidates the backend suggests (or looks them up by phone) and POSTs the pick to
`crm/locations/`. While a «Yangi mijoz» form is open the location is simply carried into it.
Anything outside these cases (a finance draft, a group chat) is not touched: the filters
refuse and the update falls through to the next router. The FSM state is `LocPick:target`
(default destiny, Redis); the location waits in the FSM data under `location`.
"""

from __future__ import annotations

import logging
import re
import time

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import BaseFilter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.hr.texts import FINANCE_MENU_BUTTONS

from .. import api
from .. import keyboards as K
from .. import texts as T
from ..states import Lead, LocPick
from . import lead

log = logging.getLogger("bot.crm.location")

LOC_CB = re.compile(r"^crm:loc:([im]):(\d+)$")
PHONE_RE = re.compile(r"^\+?[\d\s\-()]{7,20}$")
LOC_TTL = 600  # seconds a pending pick stays valid
# every Lead step except the in-flight save
LEAD_OPEN = StateFilter(
    Lead.name, Lead.phone, Lead.source, Lead.note, Lead.remind, Lead.remind_custom, Lead.confirm
)


class CanSetLocation(BaseFilter):
    """The backend said can_set_location and the default-destiny FSM state is empty or
    already `LocPick:*`; any other state (a finance draft, a lead form) is not ours."""

    async def __call__(self, event, state: FSMContext, actor=None) -> bool:
        if actor is None or not getattr(actor, "can_set_location", False):
            return False
        cur = await state.get_state()
        return cur is None or cur.startswith("LocPick:")


def _loc_of(message: Message) -> dict:
    loc = message.location
    venue = message.venue
    return {
        "lat": loc.latitude,
        "lon": loc.longitude,
        "address": (venue.address or "") if venue else "",
        "live": bool(getattr(loc, "live_period", None)),
    }


def _expired(data: dict) -> bool:
    ts = data.get("ts")
    return not isinstance(ts, (int, float)) or time.time() - ts > LOC_TTL


def _menu_free(message: Message) -> bool:
    return (message.text or "").strip() not in FINANCE_MENU_BUTTONS and message.text != T.NEW_BTN


async def _drop_kb(cb: CallbackQuery) -> None:
    m = cb.message
    if isinstance(m, Message):
        try:
            await m.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            log.info("clear keyboard failed", exc_info=True)


def build() -> Router:
    r = Router(name="crm_location")
    plain = F.text & ~F.text.startswith("/") & ~F.forward_origin & F.func(_menu_free)

    # 1. a location while the lead form is open: carried into the lead
    @r.message(F.location, LEAD_OPEN)
    async def loc_in_lead(message: Message, state: FSMContext):
        loc = _loc_of(message)
        await state.update_data(location=loc)
        text = T.LOC_IN_LEAD + ("\n\n" + T.LOC_LIVE if loc["live"] else "")
        await message.answer(text)

    # 2. a location from a person who may set locations: pick the client
    @r.message(F.location, CanSetLocation())
    async def loc_received(message: Message, state: FSMContext):
        loc = _loc_of(message)
        uid = message.from_user.id
        try:
            res = await api.call("GET", "crm/locations/candidates/", actor=uid)
        except api.BackendError as e:
            log.warning("location candidates failed for %s: %s", uid, e)
            await state.clear()
            await message.answer(api.err_text(e))
            return
        res = res or {}
        items = res.get("items") or []
        can_new = bool(res.get("can_new_lead"))
        await state.set_state(LocPick.target)
        await state.set_data({"location": loc, "ts": time.time()})
        text = T.LOC_ASK if items else T.LOC_ASK_EMPTY
        if loc["live"]:
            text += "\n\n" + T.LOC_LIVE
        await message.answer(text, reply_markup=K.loc_targets_kb(items, can_new))

    # 3. a phone typed while waiting for the pick
    @r.message(plain, F.text.regexp(PHONE_RE), StateFilter(LocPick.target))
    async def loc_phone(message: Message, state: FSMContext):
        uid = message.from_user.id
        if _expired(await state.get_data()):
            await state.clear()
            raise SkipHandler
        phone = lead._norm_phone(message.text)
        try:
            res = await api.call(
                "GET", "crm/locations/candidates/", actor=uid, params={"phone": phone}
            )
        except api.ServiceRefusal as e:
            await message.answer(api.err_text(e) + "\n\n" + T.LOC_ASK)
            return
        except api.BackendError as e:
            log.warning("location lookup failed for %s: %s", uid, e)
            await message.answer(api.err_text(e))
            return
        res = res or {}
        items = res.get("items") or []
        can_new = bool(res.get("can_new_lead"))
        if not items:
            await state.update_data(prefill_phone=phone)
            await message.answer(T.LOC_PHONE_NONE, reply_markup=K.loc_targets_kb([], can_new))
            return
        await message.answer(T.LOC_ASK, reply_markup=K.loc_targets_kb(items, can_new))

    # 3b. anything else (text, command, menu button, media) is not ours: drop the pick and
    # let the later routers (finance / HR) see the update with a clean state
    @r.message(~F.location, StateFilter(LocPick.target))
    async def loc_other(message: Message, state: FSMContext):
        await state.clear()
        raise SkipHandler

    # 4. the pick
    @r.callback_query(F.data.regexp(LOC_CB), StateFilter(LocPick.target))
    async def loc_pick(cb: CallbackQuery, state: FSMContext):
        kind_code, tid = LOC_CB.match(cb.data).groups()
        d = await state.get_data()
        loc = d.get("location") or {}
        if _expired(d) or "lat" not in loc or "lon" not in loc:
            await state.clear()
            await cb.answer(T.STALE)
            return
        body: dict = {
            "target": {"kind": "invoice" if kind_code == "i" else "metering", "id": int(tid)},
            "lat": loc["lat"],
            "lon": loc["lon"],
        }
        if loc.get("address"):
            body["address"] = loc["address"]
        if loc.get("live"):
            body["live"] = True
        try:
            res = await api.call("POST", "crm/locations/", actor=cb.from_user.id, json=body)
        except api.BackendError as e:
            log.warning("location save failed for %s: %s", cb.from_user.id, e)
            try:
                await cb.answer(api.err_text(e).removeprefix("❗ ")[:200], show_alert=True)
            except TelegramAPIError:
                log.info("alert failed", exc_info=True)
            return  # state stays: the person may pick another target
        await state.clear()
        await cb.answer()
        await _drop_kb(cb)
        res = res or {}
        if isinstance(cb.message, Message):
            await cb.message.answer(
                T.loc_saved(res),
                reply_markup=K.loc_done_kb(res.get("map_url") or "", res.get("url") or ""),
            )

    # 5. the client is new: run the lead form with the location attached
    @r.callback_query(F.data == "crm:loc:new", StateFilter(LocPick.target))
    async def loc_new(cb: CallbackQuery, state: FSMContext, actor=None):
        if actor is None or not getattr(actor, "can_add_lead", False):
            await cb.answer(T.STALE)
            return
        d = await state.get_data()
        if _expired(d):
            await state.clear()
            await cb.answer(T.STALE)
            return
        await cb.answer()
        await _drop_kb(cb)
        if isinstance(cb.message, Message):
            await lead._start(
                cb.message,
                state,
                {"location": d.get("location"), "prefill_phone": d.get("prefill_phone") or ""},
            )

    # 6. cancel
    @r.callback_query(F.data == "crm:loc:x", StateFilter(LocPick.target))
    async def loc_cancel(cb: CallbackQuery, state: FSMContext):
        await state.clear()
        await cb.answer(T.CANCELLED)
        await _drop_kb(cb)
        if isinstance(cb.message, Message):
            await cb.message.answer(T.CANCELLED)

    # old buttons (no LocPick state any more): never touch other flows' state
    @r.callback_query(F.data.startswith("crm:loc:"))
    async def loc_stale(cb: CallbackQuery):
        try:
            await cb.answer(T.STALE)
        except TelegramAPIError:
            pass

    return r
