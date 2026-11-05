"""The zamer Router: the measurer's buttons under the zamer cards and their typed answers.
Sits after `common.start` and before `crm`: its callbacks are `mt:` only and its text
handlers match only its own `Meter*` states, so everything else falls through."""

from __future__ import annotations

from aiogram import F, Router

from . import handlers


def make_router() -> Router:
    r = Router(name="metering")
    r.message.filter(F.chat.type == "private")
    r.include_router(handlers.build())
    return r


router = make_router()
