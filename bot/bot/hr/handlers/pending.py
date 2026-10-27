"""The answers the davomat bot is waiting for: plain private text after «Sababini yozing»,
«Necha daqiqada kelasiz?» ... Registered LAST in the private router (see hr/__init__.py)
so commands, menu buttons and the holiday FSM get their turn first."""

from __future__ import annotations

from aiogram import F
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .. import api
from .. import messages as M
from ..texts import FINANCE_MENU_BUTTONS
from .employee import private_router, today_iso


class PendingAnswer(BaseFilter):
    """Plain private text that may answer an HR question. Only when no finance flow is open
    (default-destiny FSM state is None), the text is not a finance menu button, and the
    sender is an HR employee."""

    async def __call__(self, message: Message, state: FSMContext, actor=None):
        text = (message.text or "").strip()
        if not text or text.startswith("/") or text in FINANCE_MENU_BUTTONS:
            return False
        if not api.employee_of(actor):
            return False
        return await state.get_state() is None


@private_router.message(F.text, PendingAnswer())
@api.guarded
async def on_pending_answer(message: Message, actor=None):
    uid = message.from_user.id
    res = await api.call(
        "POST", "hr/private-text/", actor=uid, json={"text": (message.text or "").strip()}
    )
    if not res or not res.get("handled"):
        raise SkipHandler  # not for HR: the finance router may want it
    name = (api.employee_of(actor) or {}).get("name")
    for text, kb in M.private_text_reply(
        res.get("outcome") or "", res.get("data") or {}, name, today_iso()
    ):
        await api.answer(message, text, kb)
