"""Zamer (metering) part of the bot: cards + reminders for the measurer, the buttons
«O'lchov oldim» / «Vaqtni o'zgartirish» / «Bekor bo'ldi».

Exports ``router`` (wired by bot/bot/__init__.py between ``common.start`` and ``crm``).
Importing the package registers the `metering.*` /notify renderers. Files are never
handled here: they are uploaded on the site.
"""

from __future__ import annotations

from . import notify  # noqa: F401  (registers metering.*)
from .router import make_router, router

__all__ = ["make_router", "router"]
