"""Omborchi (warehouse keeper) part of the bot: search, kirim / chiqim, new product, pictures.

Exports ``router`` (after `offer`, before `crm`) and ``fallback_router`` (after
`hr.private_router`, before `finance`), wired in bot/bot/__init__.py. No `/notify` events
here (the low-stock event is not built). All rules live in the backend.
"""

from __future__ import annotations

from bot.hr.texts import register_menu_buttons

from .handlers.menu import warehouse_start
from .router import ex_keeper_router, fallback_router, make_fallback_router, make_router, router
from .texts import MENU_BTN

register_menu_buttons(MENU_BTN)

__all__ = [
    "ex_keeper_router",
    "fallback_router",
    "make_fallback_router",
    "make_router",
    "router",
    "warehouse_start",
]
