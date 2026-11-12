"""Buttons under the painter cards.

Painter: «✅ Bajardim» (`pn:dn`) opens the FSM `PainterDone:note -> confirm` (30 min TTL),
«✅ Yuborish» posts `painters/{id}/done/ {note}`.
Production head: `pn:dd:{days}:{id}` posts `painters/{id}/due/ {days}`;
`pn:ty:{type_id}:{id}` posts `painters/{id}/type/ {type_id}` (the team after the rover).
Split jobs act on a PART: `pn:pd:{part}` -> FSM (data `kind: "part"`; a flow without `kind` is a
job flow) -> `pn:psy:{part}` posts `painter-parts/{part}/done/ {note}`, `pn:pse` restarts;
`pn:pdd:{days}:{part}` posts `painter-parts/{part}/due/ {days}`.
The backend decides (403 not linked / not the painter, 409 already done, 400 field, 404); we
show it as an alert / re-ask."""

from __future__ import annotations

import logging
import re
import time

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.common.due import NOTE_MAX, note_ok
from bot.crm.handlers.lead import CMD_CANCEL
from bot.crm.texts import NEW_BTN
from bot.hr.texts import FINANCE_MENU_BUTTONS

from . import api, messages
from . import keyboards as K
from . import texts as T
from .states import PainterDone

log = logging.getLogger("bot.painter.handlers")

TTL = 1800  # seconds a «Bajardim» flow stays valid
DN_RE = re.compile(r"^pn:dn:(\d+)$")
SY_RE = re.compile(r"^pn:sy:(\d+)$")
SE_RE = re.compile(r"^pn:se:(\d+)$")
DD_RE = re.compile(r"^pn:dd:(\d+):(\d+)$")
TY_RE = re.compile(r"^pn:ty:(\d+):(\d+)$")
PD_RE = re.compile(r"^pn:pd:(\d+)$")
PSY_RE = re.compile(r"^pn:psy:(\d+)$")
PSE_RE = re.compile(r"^pn:pse:(\d+)$")
PDD_RE = re.compile(r"^pn:pdd:(\d+):(\d+)$")


def _kind(d: dict) -> str:
    return "part" if d.get("kind") == "part" else "job"  # missing = a flow opened before deploy


def _url(cb: CallbackQuery) -> str:
    """The site link of the message's own keyboard, so intermediate screens keep it."""
    m = cb.message
    if isinstance(m, Message) and m.reply_markup:
        for row in m.reply_markup.inline_keyboard:
            for btn in row:
                if btn.url and btn.text == K.OPEN_PANEL:
                    return btn.url
    return ""


def _split_url(cb: CallbackQuery, url: str) -> str:
    """The «✂️ Bo'lib berish» link of the message's own keyboard; else rebuilt from the site
    link (`...?open={id}` + `&split=1`, the pattern the backend uses)."""
    m = cb.message
    if isinstance(m, Message) and m.reply_markup:
        for row in m.reply_markup.inline_keyboard:
            for btn in row:
                if btn.url and btn.text == K.SPLIT_BTN:
                    return btn.url
    if url and "?" in url and "split=" not in url:
        return url + "&split=1"
    return ""


async def _set_kb(cb: CallbackQuery, markup) -> None:
    m = cb.message
    if not isinstance(m, Message):
        return
    try:
        await m.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            log.info("edit markup failed: %s", e)
    except TelegramAPIError:
        log.info("edit markup failed", exc_info=True)


async def _alert(cb: CallbackQuery, e: api.BackendError) -> None:
    await cb.answer(api.err_text(e).removeprefix("❗ ")[:200], show_alert=True)


async def _edit_card(bot, d: dict, text: str | None, kb) -> None:
    """Edit the stored task card (chat_id / message_id of the FSM data)."""
    try:
        if text is None:
            await bot.edit_message_reply_markup(
                chat_id=d.get("chat_id"), message_id=d.get("message_id"), reply_markup=kb
            )
        else:
            await bot.edit_message_text(
                text, chat_id=d.get("chat_id"), message_id=d.get("message_id"), reply_markup=kb
            )
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            log.info("edit of the painter card failed: %s", e)
    except TelegramAPIError:
        log.info("edit of the painter card failed", exc_info=True)


def _fresh(d: dict) -> bool:
    ts = d.get("ts")
    return isinstance(ts, (int, float)) and time.time() - ts <= TTL


def build() -> Router:
    r = Router(name="painter_buttons")

    # ---- head: deadline presets
    @r.callback_query(F.data.regexp(DD_RE))
    async def set_due(cb: CallbackQuery):
        days, pid = DD_RE.match(cb.data).groups()
        pid_i = int(pid)
        url = _url(cb)
        try:
            res = await api.call(
                "POST", f"painters/{pid_i}/due/", actor=cb.from_user.id, json={"days": int(days)}
            )
        except (api.Conflict, api.NotFound) as e:
            await _set_kb(cb, K.due_kb(pid_i, (), url, "done"))  # nothing to set any more
            await _alert(cb, e)
            return
        except api.BackendError as e:
            await _alert(cb, e)
            return
        except Exception:  # noqa: BLE001
            log.exception("painter due %s failed", pid_i)
            await cb.answer(api.DOWN_TEXT, show_alert=True)
            return
        task = (res or {}).get("painter") or {}
        m = cb.message
        if task and isinstance(m, Message):
            try:
                await m.edit_text(
                    T.head_card(task),
                    reply_markup=K.due_kb(
                        pid_i, K.PRESETS, task.get("url") or url, task.get("state") or "new"
                    ),
                )
            except TelegramBadRequest as e:
                if "not modified" not in str(e).lower():
                    log.info("edit card failed: %s", e)
            except TelegramAPIError:
                log.info("edit card failed", exc_info=True)
        await cb.answer(T.DUE_SAVED)

    # ---- head: deadline presets of one part (split job)
    @r.callback_query(F.data.regexp(PDD_RE))
    async def set_part_due(cb: CallbackQuery):
        days, part = PDD_RE.match(cb.data).groups()
        part_i = int(part)
        url = _url(cb)
        try:
            res = await api.call(
                "POST",
                f"painter-parts/{part_i}/due/",
                actor=cb.from_user.id,
                json={"days": int(days)},
            )
        except (api.Conflict, api.NotFound) as e:
            await _set_kb(cb, K.part_due_kb(part_i, (), url, "done"))
            await _alert(cb, e)
            return
        except api.BackendError as e:
            await _alert(cb, e)
            return
        except Exception:  # noqa: BLE001
            log.exception("painter part due %s failed", part_i)
            await cb.answer(api.DOWN_TEXT, show_alert=True)
            return
        p = (res or {}).get("part") or {}
        m = cb.message
        if p and isinstance(m, Message):
            try:
                await m.edit_text(
                    T.part_head_card(p),
                    reply_markup=K.part_due_kb(
                        part_i, K.PRESETS, p.get("url") or url, p.get("state") or "new"
                    ),
                )
            except TelegramBadRequest as e:
                if "not modified" not in str(e).lower():
                    log.info("edit card failed: %s", e)
            except TelegramAPIError:
                log.info("edit card failed", exc_info=True)
        await cb.answer(T.DUE_SAVED)

    # ---- head: pick the team after the rover
    @r.callback_query(F.data.regexp(TY_RE))
    async def pick_team(cb: CallbackQuery):
        type_id, pid = TY_RE.match(cb.data).groups()
        pid_i = int(pid)
        url = _url(cb)
        try:
            res = await api.call(
                "POST",
                f"painters/{pid_i}/type/",
                actor=cb.from_user.id,
                json={"type_id": int(type_id)},
            )
        except api.Conflict as e:
            # nothing to pick any more: keep the site link and the split link
            await _set_kb(cb, K.split_kb(_split_url(cb, url), url))
            await _alert(cb, e)
            return
        except api.BackendError as e:
            await _alert(cb, e)
            return
        except Exception:  # noqa: BLE001
            log.exception("painter team %s failed", pid_i)
            await cb.answer(api.DOWN_TEXT, show_alert=True)
            return
        task = dict((res or {}).get("painter") or {})
        task.setdefault("id", pid_i)
        link = (
            K.split_kb(task.get("split_url") or "", task.get("url") or url)
            if T.remainder_of(task)
            else K.link_kb(task.get("url") or url)
        )
        text = T.team_chosen(task)
        m = cb.message
        here = None
        if isinstance(m, Message):
            here = (m.chat.id, m.message_id)
            try:
                await m.edit_text(text, reply_markup=link)
            except TelegramBadRequest as e:
                if "not modified" not in str(e).lower():
                    log.info("edit card failed: %s", e)
            except TelegramAPIError:
                log.info("edit card failed", exc_info=True)
        for e in await messages.take_all(messages.rkey(pid_i)):
            if here and (e.get("chat_id"), e.get("message_id")) == here:
                continue
            await _edit_card(cb.bot, e, text, link)
        await cb.answer(T.TEAM_OK)

    # ---- painter: «Bajardim» -> note -> confirm (job: pn:dn / part: pn:pd)
    async def _start(cb: CallbackQuery, state: FSMContext, ident: int, kind: str):
        cur = await state.get_state()
        if cur is not None and not cur.startswith("PainterDone"):
            await cb.answer(T.BUSY, show_alert=True)
            return
        m = cb.message
        if not isinstance(m, Message):
            await cb.answer(T.STALE)
            return
        await state.set_state(PainterDone.note)
        await state.set_data(
            {
                "pid": ident,
                "kind": kind,
                "chat_id": m.chat.id,
                "message_id": m.message_id,
                "url": _url(cb),
                "ts": time.time(),
            }
        )
        await cb.answer()
        await m.answer(T.ASK_NOTE, reply_markup=K.cancel_kb())

    @r.callback_query(F.data.regexp(DN_RE))
    async def start_done(cb: CallbackQuery, state: FSMContext):
        await _start(cb, state, int(DN_RE.match(cb.data).group(1)), "job")

    @r.callback_query(F.data.regexp(PD_RE))
    async def start_part_done(cb: CallbackQuery, state: FSMContext):
        await _start(cb, state, int(PD_RE.match(cb.data).group(1)), "part")

    async def _restart(cb: CallbackQuery, state: FSMContext, ident: int, kind: str):
        d = await state.get_data()
        cur = await state.get_state()
        if not (
            cur
            and cur.startswith("PainterDone")
            and d.get("pid") == ident
            and _kind(d) == kind
            and _fresh(d)
        ):
            if cur and cur.startswith("PainterDone"):
                await state.clear()
            await _set_kb(cb, None)
            await cb.answer(T.STALE, show_alert=True)
            return
        await state.update_data(ts=time.time(), note=None)
        await state.set_state(PainterDone.note)
        await _set_kb(cb, None)
        await cb.answer()
        m = cb.message
        if isinstance(m, Message):
            await m.answer(T.ASK_NOTE, reply_markup=K.cancel_kb())

    @r.callback_query(F.data.regexp(SE_RE))
    async def restart(cb: CallbackQuery, state: FSMContext):
        await _restart(cb, state, int(SE_RE.match(cb.data).group(1)), "job")

    @r.callback_query(F.data.regexp(PSE_RE))
    async def restart_part(cb: CallbackQuery, state: FSMContext):
        await _restart(cb, state, int(PSE_RE.match(cb.data).group(1)), "part")

    @r.callback_query(F.data == "pn:q")
    async def cancel_typed(cb: CallbackQuery, state: FSMContext):
        cur = await state.get_state()
        if cur and cur.startswith("PainterDone"):
            await state.clear()
        await cb.answer(T.CANCELLED)
        await _set_kb(cb, None)

    async def _submit(cb: CallbackQuery, state: FSMContext, ident: int, kind: str):
        d = await state.get_data()
        cur = await state.get_state()
        if (
            cur != PainterDone.confirm.state
            or d.get("pid") != ident
            or _kind(d) != kind
            or not _fresh(d)
            or not d.get("note")
        ):
            if cur and cur.startswith("PainterDone"):
                await state.clear()
            await _set_kb(cb, None)
            await cb.answer(T.STALE, show_alert=True)
            return
        url = d.get("url") or ""
        path = f"painter-parts/{ident}/done/" if kind == "part" else f"painters/{ident}/done/"
        try:
            res = await api.call("POST", path, actor=cb.from_user.id, json={"note": d["note"]})
        except api.ServiceRefusal as e:
            if e.field == "note":
                await state.set_state(PainterDone.note)
                await state.update_data(ts=time.time())
                await _set_kb(cb, None)
                await cb.answer()
                m = cb.message
                if isinstance(m, Message):
                    await m.answer(
                        api.err_text(e) + "\n\n" + T.ASK_NOTE, reply_markup=K.cancel_kb()
                    )
                return
            await state.clear()
            await _set_kb(cb, None)
            await _alert(cb, e)
            return
        except (api.Conflict, api.NotFound, api.Forbidden) as e:
            await state.clear()
            # 403: nothing to press any more (no keyboard); 409 / 404: the link only
            await _edit_card(
                cb.bot, d, None, None if isinstance(e, api.Forbidden) else K.link_kb(url)
            )
            await _set_kb(cb, None)
            await _alert(cb, e)
            return
        except api.BackendError as e:
            await state.clear()
            await _set_kb(cb, None)
            await _alert(cb, e)
            return
        except Exception:  # noqa: BLE001
            log.exception("painter %s done %s failed", kind, ident)
            await state.clear()
            await _set_kb(cb, None)
            await cb.answer(api.DOWN_TEXT, show_alert=True)
            return
        await state.clear()
        task = dict((res or {}).get("part" if kind == "part" else "painter") or {})
        task.setdefault("id", ident)
        task.setdefault("state", "done")
        if url and not task.get("url"):
            task["url"] = url
        if kind == "part":
            await _edit_card(
                cb.bot,
                d,
                T.part_task_card(task),
                K.part_task_kb(ident, "done", task.get("url") or ""),
            )
        else:
            await _edit_card(
                cb.bot, d, T.task_card(task), K.task_kb(ident, "done", task.get("url") or "")
            )
        m = cb.message
        if isinstance(m, Message):
            try:
                await m.edit_text(T.DONE_OK, reply_markup=None)
            except TelegramAPIError:
                log.info("edit of the summary failed", exc_info=True)
        await cb.answer(T.DONE_OK)

    @r.callback_query(F.data.regexp(SY_RE))
    async def submit(cb: CallbackQuery, state: FSMContext):
        await _submit(cb, state, int(SY_RE.match(cb.data).group(1)), "job")

    @r.callback_query(F.data.regexp(PSY_RE))
    async def submit_part(cb: CallbackQuery, state: FSMContext):
        await _submit(cb, state, int(PSY_RE.match(cb.data).group(1)), "part")

    # ---- typed izoh
    typed = StateFilter(PainterDone.note, PainterDone.confirm)

    @r.message(F.text.regexp(CMD_CANCEL), typed)
    async def typed_cancel(message: Message, state: FSMContext):
        await state.clear()
        await message.answer(T.CANCELLED)

    @r.message(F.text & ~F.text.startswith("/") & ~F.forward_origin, typed)
    async def typed_answer(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if text in FINANCE_MENU_BUTTONS or text == NEW_BTN:
            await state.clear()
            raise SkipHandler
        d = await state.get_data()
        if not _fresh(d):
            await state.clear()
            await message.answer(T.STALE)
            return
        cur = await state.get_state()
        if cur == PainterDone.note.state:
            if not note_ok(text):
                bad = T.LONG_NOTE if len(text) > NOTE_MAX else T.BAD_NOTE
                await message.answer(bad + "\n\n" + T.ASK_NOTE, reply_markup=K.cancel_kb())
                return
            await state.update_data(note=text, ts=time.time())
            await state.set_state(PainterDone.confirm)
            await message.answer(
                T.summary(text), reply_markup=K.summary_kb(int(d["pid"]), _kind(d))
            )
            return
        await message.answer(T.USE_BUTTONS, reply_markup=K.summary_kb(int(d["pid"]), _kind(d)))

    return r
