"""Painter (Molyar) part of the bot: the full task card with «✅ Bajardim» for the painter,
the «set the deadline» card for the production heads, «Molyar tayyor» for the assembly
managers.

Exports ``router`` (wired by bot/bot/__init__.py right after ``rover``). Importing the
package registers the `painter.*` /notify renderers.
"""

from __future__ import annotations

from . import notify  # noqa: F401  (registers painter.*)
from .router import make_router, router

__all__ = ["make_router", "router"]
