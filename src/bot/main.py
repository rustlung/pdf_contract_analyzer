import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from src.bot.config import get_bot_gateway_settings, get_bot_token
from src.bot.handlers import setup_routers
from src.bot.telegram_gateway import GatewayAiohttpSession


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    gateway_settings = get_bot_gateway_settings()
    if gateway_settings:
        # The real bot token remains in the Cloudflare Worker. The service
        # token is used only to satisfy aiogram's Bot token validation; URL
        # templates intentionally do not interpolate it.
        bot = Bot(
            token=gateway_settings.service_token,
            session=GatewayAiohttpSession(gateway_settings),
        )
        logging.info("Telegram bot using Cloudflare Telegram API Gateway")
    else:
        token = get_bot_token()
        proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        if proxy_url:
            logging.info("Telegram bot using configured proxy")
            session = AiohttpSession(proxy=proxy_url)
            bot = Bot(token=token, session=session)
        else:
            bot = Bot(token=token)

    dp = Dispatcher()
    dp.include_router(setup_routers())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
