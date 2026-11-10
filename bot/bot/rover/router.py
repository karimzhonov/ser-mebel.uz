"""The rover Router: the checker's buttons under the rover card (`rv:` callbacks only, no
FSM). Private chats only; sits right after `offer`."""

from __future__ import annotations

from aiogram import F, Router

from . import handlers


def make_router() -> Router:
    r = Router(name="rover")
    r.message.filter(F.chat.type == "private")
    r.include_router(handlers.build())
    return r


router = make_router()
