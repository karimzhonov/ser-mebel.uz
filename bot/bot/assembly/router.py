"""The assembly Router: the assembler's «✅ O'rnatildi» flow, the head's deadline presets and
team pick (`as:` callbacks, `AssemblyFinish` states). Private chats only; sits right after
`painter`."""

from __future__ import annotations

from aiogram import F, Router

from . import handlers


def make_router() -> Router:
    r = Router(name="assembly")
    r.message.filter(F.chat.type == "private")
    r.include_router(handlers.build())
    return r


router = make_router()
