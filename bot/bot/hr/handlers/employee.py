"""Employee side of the davomat bot in private chat: /holatim /ballarim /ballar /kelolmayman,
the HR part of /start, and the answers the bot is waiting for (lateness comment, reason
for absence, arrival time)."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.common import fmt as common_fmt

from .. import api
from .. import keyboards as K
from .. import messages as M
from ..fmt import ism
from ..texts import EMP_CMDS, PTS_HELP

log = logging.getLogger("bot.hr.employee")

private_router = Router(name="hr_private")
PRIVATE = F.chat.type == "private"
private_router.message.filter(PRIVATE)


def today_iso() -> str:
    return common_fmt.today().isoformat()


# ------------------------------------------------------------------ /start
async def employee_start(message: Message, actor: dict | None, via_link: bool) -> bool:
    """The HR half of /start (called by common/start.py).

    `via_link`: the person came through «🤖 Botga ulanish» (`/start davomat`): always
    answer. Plain /start: answer only if this is an employee, otherwise return False so the
    finance «Ro'yxatdan o'tish» screen can have it. True = handled."""
    user = message.from_user
    try:
        actor = await api.ensure_actor(actor, user)
        group_chat_id = None
        if not api.employee_of(actor):
            group_chat_id = await _find_work_group(user.id)
        res = await api.call(
            "POST",
            "hr/start/",
            actor=user.id,
            json={"user": api.user_dict(user), "group_chat_id": group_chat_id},
        )
    except api.BackendError as e:
        log.warning("hr/start failed for %s: %s", user.id, e)
        await message.answer(api.err_text(e))
        return True
    e = (res or {}).get("employee")
    if not e:
        if not via_link:
            return False
        await api.answer(message, M.NOT_FOUND_IN_GROUPS)
        return True
    await api.answer(message, M.start_text(e))
    return True


async def _find_work_group(uid: int) -> int | None:
    """A newcomer is created only if they are really in one of the watched groups."""
    groups = await api.call("GET", "hr/groups/", actor=uid) or []
    bot = api.get_bot()
    for g in groups:
        if g.get("is_active") is False:
            continue
        try:
            mem = await bot.get_chat_member(g["chat_id"], uid)
        except TelegramAPIError:
            continue
        st = str(getattr(mem.status, "value", mem.status))
        if st in ("member", "administrator", "creator", "restricted"):
            return g["chat_id"]
    return None


# ------------------------------------------------------------------ commands
@private_router.message(Command(*EMP_CMDS))
@api.guarded
async def on_employee_command(message: Message, command: CommandObject, actor=None):
    uid = message.from_user.id
    cmd = command.command.lower()
    if cmd in ("holatim", "ballarim"):
        try:
            res = await api.call("GET", "hr/me/status/", actor=uid)
        except api.NotFound:
            await message.answer(M.NOT_AN_EMPLOYEE)
            return
        await api.answer(message, M.status_text(res))
    elif cmd == "ballar":
        await api.answer(message, PTS_HELP)
    elif cmd == "kelolmayman":
        res = await api.call("POST", "hr/cant-come/", actor=uid)
        result = res.get("result")
        if result == "not_employee":
            await message.answer(M.NOT_IN_ATTENDANCE_LIST)
        elif result == "already_in":
            await message.answer(M.ALREADY_IN)
        else:
            name = ism((res.get("employee") or {}).get("name"))
            await api.answer(
                message,
                f"Tushunarli, {name}. Iltimos, sababini tanlang yoki yozib yuboring:",
                K.reason_kb(res.get("day") or today_iso()),
            )
