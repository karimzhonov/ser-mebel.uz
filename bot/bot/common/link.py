"""`/start <payload>` from the site's «connect Telegram» link: the payload goes to the
backend (`POST link/`), which verifies the signed token and writes telegram_id."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.types import Message

from bot.backend.client import BackendDown, BackendError, NotFound, backend
from bot.common.kb import ik, url_button
from config import BASE_SITE

logger = logging.getLogger(__name__)

# u<pk>_<hmac10>; plain digits are the deprecated format (accepted for one more release)
LINK_RE = re.compile(r"^/start(?:@\w+)?\s+(u\d+_[0-9a-f]{10}|\d+)\s*$")

router = Router(name="link")

NOT_FOUND = "Профиль топилмади. Илтимос, линкни қайта олинг."


def site_kb():
    return ik([[url_button("Открыть", BASE_SITE)]]) if BASE_SITE else None


@router.message(F.chat.type == "private", F.text.regexp(LINK_RE))
async def link_account(message: Message):
    token = LINK_RE.match(message.text).group(1)
    if token.isdigit():
        logger.warning("deprecated plain-digit link payload from chat %s", message.chat.id)
    try:
        await backend.request(
            "POST", "link/", json={"token": token, "telegram_id": message.from_user.id}
        )
    except NotFound:
        return await message.reply(NOT_FOUND, reply_markup=site_kb())
    except BackendDown:
        return await message.reply(
            "⚠️ Server vaqtincha ishlamayapti. Birozdan keyin qayta urinib ko'ring."
        )
    except BackendError as e:
        logger.error("link failed: %s", e)
        return await message.reply(NOT_FOUND, reply_markup=site_kb())
    await message.reply("Сизни профилингиз телеграмга уланди", reply_markup=site_kb())
