"""Плагин для задания 25."""

import logging
from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from core.plugin_base import BotPlugin
from core import states
from . import handlers

logger = logging.getLogger(__name__)

class Task25Plugin(BotPlugin):
    code = "task25"
    title = "Задание 25 (Развёрнутый ответ)"
    menu_priority = 17  # После task20
    
    async def post_init(self, app):
        """Инициализация данных для задания 25."""
        try:
            await handlers.init_task25_data()
            logger.info(f"Task25 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task25 data: {e}")
    
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
                CommandHandler("task25", handlers.cmd_task25),
            ],
            states={
                states.CHOOSING_MODE: [
                    # Основные режимы
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t25_practice$"),
                    CallbackQueryHandler(handlers.theory_mode, pattern="^t25_theory$"),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t25_examples$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t25_progress$"),
                    CallbackQueryHandler(handlers.settings_mode, pattern="^t25_settings$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.noop, pattern="^noop$"),
                    
                    # Обработчики для выбора тем
                    CallbackQueryHandler(handlers.select_block, pattern="^t25_select_block$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t25_(new_topic|retry)$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t25_menu$"),
                    
                    # Навигация по темам
                    CallbackQueryHandler(handlers.block_menu, pattern="^t25_block:"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t25_list_topics($|:page:\d+)"),
                    CallbackQueryHandler(handlers.random_topic_all, pattern="^t25_random_all$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t25_random_block$"),
                    
                    # Банк примеров
                    CallbackQueryHandler(handlers.bank_navigation, pattern="^t25_bank_nav:"),
                    CallbackQueryHandler(handlers.bank_search, pattern="^t25_bank_search$"),
                    
                    # Настройки
                    CallbackQueryHandler(handlers.handle_settings_actions, pattern="^t25_(reset_progress|confirm_reset)$"),
                    CallbackQueryHandler(handlers.set_strictness, pattern="^t25_strictness:"),
                    
                    # Прогресс
                    CallbackQueryHandler(handlers.show_block_stats, pattern="^t25_stats_blocks$"),
                    CallbackQueryHandler(handlers.detailed_progress, pattern="^t25_detailed_progress$"),
                ],
                
                states.CHOOSING_BLOCK: [
                    CallbackQueryHandler(handlers.block_menu, pattern="^t25_block:"),
                    CallbackQueryHandler(handlers.select_block, pattern="^t25_select_block$"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t25_list_topics:page:"),
                ],
                
                states.ANSWERING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_answer),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t25_practice$"),
                ],
                
                states.AWAITING_FEEDBACK: [
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t25_retry$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t25_new_topic$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t25_progress$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t25_menu$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                ],
                
                states.SEARCHING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_bank_search),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t25_examples$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.return_to_menu, pattern="^t25_menu$"),
                CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
            ],
            name="task25_conversation",
            persistent=False,
        )
        
        # Регистрируем обработчики в приложении
        app.add_handler(conv_handler)
        logger.info(f"Registered handlers for {self.title} plugin")

# Экспортируем плагин
plugin = Task25Plugin()

__all__ = ['plugin']