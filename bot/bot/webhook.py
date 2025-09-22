from aiogram.types import Update
from config import WEBHOOK_URL
from . import bot, dp

async def set_webhook():
    info = await bot.get_webhook_info()
    if info.url == WEBHOOK_URL:
        return
    await bot.set_webhook(
        WEBHOOK_URL,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True
    )
    print(f"Webhook установлен: {WEBHOOK_URL}")


async def delete_webhook():
    await bot.delete_webhook()
    print("Webhook удалён")


async def feed_update(data):
    update = Update(**data)
    await dp.feed_update(bot, update)