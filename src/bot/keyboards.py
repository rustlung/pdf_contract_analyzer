from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


RECOGNIZE_MODE = "📄 Распознать документ (PDF → DOCX)"
ANALYZE_MODE = "Анализ договора"
COMPARE_MODE = "Сравнение договоров"
YES_OPTION = "Да"
NO_OPTION = "Нет"
DESTINATION_CHAT = "В чат"
DESTINATION_DRIVE = "В Google Drive"
CANCEL_OPTION = "Отмена"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=RECOGNIZE_MODE)],
            [KeyboardButton(text=ANALYZE_MODE)],
            [KeyboardButton(text=COMPARE_MODE)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите режим работы",
    )


def yes_no_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=YES_OPTION), KeyboardButton(text=NO_OPTION)]],
        resize_keyboard=True,
    )


def destination_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=DESTINATION_CHAT)],
            [KeyboardButton(text=DESTINATION_DRIVE)],
        ],
        resize_keyboard=True,
    )


def file_wait_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_OPTION)]],
        resize_keyboard=True,
    )


def drive_connect_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Подключить Google Drive", url=url)]]
    )
