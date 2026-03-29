from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.bot.keyboards import main_menu_keyboard
from src.bot.states import BotFlow

router = Router()

WELCOME_TEXT = (
    "Привет! Это DocuMind.\n\n"
    "Выберите режим работы:\n"
    "- распознать документ (PDF -> DOCX)\n"
    "- анализ договора\n"
    "- сравнение договоров"
)


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BotFlow.choosing_mode)
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())
