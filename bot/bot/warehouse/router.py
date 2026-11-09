"""Warehouse Routers (private chats, omborchi only).

* ``make_router()``: menu, `wh:` buttons and the `Wh*` states. Sits after `offer`, before
  `crm`/`hr.private_router`/`finance`: it only takes the «📦 Ombor» button, `/ombor`, its own
  `wh:` callbacks and typed answers of its own states, so everything else falls through.
* ``make_fallback_router()``: sits AFTER `hr.private_router` and BEFORE `finance`, so a
  keeper's answer to an HR question is never stolen. Free text -> product search and a
  stray photo -> «attach to the product?», only for a keeper who is not a finance member
  (finance takes their text / photos as operations and receipts) and has no open state.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.common.actor import Actor
from bot.common.rds import get_redis
from bot.hr.texts import FINANCE_MENU_BUTTONS

from . import keyboards as K
from . import photos as P
from . import texts as T
from .api import BackendError
from .handlers import card, menu, move, photo, product
from .handlers import util as U
from .handlers.menu import MENU_RE
from .states import ALL

log = logging.getLogger("bot.warehouse.router")


def _is_keeper(event, actor: Actor | None = None) -> bool:
    return bool(actor and actor.is_keeper)


def _plain_keeper(event, actor: Actor | None = None) -> bool:
    """A keeper who is not a finance member."""
    return bool(actor and actor.is_keeper and actor.member is None)


def make_router() -> Router:
    r = Router(name="warehouse")
    r.message.filter(F.chat.type == "private", _is_keeper)
    r.callback_query.filter(F.data.startswith("wh:"), _is_keeper)
    r.include_router(menu.build())  # first: the «another flow is open» gate + menu button
    r.include_router(card.build())
    r.include_router(move.build())
    r.include_router(product.build())
    r.include_router(photo.build())
    return r


def make_ex_keeper_router() -> Router:
    """Somebody who is no longer (or never was) a keeper but has a Wh* state / old button /
    the «📦 Ombor» text: a short refusal. Touches nothing else."""
    r = Router(name="warehouse_ex_keeper")
    r.message.filter(F.chat.type == "private", lambda m, actor=None: not _is_keeper(m, actor))
    r.callback_query.filter(
        F.data.startswith("wh:"), lambda c, actor=None: not _is_keeper(c, actor)
    )

    @r.message(F.text.regexp(MENU_RE))
    async def ex_menu(message: Message, state: FSMContext):
        await U.clear(state)  # menu button text: also drops a stale Wh* state
        await message.answer(T.NOT_KEEPER)

    @r.message(StateFilter(*ALL))
    async def ex_state(message: Message, state: FSMContext):
        await U.clear(state)
        await message.answer(T.NOT_KEEPER)

    @r.callback_query()
    async def ex_cb(cb: CallbackQuery, state: FSMContext):
        if U.is_wh_state(await state.get_state()):
            await U.clear(state)
        await cb.answer(T.NOT_KEEPER, show_alert=True)

    return r


def make_fallback_router() -> Router:
    r = Router(name="warehouse_fallback")
    r.message.filter(F.chat.type == "private", _plain_keeper, StateFilter(None))

    @r.message(F.text & ~F.text.startswith("/") & ~F.forward_origin)
    async def free_text(message: Message):
        text = (message.text or "").strip()
        if not text or text in FINANCE_MENU_BUTTONS:
            raise SkipHandler
        await menu.search(message, message.from_user.id, text[:100])

    @r.message(F.photo)
    async def stray_photo(message: Message):
        uid = message.from_user.id
        pid = await P.current(uid)
        if pid is None:
            raise SkipHandler
        name = ""
        try:
            name = (await menu.U.get_product(uid, pid))["product"]["name"]
        except BackendError as e:
            log.info("stray photo: product %s unavailable: %s", pid, e)
            raise SkipHandler
        await get_redis().set(f"wh:pend:{uid}", message.photo[-1].file_id, ex=600)
        await message.answer(T.attach_ask(name), reply_markup=K.attach_kb(pid))

    return r


router = make_router()
ex_keeper_router = make_ex_keeper_router()
fallback_router = make_fallback_router()
