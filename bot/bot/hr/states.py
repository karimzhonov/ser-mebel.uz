"""FSM of the davomat bot.

HR keeps its own FSM namespace (`destiny="hr"`), so an admin who is in the middle of a
finance draft (default destiny) never has it cleared or overwritten by an HR question.
The storage is the dispatcher's (Redis in prod: shared by all uvicorn workers and
restart-safe).
"""

from __future__ import annotations

from dataclasses import replace

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

HR_DESTINY = "hr"


class HolidayDays(StatesGroup):
    """After «✏️ Boshqa (yozaman)» on a holiday question: waiting for «3» or «3 20.03»."""

    days = State()


def hr_context(state: FSMContext) -> FSMContext:
    """The HR-destiny context for the same chat/user as `state` (the default-destiny one
    aiogram injects into handlers)."""
    return FSMContext(storage=state.storage, key=replace(state.key, destiny=HR_DESTINY))
