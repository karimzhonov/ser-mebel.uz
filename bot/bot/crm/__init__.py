"""CRM (call-center leads) part of the bot: «Yangi mijoz» form, `crm.task_due` reminders.

Exports ``router`` (wired by bot/bot/__init__.py after ``common.start``). Importing the
package registers the `crm.*` /notify renderers and the «🆕 Yangi mijoz» menu button text.
"""

from __future__ import annotations

from bot.hr.texts import register_menu_buttons

from . import notify  # noqa: F401  (registers crm.task_due)
from .router import make_router, router
from .texts import NEW_BTN

register_menu_buttons(NEW_BTN)

__all__ = ["make_router", "router"]
