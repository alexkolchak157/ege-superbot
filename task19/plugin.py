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
                    CallbackQueryHandler(handlers.settings_mode, pattern="^t19_settings$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.noop, pattern="^noop$"),
                    
                    # Обработчики для выбора тем
                    CallbackQueryHandler(handlers.select_block, pattern="^t19_select_block$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t19_(new|retry)$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                    
                    # Навигация по темам
                    CallbackQueryHandler(handlers.block_menu, pattern="^t19_block:"),
                    CallbackQueryHandler(handlers.list_topics, pattern=r"^t19_list_topics($|:page:\d+)"),
                    CallbackQueryHandler(handlers.random_topic_all, pattern="^t19_random_all$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t19_random_block$"),
                    
                    # Банк примеров
                    CallbackQueryHandler(handlers.bank_navigation, pattern="^t19_bank_nav:"),
                    CallbackQueryHandler(handlers.bank_search, pattern="^t19_bank_search$"),
                    
                    # Настройки
                    CallbackQueryHandler(handlers.apply_strictness, pattern="^t19_set_strictness:"),
                    
                    # Статистика
                    CallbackQueryHandler(handlers.detailed_progress, pattern="^t19_detailed_progress$"),
                    CallbackQueryHandler(handlers.export_results, pattern="^t19_export$"),
                    
                    # Теория - подразделы
                    CallbackQueryHandler(handlers.handle_theory_sections, pattern="^t19_(how_to_write|good_examples|common_mistakes|useful_phrases)$"),
                    
                    # Настройки
                    CallbackQueryHandler(handlers.handle_settings_actions, pattern="^t19_(reset_progress|confirm_reset)$"),
                    
                    # Новые функции
                    CallbackQueryHandler(handlers.mistakes_mode, pattern="^t19_mistakes$"),
                    CallbackQueryHandler(handlers.show_achievements, pattern="^t19_achievements$"),
                ],
                
                states.CHOOSING_BLOCK: [
                    CallbackQueryHandler(handlers.block_menu, pattern="^t19_block:"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t19_list_topics$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t19_random_block$"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.select_block, pattern="^t19_select_block$"),
                ],
                
                states.CHOOSING_TOPIC: [
                    CallbackQueryHandler(handlers.choose_topic, pattern="^t19_topic:"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.block_menu, pattern="^t19_block:"),
                    CallbackQueryHandler(handlers.select_block, pattern="^t19_select_block$"),
                    CallbackQueryHandler(handlers.list_topics, pattern=r"^t19_list_topics:page:\d+"),
                ],
                
                states.ANSWERING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_answer),
                    MessageHandler(filters.Document.ALL, handlers.handle_answer_document_task19),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                ],
                states.AWAITING_FEEDBACK: [
                    CallbackQueryHandler(handlers.practice_mode, pattern="^next_topic$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^retry$"),
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
        app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer() if u.callback_query else None,pattern="^streak_ok$"))
        logger.info(f"Registered handlers for {self.title} plugin")


# Экспортируем плагин
plugin = Task19Plugin()