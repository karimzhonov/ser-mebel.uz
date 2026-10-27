import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import AiogramError
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import BASE_SITE, BOT_TOKEN

logger = logging.getLogger(__name__)

STATE_TTL = 6 * 3600

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dispatcher() -> Dispatcher:
    from bot.common.middlewares import ActorMiddleware, DedupMiddleware, UserLockMiddleware
    from bot.common.rds import get_redis

    storage = RedisStorage(
        get_redis(),
        key_builder=DefaultKeyBuilder(with_bot_id=True, with_destiny=True),
        state_ttl=STATE_TTL,
        data_ttl=STATE_TTL,
    )
    d = Dispatcher(storage=storage)
    d.update.outer_middleware(DedupMiddleware())
    d.update.outer_middleware(UserLockMiddleware())
    actor = ActorMiddleware()
    d.message.outer_middleware(actor)
    d.callback_query.outer_middleware(actor)

    from bot import hr
    from bot.common import link, start
    from bot.finance import router as finance_router

    # Order matters: HR groups, site link, /start, HR private, then finance (the rest).
    d.include_router(hr.group_router)
    d.include_router(link.router)
    d.include_router(start.router)
    d.include_router(hr.private_router)
    d.include_router(finance_router)
    return d


dp = build_dispatcher()


def build_keyboard(url: str = ""):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть", url="".join([BASE_SITE, url]))]]
    )


async def send_message(chat_id: int | str, text: str, url: str):
    """Legacy route used by Django's oauth.User.send_message()."""
    try:
        # Django sends plain text: no HTML parsing
        await bot.send_message(
            chat_id=chat_id, text=text, reply_markup=build_keyboard(url), parse_mode=None
        )
        return {"status": "ok"}
    except AiogramError as e:
        logger.error("Ошибка при отправке сообщения: %s", e)
        raise ConnectionError(f"{e}")
