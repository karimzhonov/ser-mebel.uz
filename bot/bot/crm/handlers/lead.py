"""The «Yangi mijoz» FSM: name -> phone -> source -> note -> reminder -> confirm -> save.

Entry points: «🆕 Yangi mijoz», /mijoz, a forwarded client message, a shared contact.
The entry filter only lets a person in who may add leads and whose default-destiny FSM
state is empty or already a `Lead:*` one, so a finance draft is never clobbered and
forwards / contacts of everybody else fall through to the next router untouched.
"""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import BaseFilter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, MessageOriginHiddenUser, MessageOriginUser

from bot.common.fmt import clip, esc
from bot.hr.texts import FINANCE_MENU_BUTTONS

from .. import api
from .. import keyboards as K
from .. import texts as T
from ..states import Lead

log = logging.getLogger("bot.crm.lead")

CMD_NEW = re.compile(r"^/mijoz(@\w+)?\s*$", re.I)
CMD_CANCEL = re.compile(r"^/(bekor|cancel)(@\w+)?\s*$", re.I)
NOTE_MAX = 1000
FIELD_STEP = {"name": "name", "phone": "phone", "source": "source", "remind": "remind"}


class CanAddLead(BaseFilter):
    """Private chat is the router's filter. Here: the backend said can_add_lead and no
    foreign (finance) FSM state is active. With `forwards=True` a finance member is also
    refused outside a Lead state: their forwards (receipts, expense texts) belong to
    finance; they start a lead with /mijoz or the button."""

    def __init__(self, forwards: bool = False):
        self.forwards = forwards

    async def __call__(self, event, state: FSMContext, actor=None) -> bool:
        if actor is None or not getattr(actor, "can_add_lead", False):
            return False
        cur = await state.get_state()
        if cur is not None:
            return cur.startswith("Lead:")
        return not (self.forwards and getattr(actor, "member", None))


def _norm_phone(raw: str) -> str:
    s = (raw or "").strip()
    if (
        s
        and not s.startswith("+")
        and re.fullmatch(r"[\d\s\-()]+", s)
        and len(re.sub(r"\D", "", s)) >= 11
    ):
        return "+" + re.sub(r"\D", "", s)
    return s


def _prefill_from_forward(message: Message) -> dict:
    """{prefill_name, note, source} out of a forwarded message."""
    origin = message.forward_origin
    name, username = "", ""
    if isinstance(origin, MessageOriginUser):
        u = origin.sender_user
        name, username = u.full_name, u.username or ""
    elif isinstance(origin, MessageOriginHiddenUser):
        name = origin.sender_user_name
    body = (message.text or message.caption or "").strip()
    note = clip(body, NOTE_MAX) if body else "[media]"
    if username:
        note = f"@{username}\n{note}"
    return {"prefill_name": name, "note": note, "source": "telegram"}


# ------------------------------------------------------------------ steps
async def _send(target: Message, text: str, kb=None):
    return await target.answer(text, reply_markup=kb)


async def _drop_kb(cb: CallbackQuery) -> None:
    m = cb.message
    if isinstance(m, Message):
        try:
            await m.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            log.info("clear keyboard failed", exc_info=True)


async def go_name(target: Message, state: FSMContext, prefix: str = "") -> None:
    d = await state.get_data()
    await state.set_state(Lead.name)
    await _send(target, prefix + T.ASK_NAME, K.name_kb(d.get("prefill_name") or ""))


async def go_phone(target: Message, state: FSMContext, prefix: str = "") -> None:
    d = await state.get_data()
    await state.set_state(Lead.phone)
    await _send(target, prefix + T.ASK_PHONE, K.phone_kb(d.get("prefill_phone") or ""))


async def go_source(target: Message, state: FSMContext, prefix: str = "") -> None:
    d = await state.get_data()
    await state.set_state(Lead.source)
    await _send(
        target,
        prefix + T.ASK_SOURCE,
        K.source_kb(d.get("source") or "", d.get("client_fio") or ""),
    )


async def go_note(target: Message, state: FSMContext, prefix: str = "") -> None:
    d = await state.get_data()
    await state.set_state(Lead.note)
    cur = d.get("note") or ""
    text = prefix + T.ASK_NOTE
    if cur:
        text += f"\n\n<i>{esc(clip(cur, 300))}</i>"
    await _send(target, text, K.note_kb(bool(cur)))


async def go_remind(target: Message, state: FSMContext, prefix: str = "") -> None:
    await state.set_state(Lead.remind)
    await _send(target, prefix + T.ASK_REMIND, K.remind_kb())


async def go_confirm(target: Message, state: FSMContext, prefix: str = "") -> None:
    d = await state.get_data()
    await state.set_state(Lead.confirm)
    await _send(target, prefix + T.summary(d), K.confirm_kb())


STEPS = {
    "name": go_name,
    "phone": go_phone,
    "source": go_source,
    "note": go_note,
    "remind": go_remind,
    "confirm": go_confirm,
}


async def _start(message: Message, state: FSMContext, seed: dict) -> None:
    await state.clear()
    await state.update_data(**seed)
    await go_name(message, state)


def _guard(fn):
    """Backend errors of a step are told to the person; the FSM state stays as it was."""

    async def wrapper(event, *a, **kw):
        try:
            return await fn(event, *a, **kw)
        except api.BackendError as e:
            log.warning("%s: %s", fn.__name__, e)
            target = event.message if isinstance(event, CallbackQuery) else event
            try:
                if isinstance(event, CallbackQuery):
                    await event.answer(api.err_text(e)[:200], show_alert=True)
                elif target is not None:
                    await target.answer(api.err_text(e))
            except TelegramAPIError:
                log.warning("could not report a backend error", exc_info=True)

    wrapper.__name__ = fn.__name__
    wrapper.__wrapped__ = fn  # keep aiogram's signature inspection on the original
    return wrapper


async def _accept_phone(target: Message, state: FSMContext, uid: int, phone: str) -> None:
    d = await state.get_data()
    try:
        info = await api.call("GET", "crm/clients/", actor=uid, params={"phone": phone})
    except api.ServiceRefusal as e:
        await _send(
            target, api.err_text(e) + "\n\n" + T.ASK_PHONE, K.phone_kb(d.get("prefill_phone") or "")
        )
        return
    prefix, fio = "", ""
    if (info or {}).get("exists"):
        prefix = T.known_client(info) + "\n\n"
        if info.get("fio") and info["fio"] != d.get("name"):
            fio = info["fio"]
    await state.update_data(phone=phone, client_fio=fio)
    await go_source(target, state, prefix)


def build() -> Router:
    r = Router(name="crm_lead")
    in_lead = StateFilter(Lead)

    # ---- cancel (only inside a lead flow: never touches a finance draft)
    @r.message(F.text.regexp(CMD_CANCEL), in_lead)
    async def cancel_cmd(message: Message, state: FSMContext):
        await state.clear()
        await message.answer(T.CANCELLED)

    @r.callback_query(F.data == "crm:cancel")
    async def cancel_cb(cb: CallbackQuery, state: FSMContext):
        cur = await state.get_state()
        if cur and cur.startswith("Lead:"):
            await state.clear()
            await cb.answer(T.CANCELLED)
            await _drop_kb(cb)
            if isinstance(cb.message, Message):
                await cb.message.answer(T.CANCELLED)
            return
        await cb.answer(T.STALE)

    # ---- entry points
    @r.message(F.forward_origin, CanAddLead(forwards=True))
    async def on_forward(message: Message, state: FSMContext):
        await _start(message, state, _prefill_from_forward(message))

    @r.message(F.text == T.NEW_BTN, CanAddLead())
    async def on_new_button(message: Message, state: FSMContext):
        await _start(message, state, {})

    @r.message(F.text.regexp(CMD_NEW), CanAddLead())
    async def on_new_cmd(message: Message, state: FSMContext):
        await _start(message, state, {})

    # ---- phone shared as a contact while the phone is asked
    @r.message(F.contact, StateFilter(Lead.phone))
    @_guard
    async def phone_contact(message: Message, state: FSMContext):
        await _accept_phone(
            message, state, message.from_user.id, _norm_phone(message.contact.phone_number)
        )

    @r.message(F.contact, CanAddLead())
    async def on_contact(message: Message, state: FSMContext):
        c = message.contact
        name = " ".join(x for x in (c.first_name, c.last_name) if x)
        await _start(
            message,
            state,
            {"prefill_name": name, "prefill_phone": _norm_phone(c.phone_number)},
        )

    # ---- text answers
    def _not_menu_button(message: Message) -> bool:
        # finance / HR reply-keyboard buttons (and NEW_BTN, registered there) are never answers
        return (message.text or "").strip() not in FINANCE_MENU_BUTTONS and (
            message.text != T.NEW_BTN
        )

    plain = F.text & ~F.text.startswith("/") & ~F.forward_origin & F.func(_not_menu_button)

    @r.message(plain, StateFilter(Lead.name))
    async def name_text(message: Message, state: FSMContext):
        await state.update_data(name=clip(message.text.strip(), 100))
        await go_phone(message, state)

    @r.message(plain, StateFilter(Lead.phone))
    @_guard
    async def phone_text(message: Message, state: FSMContext):
        await _accept_phone(message, state, message.from_user.id, _norm_phone(message.text))

    @r.message(plain, StateFilter(Lead.note))
    async def note_text(message: Message, state: FSMContext):
        await state.update_data(note=clip(message.text.strip(), NOTE_MAX))
        await go_remind(message, state)

    @r.message(plain, StateFilter(Lead.remind_custom))
    @_guard
    async def remind_text(message: Message, state: FSMContext):
        try:
            res = await api.call(
                "POST",
                "crm/due/parse/",
                actor=message.from_user.id,
                json={"text": message.text.strip()},
            )
        except api.ServiceRefusal as e:
            await _send(message, api.err_text(e) + "\n\n" + T.ASK_REMIND_CUSTOM, K.cancel_kb())
            return
        await state.update_data(remind={"at": str(res["due_at"])[:16]})
        await go_confirm(message, state)

    @r.message(plain, StateFilter(Lead.source, Lead.remind, Lead.confirm, Lead.saving))
    async def nudge(message: Message):
        await message.answer(T.USE_BUTTONS)

    # ---- buttons
    @r.callback_query(F.data == "crm:name:use", StateFilter(Lead.name))
    async def name_use(cb: CallbackQuery, state: FSMContext):
        d = await state.get_data()
        await cb.answer()
        await _drop_kb(cb)
        await state.update_data(name=d.get("prefill_name") or "")
        await go_phone(cb.message, state)

    @r.callback_query(F.data == "crm:name:client", StateFilter(Lead.source))
    async def name_client(cb: CallbackQuery, state: FSMContext):
        d = await state.get_data()
        if d.get("client_fio"):
            await state.update_data(name=d["client_fio"], client_fio="")
        await cb.answer("Ism almashtirildi")
        await _drop_kb(cb)
        await go_source(cb.message, state)

    @r.callback_query(F.data == "crm:phone:use", StateFilter(Lead.phone))
    @_guard
    async def phone_use(cb: CallbackQuery, state: FSMContext):
        d = await state.get_data()
        await cb.answer()
        await _drop_kb(cb)
        await _accept_phone(cb.message, state, cb.from_user.id, d.get("prefill_phone") or "")

    @r.callback_query(F.data.startswith("crm:src:"), StateFilter(Lead.source))
    async def source_pick(cb: CallbackQuery, state: FSMContext):
        key = cb.data.split(":", 2)[2]
        if key not in T.SOURCES:
            await cb.answer(T.STALE)
            return
        await state.update_data(source=key)
        await cb.answer()
        await _drop_kb(cb)
        await go_note(cb.message, state)

    @r.callback_query(F.data == "crm:note:skip", StateFilter(Lead.note))
    async def note_skip(cb: CallbackQuery, state: FSMContext):
        await cb.answer()
        await _drop_kb(cb)
        await go_remind(cb.message, state)

    @r.callback_query(F.data.startswith("crm:rem:"), StateFilter(Lead.remind))
    async def remind_pick(cb: CallbackQuery, state: FSMContext):
        kind = cb.data.split(":", 2)[2]
        await cb.answer()
        await _drop_kb(cb)
        if kind == "custom":
            await state.set_state(Lead.remind_custom)
            await _send(cb.message, T.ASK_REMIND_CUSTOM, K.cancel_kb())
            return
        if kind not in ("today", "tomorrow", "none"):
            return
        await state.update_data(remind={"preset": kind})
        await go_confirm(cb.message, state)

    @r.callback_query(F.data == "crm:save")
    async def save(cb: CallbackQuery, state: FSMContext):
        cur = await state.get_state()
        if cur is None or cur == Lead.saving.state:
            await cb.answer(T.ALREADY_SAVED, show_alert=True)
            return
        if cur != Lead.confirm.state:
            await cb.answer(T.STALE)
            return
        d = await state.get_data()
        await state.set_state(Lead.saving)  # a second tap sees this and does not POST
        await cb.answer()
        await _drop_kb(cb)
        payload = {
            "name": d.get("name") or "",
            "phone": d.get("phone") or "",
            "source": d.get("source") or "",
            "note": d.get("note") or "",
            "remind": d.get("remind") or {"preset": "none"},
        }
        target = cb.message
        done = False
        try:
            try:
                res = await api.call("POST", "crm/leads/", actor=cb.from_user.id, json=payload)
            except api.ServiceRefusal as e:
                step = FIELD_STEP.get(e.field)
                if step:
                    await STEPS[step](target, state, api.err_text(e) + "\n\n")
                else:
                    await go_confirm(target, state, api.err_text(e) + "\n\n")
                done = True
                return
            except api.BackendError as e:
                log.warning("lead save failed for %s: %s", cb.from_user.id, e)
                await go_confirm(target, state, api.err_text(e) + "\n\n")
                done = True
                return
            await state.clear()
            done = True
            res = res or {}
            text = T.saved(res)
            if res.get("duplicate"):
                text = T.DUPLICATE + "\n\n" + text
            await target.answer(text, reply_markup=K.panel_kb(res.get("url") or ""))
        except Exception:
            log.exception("lead save crashed for %s", cb.from_user.id)
            try:
                await target.answer(api.DOWN_TEXT)
            except TelegramAPIError:
                log.warning("could not report a save crash", exc_info=True)
        finally:
            if not done:
                # an unexpected error must not leave the person stuck in Lead.saving
                await state.set_state(Lead.confirm)

    @r.callback_query(F.data.startswith("crm:"))
    async def stale(cb: CallbackQuery):
        try:
            await cb.answer(T.STALE)
        except TelegramAPIError:
            pass

    return r
