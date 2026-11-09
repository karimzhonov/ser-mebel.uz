"""Plain `/start`, `/moliya` and `/start davomat`.

Plain: finance start (member) -> HR employee_start (employee) -> CRM hint (call-center) ->
warehouse start (a keeper who is nothing else) -> finance join screen (stranger). A blocked
non-employee gets no reply. A keeper who is also a member / employee / call-center person
gets only an inline «📦 Ombor» hint (their reply keyboard is not replaced). `/start davomat`
goes to HR.
"""

from __future__ import annotations

import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.common.actor import Actor
from bot.crm import keyboards as crm_kb
from bot.crm import texts as crm_texts
from bot.finance import finance_start
from bot.hr import employee_start
from bot.warehouse import keyboards as wh_kb
from bot.warehouse import warehouse_start

router = Router(name="start")
router.message.filter(F.chat.type == "private")

PLAIN = re.compile(r"^/(start|moliya)(@\w+)?\s*$", re.I)
DAVOMAT = re.compile(r"^/start(@\w+)?\s+davomat\s*$", re.I)


@router.message(F.text.regexp(DAVOMAT))
async def start_davomat(message: Message, actor: Actor):
    await employee_start(message, actor, True)


@router.message(F.text.regexp(PLAIN))
async def start_plain(message: Message, state: FSMContext, actor: Actor, bot: Bot):
    if actor.active and await finance_start(message, state, actor, bot):
        if actor.can_add_lead:
            await message.answer(crm_texts.FIN_HINT)
        await _ombor_hint(message, actor)
        return
    if actor.pending:
        await finance_start(message, state, actor, bot)
        return
    if actor.employee and await employee_start(message, actor, False):
        await _ombor_hint(message, actor)
        return
    if actor.blocked:
        return  # silence
    if actor.member is None and actor.can_add_lead:
        # a call-center person with no other role: the lead form instead of the join screen
        await message.answer(crm_texts.START_HINT, reply_markup=crm_kb.menu_kb())
        await _ombor_hint(message, actor)
        return
    if actor.is_keeper:
        # a keeper who is nothing else: reply button + inline menu
        await warehouse_start(message, actor)
        return
    if actor.member is None:
        await finance_start(message, state, actor, bot)


async def _ombor_hint(message: Message, actor: Actor) -> None:
    """An inline «open the warehouse» hint that leaves the other reply keyboards alone."""
    if actor.is_keeper:
        await message.answer("📦 Ombor: /ombor", reply_markup=wh_kb.open_kb())
