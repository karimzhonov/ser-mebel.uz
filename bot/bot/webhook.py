from aiogram.types import Update

from config import WEBHOOK_URL

from . import bot, dp


async def set_webhook():
    info = await bot.get_webhook_info()
    wanted = dp.resolve_used_update_types()
    # Re-register when the update types change too: the finance router added
    # callback_query, and an old webhook limited to "message" would never get button presses.
    if info.url == WEBHOOK_URL and set(info.allowed_updates or []) == set(wanted):
        return
    await bot.set_webhook(
        WEBHOOK_URL,
        allowed_updates=wanted,
        drop_pending_updates=info.url != WEBHOOK_URL,
    )
    print(f"Webhook установлен: {WEBHOOK_URL}")


async def delete_webhook():
    await bot.delete_webhook()
    print("Webhook удалён")


async def feed_update(data):
    update = Update(**data)
    await dp.feed_update(bot, update)
