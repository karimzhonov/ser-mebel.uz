"""The painter Router: the painter's «✅ Bajardim» flow and the head's deadline presets
(`pn:` callbacks, `PainterDone` states). Private chats only; sits right after `rover`."""

from __future__ import annotations

from aiogram import F, Router

from . import handlers


def make_router() -> Router:
    r = Router(name="painter")
    r.message.filter(F.chat.type == "private")
    r.include_router(handlers.build())
    return r


router = make_router()
