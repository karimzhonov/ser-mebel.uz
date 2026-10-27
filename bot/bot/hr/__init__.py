"""Davomat (attendance) part of the bot.

Exports (wired by bot/bot/__init__.py, router order: group_router, common link/start,
private_router, finance):

* ``group_router``   - work-group traffic: video-note reports, /ulash /uzish /qosh /myid,
  joins/leaves, my_chat_member.
* ``private_router`` - `dv:` buttons, employee and manager commands, «🕘 Davomat», the HR
  FSM (destiny="hr"), and the pending-answer handler (registered last).
* ``employee_start`` - the HR half of /start, used by common/start.py.

Importing this package also registers the `hr.*` /notify renderers (hr/notify.py).
Needs `allowed_updates` to include my_chat_member and chat_member.
"""

from __future__ import annotations

from . import notify  # noqa: F401  (registers the hr.* renderers)
from .handlers import admin, callbacks, group, membership, pending  # noqa: F401
from .handlers.employee import employee_start, private_router
from .handlers.group import group_router
from .texts import register_menu_buttons

__all__ = ["employee_start", "group_router", "private_router", "register_menu_buttons"]
