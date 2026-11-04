"""Dizayn va narx (stage 2) part of the bot: cards + reminders for the designer / pricer
(only «Muddatni o'zgartirish» and a link to the site; «Tayyor» is pressed on the site) and
the manager's cards where the client's answer is recorded.

Exports ``router`` (wired by bot/bot/__init__.py right after ``metering``, before ``crm``).
Importing the package registers the `offer.*` /notify renderers. Files are never handled
here.
"""

from __future__ import annotations

from . import notify  # noqa: F401  (registers offer.*)
from .router import make_router, router

__all__ = ["make_router", "router"]
