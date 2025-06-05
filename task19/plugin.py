from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from core.plugin_base import BotPlugin
from core import states
from . import handlers

class Task19Plugin(BotPlugin):
    code = "task19"
    title = "Задание 19 (Примеры)"
    menu_priority = 15
    
    async def post_init(self, app):
        """Инициализация данных для задания 19."""
        await handlers.init_task19_data()
    
    def register(self, app):
        """Регистрация обработчиков."""
        
        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    handlers.entry_from_menu,
                    pattern=f"^choose_{self.code}$"
                ),
                CommandHandler("task19", handlers.cmd_task19),
            ],
            states={
                states.CHOOSING_MODE: [
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.theory_mode, pattern="^t19_theory$"),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t19_examples$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t19_progress$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                ],
                states.CHOOSING_TOPIC: [
                    CallbackQueryHandler(handlers.select_topic, pattern=r"^t19_topic:"),
                    CallbackQueryHandler(handlers.navigate_topics, pattern=r"^t19_nav:"),
                    CallbackQueryHandler(handlers.back_to_menu, pattern="^t19_back$"),
                ],
                states.AWAITING_ANSWER: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_answer),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.back_to_menu, pattern="^t19_menu$"),
            ],
            allow_reentry=True,
        )
        
        app.add_handler(conv_handler)

plugin = Task19Plugin()