import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from src.bot.config import get_bot_token
from src.bot.handlers import setup_routers


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    token = get_bot_token()

    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if proxy_url:
        logging.info("Telegram bot using proxy: %s", proxy_url.split("@")[-1])
        session = AiohttpSession(proxy=proxy_url)
        bot = Bot(token=token, session=session)
    else:
        bot = Bot(token=token)

    dp = Dispatcher()
    dp.include_router(setup_routers())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
