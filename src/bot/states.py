from aiogram.fsm.state import State, StatesGroup


class BotFlow(StatesGroup):
    choosing_mode = State()
    waiting_single_document = State()
    waiting_recognize_save_to_drive = State()
    waiting_compare_first_document = State()
    waiting_compare_second_document = State()
    waiting_save_to_drive = State()
    waiting_return_recognized_results = State()
    waiting_return_destination = State()
