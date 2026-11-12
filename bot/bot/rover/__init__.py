"""Rover part of the bot: the card «Rover ishini tekshiring» for the users with the
«Rover tekshiruvchi» role and the button that confirms the job.

Exports ``router`` (wired by bot/bot/__init__.py right after ``offer``). Importing the
package registers the `rover.*` /notify renderers.
"""

from __future__ import annotations

from . import notify  # noqa: F401  (registers rover.*)
from .router import make_router, router

__all__ = ["make_router", "router"]
