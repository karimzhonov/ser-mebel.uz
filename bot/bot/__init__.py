import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import AiogramError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import BASE_SITE, BOT_TOKEN
from db.models.oauth import User

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Order matters: the finance router sees private messages first and lets the ones it
# doesn't own (site linking, non-members) fall through to the site router below.
site_router = Router(name="site")


def build_keyboard(url: str = ""):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть", url="".join([BASE_SITE, url]))]]
    )


@site_router.message(F.chat.type == "private")
async def handle_any_message(message: Message):
    # photos/stickers have no text
    args = (message.text or "").split()

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


from .finance import router as finance_router  # noqa: E402

dp.include_router(finance_router)
dp.include_router(site_router)


async def send_message(chat_id: int | str, text: str, url: str):
    try:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=build_keyboard(url))
        return {"status": "ok"}
    except AiogramError as e:
        logger.error("Ошибка при отправке сообщения: %s", e)
        raise ConnectionError(f"{e}")
