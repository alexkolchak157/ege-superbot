"""Плагин для задания 19."""

import logging
from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from core.plugin_base import BotPlugin
from core import states
from . import handlers

logger = logging.getLogger(__name__)


class Task19Plugin(BotPlugin):
    code = "task19"
    title = "Задание 19 (Примеры)"
    menu_priority = 15
    
    async def post_init(self, app):
        """Инициализация данных для задания 19."""
        try:
            await handlers.init_task19_data()
            logger.info(f"Task19 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task19 data: {e}")
            # Не падаем, даже если не удалось загрузить данные
            pass
    
    def entry_handler(self):
        """Возвращает обработчик для входа из главного меню."""
        return CallbackQueryHandler(
            handlers.entry_from_menu,
            pattern=f"^choose_{self.code}$"
        )
    
    def register(self, app):
        """Регистрация обработчиков в приложении."""
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
                    # Основные режимы
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.theory_mode, pattern="^t19_theory$"),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t19_examples$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t19_progress$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.noop, pattern="^noop$"),
                    # Обработчики для выбора тем
                    CallbackQueryHandler(handlers.select_block, pattern="^t19_select_block$"),
                    CallbackQueryHandler(handlers.random_topic_all, pattern="^t19_random_all$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t19_random_block$"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t19_list_topics$"),
                    # Навигация по банку примеров
                    CallbackQueryHandler(handlers.bank_navigation, pattern=r"^t19_bank_(next|prev)$"),
                ],
                states.CHOOSING_BLOCK: [
                    CallbackQueryHandler(handlers.block_menu, pattern=r"^t19_block:"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t19_random_block$"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t19_list_topics$"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                    CallbackQueryHandler(handlers.select_block, pattern="^t19_select_block$"),
                ],
                states.CHOOSING_TOPIC: [
                    CallbackQueryHandler(handlers.select_topic, pattern=r"^t19_topic:"),
                    CallbackQueryHandler(handlers.list_topics, pattern=r"^t19_list_topics:page:"),
                    CallbackQueryHandler(handlers.block_menu, pattern=r"^t19_block:"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                ],
                states.ANSWERING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_answer),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
            ],
            name="task19_conversation",
            persistent=False,
        )
        
        # Регистрируем обработчики в приложении
        app.add_handler(conv_handler)
        logger.info(f"Registered handlers for {self.title} plugin")


# Экспортируем плагин
plugin = Task19Plugin()
