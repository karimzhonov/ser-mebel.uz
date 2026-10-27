import hashlib
import logging

from aiogram.types import Update

from config import BOT_TOKEN, WEBHOOK_URL

from . import bot, dp

logger = logging.getLogger(__name__)


def webhook_secret() -> str:
    """Telegram `secret_token` (1-256 of A-Za-z0-9_-), derived from the bot token so no new
    env var is needed. Telegram sends it back in X-Telegram-Bot-Api-Secret-Token."""
    return hashlib.sha256(("webhook:" + (BOT_TOKEN or "")).encode()).hexdigest()[:48]


async def set_webhook():
    info = await bot.get_webhook_info()
    wanted = dp.resolve_used_update_types()
    # Always (re)register: the secret token is not visible in getWebhookInfo.
    await bot.set_webhook(
        WEBHOOK_URL,
        allowed_updates=wanted,
        secret_token=webhook_secret(),
        drop_pending_updates=info.url != WEBHOOK_URL,
    )
    logger.info("Webhook set: %s", WEBHOOK_URL)


async def delete_webhook():
    await bot.delete_webhook()
    logger.info("Webhook deleted")


async def feed_update(data):
    update = Update(**data)
    await dp.feed_update(bot, update)
