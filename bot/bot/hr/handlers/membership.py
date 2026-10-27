"""my_chat_member (the bot added to / removed from a group) and chat_member (someone left
or was kicked). Telegram only sends these if `allowed_updates` includes them."""

from __future__ import annotations

from aiogram.types import ChatMemberUpdated

from .. import api
from .group import group_router


def _status(member) -> str:
    st = getattr(member, "status", "")
    return str(getattr(st, "value", st))


def _chat(upd: ChatMemberUpdated) -> dict:
    c = upd.chat
    return {"id": c.id, "title": c.title or "", "username": c.username or "", "type": c.type}


@group_router.my_chat_member()
@api.guarded_quiet
async def on_my_chat_member(upd: ChatMemberUpdated):
    st = _status(upd.new_chat_member)
    if st not in ("member", "administrator"):
        return
    # the backend tells the managers only when the group is not watched yet
    await api.call(
        "POST",
        "hr/bot-membership/",
        actor=upd.from_user.id if upd.from_user else None,
        json={"chat": _chat(upd), "status": st},
    )


@group_router.chat_member()
@api.guarded_quiet
async def on_chat_member(upd: ChatMemberUpdated):
    u = upd.new_chat_member.user
    if u.is_bot or _status(upd.new_chat_member) not in ("left", "kicked"):
        return
    await api.call(
        "POST",
        "hr/members/left/",
        actor=upd.from_user.id if upd.from_user else None,
        json={"chat": _chat(upd), "user": api.user_dict(u)},
    )
