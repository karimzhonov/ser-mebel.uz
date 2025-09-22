import asyncio
from db.utils import init_tortoise
from bot import dp, bot

async def main():
    await init_tortoise()
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())