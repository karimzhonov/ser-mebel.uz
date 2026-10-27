"""Work-group traffic: video-note reports and the group commands (/ulash /uzish /qosh /myid).

The handler only forwards Telegram facts to `hr/group-message/` and renders the outcome
(reaction / reply under the report / DM to the employee). Whether it counts as a check-in
or a leaving report is decided by the backend (hr.services.process_group_report).
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, ReactionTypeEmoji

from .. import api
from .. import keyboards as K
from .. import messages as M
from ..fmt import esc
from ..links import connect_url

log = logging.getLogger("bot.hr.group")

group_router = Router(name="hr_group")
GROUP_CHATS = F.chat.type.in_({"group", "supergroup"})
group_router.message.filter(GROUP_CHATS)
group_router.my_chat_member.filter(GROUP_CHATS)
group_router.chat_member.filter(GROUP_CHATS)


def parse_cmd(text: str) -> tuple[str, list[str]]:
    parts = str(text).strip().split()
    return parts[0][1:].split("@")[0].lower(), parts[1:]


# ------------------------------------------------------------------ commands
@group_router.message(F.text.startswith("/"))
@api.guarded
async def on_group_command(message: Message):
    user = message.from_user
    if user is None:
        return
    cmd, _ = parse_cmd(message.text)
    chat = message.chat
    if cmd == "myid":
        await api.answer(
            message, f"Chat ID: <code>{chat.id}</code>\nSizning ID: <code>{user.id}</code>"
        )
        return
    if cmd == "ulash":
        await _connect(message)
    elif cmd == "uzish":
        await _disconnect(message)
    elif cmd == "qosh":
        await _add_employee(message)
    # any other command in a work group is nobody's business here


async def _connect(message: Message) -> None:
    chat, uid = message.chat, message.from_user.id
    title = chat.title or str(chat.id)
    try:
        await api.call(
            "POST", "hr/groups/", actor=uid, json={"chat_id": chat.id, "title": title}
        )
    except api.Forbidden:
        return  # not a manager: stay silent like before
    warn = await _bot_admin_warning(chat.id)
    await api.send_dm(uid, f'✅ "{esc(chat.title)}" guruhi kuzatuvga olindi.{warn}', report=True)
    await api.send(chat.id, M.GROUP_CONNECTED, K.connect_kb(await connect_url()))


async def _bot_admin_warning(chat_id: int) -> str:
    """The bot must be a group admin to see every message (unless privacy mode is off)."""
    bot = api.get_bot()
    try:
        me = await bot.me()
        if getattr(me, "can_read_all_group_messages", False):
            return ""
        cm = await bot.get_chat_member(chat_id, me.id)
        return "" if cm.status == "administrator" else M.NOT_ADMIN_WARN
    except TelegramAPIError:
        log.info("bot admin check failed for %s", chat_id, exc_info=True)
        return M.NOT_ADMIN_WARN


async def _disconnect(message: Message) -> None:
    chat, uid = message.chat, message.from_user.id
    try:
        await api.call("DELETE", f"hr/groups/{chat.id}/", actor=uid)
    except api.Forbidden:
        return
    await api.send_dm(uid, f'"{esc(chat.title)}" guruhi kuzatuvdan chiqarildi.', report=True)


async def _add_employee(message: Message) -> None:
    uid = message.from_user.id
    r = message.reply_to_message
    if not r or not r.from_user or r.from_user.is_bot:
        return
    try:
        e = await api.call(
            "POST",
            "hr/employees/",
            actor=uid,
            json={"user": api.user_dict(r.from_user), "chat_id": message.chat.id},
        )
    except api.Forbidden:
        return
    await api.send_dm(
        uid, f"✅ {esc(e['name'])} ro'yxatga qo'shildi (#{e['number']}).", report=True
    )


# ------------------------------------------------------------------ service messages
@group_router.message(F.new_chat_members)
@api.guarded_quiet
async def on_new_members(message: Message):
    users = [api.user_dict(u) for u in message.new_chat_members if not u.is_bot]
    if not users:
        return
    res = await api.call(
        "POST",
        "hr/members/joined/",
        actor=message.from_user.id if message.from_user else None,
        json={"chat": _chat_dict(message), "users": users},
    )
    url = await connect_url()
    for w in (res or {}).get("welcome") or []:
        await api.send(message.chat.id, M.welcome_member(w["name"]), K.connect_kb(url))


@group_router.message(F.left_chat_member)
@api.guarded_quiet
async def on_left_member(message: Message):
    u = message.left_chat_member
    if u.is_bot:
        return
    await api.call(
        "POST",
        "hr/members/left/",
        actor=message.from_user.id if message.from_user else None,
        json={"chat": _chat_dict(message), "user": api.user_dict(u)},
    )


# ------------------------------------------------------------------ the reports themselves
def _chat_dict(message: Message) -> dict:
    c = message.chat
    return {"id": c.id, "title": c.title or "", "username": c.username or "", "type": c.type}


def group_payload(message: Message) -> dict:
    return {
        "chat": _chat_dict(message),
        "message_id": message.message_id,
        "date": int(message.date.timestamp()),
        "from": api.user_dict(message.from_user),
        "forwarded": bool(
            getattr(message, "forward_origin", None) or getattr(message, "forward_date", None)
        ),
        "media": {
            "video_note": bool(message.video_note),
            "photo": bool(message.photo),
            "video": bool(message.video),
            "location": bool(message.location),
            "venue": bool(message.venue),
        },
        "text": message.text or message.caption or "",
    }


def _worth_forwarding(message: Message) -> bool:
    """Service messages (pins, title changes, ...) carry nothing a report could be."""
    return bool(
        message.text
        or message.caption
        or message.photo
        or message.video
        or message.video_note
        or message.location
        or message.venue
    )


@group_router.message()
@api.guarded_quiet
async def on_group_message(message: Message):
    user = message.from_user
    if user is None or user.is_bot or not _worth_forwarding(message):
        return
    res = await api.call("POST", "hr/group-message/", actor=user.id, json=group_payload(message))
    if not res or res.get("action") == "ignored":
        return
    if res.get("react"):
        try:
            await message.react([ReactionTypeEmoji(emoji=res["react"])])
        except TelegramAPIError:
            log.info("reaction failed in %s", message.chat.id, exc_info=True)
    if res.get("reply"):
        try:
            await message.reply(M.group_reply(res["reply"]))
        except TelegramAPIError:
            log.info("reply failed in %s", message.chat.id, exc_info=True)
    dm = res.get("dm")
    if dm:
        text, kb = M.group_dm(dm)
        await api.send_dm(dm["employee"]["telegram_id"], text, kb, report=True, actor=user.id)
