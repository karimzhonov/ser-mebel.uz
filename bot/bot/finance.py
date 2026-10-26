"""Finance (Moliya) bot: forwards private messages and button presses to the backend.

The whole finance logic lives in the backend (backend/accounting/telegram/), which
answers through the Bot API with the same BOT_TOKEN. This router only forwards the raw
update to POST {BACKEND_URL}/api/v1/finance/telegram/update/, signed with
HMAC-SHA256(BOT_TOKEN, body), and lets the update fall through to the site handler
when the backend says it is not a finance update.

`/start <user_id>` (linking a site account) is never forwarded.
"""

import hashlib
import hmac
import json
import logging
import re

import aiohttp
from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import CallbackQuery, Message, Update

from config import BACKEND_URL, BOT_TOKEN

logger = logging.getLogger(__name__)

router = Router(name="finance")

SITE_LINK = re.compile(r"^/start(@\w+)?\s+\S+")
TIMEOUT = aiohttp.ClientTimeout(total=55)


def sign(body: bytes) -> str:
    return hmac.new((BOT_TOKEN or "").encode(), body, hashlib.sha256).hexdigest()


async def forward(update: Update) -> bool:
    """True when the backend handled the update. by_alias: Telegram's own field names
    ("from", not aiogram's "from_user") — the backend reads the raw Bot API shape."""
    body = json.dumps(
        update.model_dump(mode="json", exclude_none=True, by_alias=True), ensure_ascii=False
    ).encode()
    url = f"{BACKEND_URL.rstrip('/')}/api/v1/finance/telegram/update/"
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.post(
                url,
                data=body,
                headers={"Content-Type": "application/json", "X-Bot-Signature": sign(body)},
            ) as resp:
                if resp.status != 200:
                    logger.error("finance backend answered %s", resp.status)
                    return False
                data = await resp.json()
                return bool(data.get("handled"))
    except (aiohttp.ClientError, TimeoutError, ValueError) as e:
        logger.error("finance backend unreachable: %s", e)
        return False


@router.message(F.chat.type == "private")
async def finance_message(message: Message, event_update: Update):
    if message.text and SITE_LINK.match(message.text):
        raise SkipHandler()
    if not await forward(event_update):
        raise SkipHandler()


@router.callback_query()
async def finance_callback(callback: CallbackQuery, event_update: Update):
    if not await forward(event_update):
        try:
            await callback.answer()
        except Exception:  # noqa: BLE001 — an expired query is fine
            pass
