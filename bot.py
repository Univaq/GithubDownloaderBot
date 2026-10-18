
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from config import settings
from handlers.start import router as start_router
from handlers.search import router as search_router
from handlers.releases import router as releases_router
from handlers.readme import router as readme_router
from handlers.menu import router as menu_router
from handlers.favorites import router as favorites_router
from repositories.jobs import initialize_database
from workers.download_worker import worker_loop


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


def create_bot() -> Bot:
    if settings.use_local_bot_api:
        local_api = TelegramAPIServer.from_base(
            settings.local_bot_api_url,
            is_local=True,
        )
        session = AiohttpSession(api=local_api)

        return Bot(
            token=settings.bot_token,
            session=session,
        )

    return Bot(token=settings.bot_token)


async def cleanup_temporary_files() -> None:
    """Remove temporary download files left by a previous run."""
    settings.downloads_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path in settings.downloads_dir.glob("ghbot_*.tmp"):
        try:
            if path.is_file() and not path.is_symlink():
                path.unlink()
        except OSError:
            logger.exception(
                "Failed to remove temporary file: %s",
                path,
            )


async def main() -> None:
    await initialize_database()
    await cleanup_temporary_files()

    bot = create_bot()
    dp = Dispatcher()
    stop_event = asyncio.Event()

    dp.include_router(start_router)
    dp.include_router(search_router)
    dp.include_router(releases_router)
    dp.include_router(readme_router)
    dp.include_router(menu_router)
    dp.include_router(favorites_router)

    worker_task = asyncio.create_task(
        worker_loop(bot, stop_event),
        name="download-worker",
    )

    try:
        bot_info = await bot.get_me()
        logger.info(
            "Bot is ready: @%s",
            bot_info.username,
        )

        await dp.start_polling(
            bot,
            drop_pending_updates=True,
        )

    finally:
        stop_event.set()

        try:
            await worker_task
        finally:
            await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
