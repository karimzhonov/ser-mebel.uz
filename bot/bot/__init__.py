import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import AiogramError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import BASE_SITE, BOT_TOKEN
from db.models.oauth import User

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


def build_keyboard(url: str = ""):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть", url="".join([BASE_SITE, url]))]]
    )


@dp.message()
async def handle_any_message(message: Message):
    args = message.text.split()

    if len(args) > 1 and args[0] == "/start":
        user_id = args[1]
        try:
            user = await User.get_or_none(id=int(user_id))
        except (ValueError, TypeError):
            user = None

        if user is None:
            logger.warning("Invalid /start payload from chat %s: %r", message.chat.id, user_id)
            return await message.reply(
                text="Профиль топилмади. Илтимос, линкни қайта олинг.",
                reply_markup=build_keyboard(),
            )

        user.telegram_id = message.from_user.id
        await user.save()

        return await message.reply(
            text="Сизни профилингиз телеграмга уланди", reply_markup=build_keyboard()
        )

    await message.answer(
        text="Бу админ панел ser-mebel.uz сайти учун", reply_markup=build_keyboard()
    )


async def send_message(chat_id: int | str, text: str, url: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=build_keyboard(url))
        return {"status": "ok"}
    except AiogramError as e:
        logger.error("Ошибка при отправке сообщения: %s", e)
        raise ConnectionError(f"{e}")
