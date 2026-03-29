import asyncio
import logging

from aiogram import Bot, Dispatcher
from src.bot.config import get_bot_token
from src.bot.handlers import setup_routers


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    token = get_bot_token()
    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(setup_routers())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
