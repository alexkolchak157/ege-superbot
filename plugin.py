from telegram.ext import Application, CallbackQueryHandler
from telegram import Update

# ▼ ДОБАВЬТЕ ЭТУ СТРОКУ
from .quiz_handlers import entry_from_main_menu    # ← функция-entry для кнопки

from . import keyboards
from .states import QuizState
from .quiz_handlers import (
    register_quiz_handlers,
    select_mode_random,
    select_mode_topic,
    select_mode_exam_number,
)
from .common import register_test_handlers
from .mistakes_review import register_mistakes_handlers

class _TestPlugin:
    code = "test_part"
    title = "Тестовая часть"
    menu_priority = 10

    def register(self, app: Application):
        register_test_handlers(app)
        register_quiz_handlers(app)
        register_mistakes_handlers(app)

    # entry_handler отдаём прямо из quiz_handlers
    from .quiz_handlers import entry_from_main_menu
    def entry_handler(self):
        from telegram.ext import CallbackQueryHandler
        return CallbackQueryHandler(
            entry_from_main_menu,
            pattern=f"^choose_{self.code}$",
        )

plugin = _TestPlugin()
