"""Assembly (Yig'ish/O'rnatish) part of the bot: the «pick the team» card for the production
heads, the full task card with «✅ O'rnatildi» for the chosen assembler, the «set the
deadline» card for the heads, «O'rnatildi» for heads and assembly managers.

Exports ``router`` (wired by bot/bot/__init__.py right after ``painter``). Importing the
package registers the `assembly.*` /notify renderers.
"""

from __future__ import annotations

from . import notify  # noqa: F401  (registers assembly.*)
from .router import make_router, router

__all__ = ["make_router", "router"]
