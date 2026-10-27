import asyncio
import logging

from bot import bot, dp
from bot.backend.client import backend


async def main():
    logging.basicConfig(level=logging.INFO)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
