from aiogram import Bot, Dispatcher
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import AiogramError
from db.models.oauth import User
from config import BOT_TOKEN, BASE_SITE

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


def build_keyboard(url: str = ''):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Открыть",
                web_app=WebAppInfo(url=''.join([BASE_SITE, url]))
            )
        ]
    ])


@dp.message()
async def handle_any_message(message: Message):
    args = message.text.split()

    if len(args) > 1 and args[0] == '/start':
        user_id = args[1]
        user = await User.get_or_none(id=user_id)
        user.telegram_id = message.from_user.id
        await user.save()

        await message.reply(
            text='Сизни профилингиз телеграмга уланди',
            reply_markup=build_keyboard()
        )
    
    await message.answer(
        text='Бу админ панел ser-mebel.uz сайти учун',
        reply_markup=build_keyboard()
    )


async def send_message(chat_id: int | str, text: str, url: str):
    try:
        await bot.send_message(
            chat_id=chat_id, text=text,
            reply_markup=build_keyboard(url)
        )
        return {'status': 'ok'}
    except AiogramError as e:
        print(f"Ошибка при отправке сообщения: {e}")
        raise ConnectionError(f"{e}")
