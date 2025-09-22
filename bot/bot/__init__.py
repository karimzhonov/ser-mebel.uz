from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import AiogramError
from db.utils import init_tortoise
from db.models.oauth import User
from config import BOT_TOKEN

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


@dp.message()
async def handle_any_message(message: Message):
    args = message.text.split()

    print(args)

    if len(args) > 1 and args[0] == '/start':
        user_id = args[1]
        user = await User.get_or_none(id=user_id)
        user.telegram_id = message.from_user.id
        await user.save()

        await message.reply(
            text='Сизни профилингиз телеграмга уланди'
        )


async def send_message(chat_id: int | str, text: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        return {'status': 'ok'}
    except AiogramError as e:
        print(f"Ошибка при отправке сообщения: {e}")
        raise ConnectionError(f"{e}")
