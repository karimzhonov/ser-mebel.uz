"""Plain `/start`, `/moliya` and `/start davomat`.

Plain: finance start (member) -> HR employee_start (employee) -> finance join screen
(stranger). A blocked non-employee gets no reply. `/start davomat` goes to HR.
"""

from __future__ import annotations

import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.common.actor import Actor
from bot.finance import finance_start
from bot.hr import employee_start

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
        return
    if actor.pending:
        await finance_start(message, state, actor, bot)
        return
    if actor.employee and await employee_start(message, actor, False):
        return
    if actor.blocked:
        return  # silence
    if actor.member is None:
        await finance_start(message, state, actor, bot)
