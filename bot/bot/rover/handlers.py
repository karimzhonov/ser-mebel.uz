"""Buttons under the rover card: «✅ Bajarildi» asks to confirm, «✅ Ha, tasdiqlayman» posts
`rovers/{id}/confirm/`. The backend decides (403 not linked / no role, 409 already
confirmed, 400 not submitted, 404); we show it as an alert."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from . import api
from . import keyboards as K
from . import texts as T

log = logging.getLogger("bot.rover.handlers")

RV_RE = re.compile(r"^rv:(ok|oky|bk):(\d+)$")


def _url(cb: CallbackQuery) -> str:
    """The site link of the message's own keyboard, so intermediate screens keep it."""
    m = cb.message
    if isinstance(m, Message) and m.reply_markup:
        for row in m.reply_markup.inline_keyboard:
            for btn in row:
                if btn.url and btn.text == K.OPEN_PANEL:
                    return btn.url
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


def build() -> Router:
    r = Router(name="rover_buttons")

    @r.callback_query(F.data.regexp(RV_RE))
    async def press(cb: CallbackQuery):
        action, rid = RV_RE.match(cb.data).groups()
        rid_i = int(rid)
        url = _url(cb)
        if action == "ok":
            await _set_kb(cb, K.confirm_kb(rid_i, url))
            await cb.answer(T.CONFIRM_ASK)
            return
        if action == "bk":
            await _set_kb(cb, K.card_kb(rid_i, "checking", url))
            await cb.answer()
            return
        try:
            res = await api.call("POST", f"rovers/{rid_i}/confirm/", actor=cb.from_user.id, json={})
        except api.Conflict as e:
            await _set_kb(cb, K.card_kb(rid_i, "done", url))  # already confirmed: no action
            await _alert(cb, e)
            return
        except api.NotFound as e:
            await _set_kb(cb, K.card_kb(rid_i, "done", url))  # rover is gone: link only
            await _alert(cb, e)
            return
        except api.BackendError as e:
            await _set_kb(cb, K.card_kb(rid_i, "checking", url))  # retry possible: normal card
            await _alert(cb, e)
            return
        except Exception:  # noqa: BLE001
            log.exception("rover confirm %s failed", rid_i)
            await _set_kb(cb, K.card_kb(rid_i, "checking", url))
            await cb.answer(api.DOWN_TEXT, show_alert=True)
            return
        task = (res or {}).get("rover") or {}
        m = cb.message
        if task and isinstance(m, Message):
            try:
                await m.edit_text(
                    T.card(task), reply_markup=K.card_kb(rid_i, "done", task.get("url") or url)
                )
            except TelegramBadRequest as e:
                if "not modified" not in str(e).lower():
                    log.info("edit card failed: %s", e)
            except TelegramAPIError:
                log.info("edit card failed", exc_info=True)
        else:
            await _set_kb(cb, K.card_kb(rid_i, "done", url))
        await cb.answer(T.DONE_OK)

    return r
