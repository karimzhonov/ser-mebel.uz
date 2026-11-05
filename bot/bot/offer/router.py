"""The design / price Router: the assignee's «Muddatni o'zgartirish» menu and the manager's
answer buttons with their typed bodies. Sits after `metering` and before `crm`: its
callbacks are `of:` only and its text handlers match only its own `Offer*` states, so
everything else falls through."""

from __future__ import annotations

from aiogram import F, Router

from . import handlers


def make_router() -> Router:
    r = Router(name="offer")
    r.message.filter(F.chat.type == "private")
    r.include_router(handlers.build())
    return r


router = make_router()
