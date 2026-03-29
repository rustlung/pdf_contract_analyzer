from aiogram import Router

from src.bot.handlers.menu import router as menu_router
from src.bot.handlers.modes import router as modes_router


def setup_routers() -> Router:
    root_router = Router()
    root_router.include_router(menu_router)
    root_router.include_router(modes_router)
    return root_router
