"""Main entry point for WPP Telegram Bot."""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from auth import AdminOnlyMiddleware
from config import ADMIN_IDS, BOT_TOKEN
from handlers import all_routers
from service import WPPService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("wpp_bot")


async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Главное меню / Дашборд"),
    ]
    await bot.set_my_commands(commands)


async def live_traffic_worker():
    """Poll live traffic every 3 seconds to accurately detect active routes."""
    while True:
        try:
            # subprocess calls inside must not block the event loop (and every handler with it)
            await asyncio.to_thread(WPPService.sample_live_traffic)
        except Exception:
            logger.debug("live traffic sample failed", exc_info=True)
        await asyncio.sleep(3)


async def main():
    if not BOT_TOKEN:
        logger.error("Критическая ошибка: BOT_TOKEN не задан! Укажите его в файле .env")
        sys.exit(1)
    if not ADMIN_IDS:
        logger.error("Критическая ошибка: ADMIN_IDS не задан или некорректен! Укажите числовой Telegram ID в файле .env")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.outer_middleware(AdminOnlyMiddleware())
    dp.callback_query.outer_middleware(AdminOnlyMiddleware())

    # Register all handlers
    for router in all_routers:
        dp.include_router(router)

    await set_commands(bot)

    # Start 3-second live traffic background sampler
    sampler = asyncio.create_task(live_traffic_worker())

    logger.info("Бот успешно запущен и отслеживает трафик с интервалом 3 секунды...")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        sampler.cancel()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
