"""Плагин для задания 20."""

import logging
from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from core.plugin_base import BotPlugin
from core import states
from . import handlers

logger = logging.getLogger(__name__)

class Task20Plugin(BotPlugin):
    code = "task20"
    title = "Задание 20 (Суждения)"
    menu_priority = 16  # После task19
    
    async def post_init(self, app):
        """Инициализация данных для задания 20."""
        try:
            await handlers.init_task20_data()
            logger.info(f"Task20 plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize task20 data: {e}")
    
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
                CommandHandler("task20", handlers.cmd_task20),
            ],
            states={
                states.CHOOSING_MODE: [
                    # Основные режимы
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t20_practice$"),
                    CallbackQueryHandler(handlers.theory_mode, pattern="^t20_theory$"),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t20_examples$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t20_progress$"),
                    CallbackQueryHandler(handlers.settings_mode, pattern="^t20_settings$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.noop, pattern="^noop$"),
                    
                    # Обработчики для выбора тем
                    CallbackQueryHandler(handlers.select_block, pattern="^t20_select_block$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t20_(new|retry)$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t20_menu$"),
                    
                    # Навигация по темам
                    CallbackQueryHandler(handlers.block_menu, pattern="^t20_block:"),
                    CallbackQueryHandler(handlers.list_topics, pattern=r"^t20_list_topics($|:page:\d+)"),
                    CallbackQueryHandler(handlers.random_topic_all, pattern="^t20_random_all$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t20_random_block$"),
                    
                    # Банк суждений
                    CallbackQueryHandler(handlers.bank_navigation, pattern="^t20_bank_nav:"),
                    CallbackQueryHandler(handlers.bank_search, pattern="^t20_bank_search$"),
                    
                    # Настройки
                    CallbackQueryHandler(handlers.set_strictness, pattern="^t20_set_strictness:"),
                    
                    # Статистика
                    CallbackQueryHandler(handlers.detailed_progress, pattern="^t20_detailed_progress$"),
                    CallbackQueryHandler(handlers.export_results, pattern="^t20_export$"),
                    
                    # Теория - подразделы
                    CallbackQueryHandler(handlers.handle_theory_sections, pattern="^t20_(how_to_write|good_examples|common_mistakes|useful_phrases)$"),
                    
                    # Настройки
                    CallbackQueryHandler(handlers.handle_settings_actions, pattern="^t20_(reset_progress|confirm_reset)$"),
                    
                    # Новые функции
                    CallbackQueryHandler(handlers.mistakes_mode, pattern="^t20_mistakes$"),
                    CallbackQueryHandler(handlers.show_achievements, pattern="^t20_achievements$"),
                ],
                
                states.CHOOSING_BLOCK: [
                    CallbackQueryHandler(handlers.block_menu, pattern="^t20_block:"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t20_list_topics$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t20_random_block$"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t20_practice$"),
                    CallbackQueryHandler(handlers.select_block, pattern="^t20_select_block$"),
                ],
                
                states.CHOOSING_TOPIC: [
                    CallbackQueryHandler(handlers.choose_topic, pattern="^t20_topic:"),
                    CallbackQueryHandler(handlers.block_menu, pattern="^t20_block:"),
                    CallbackQueryHandler(handlers.select_block, pattern="^t20_select_block$"),
                    CallbackQueryHandler(handlers.list_topics, pattern=r"^t20_list_topics:page:\d+"),
                ],
                
                states.ANSWERING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_answer),
                    MessageHandler(filters.Document.ALL, handlers.handle_answer_document_task20),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t20_practice$"),
                ],
                
                states.AWAITING_FEEDBACK: [
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t20_retry$"),
                    CallbackQueryHandler(handlers.handle_result_action, pattern="^t20_new$"),
                    CallbackQueryHandler(handlers.my_progress, pattern="^t20_progress$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t20_menu$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                ],
                
                states.SEARCHING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_bank_search),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t20_examples$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.return_to_menu, pattern="^t20_menu$"),
                CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
            ],
            name="task20_conversation",
            persistent=False,
        )
        
        # Регистрируем обработчики в приложении
        app.add_handler(conv_handler)
        app.add_handler(
            CallbackQueryHandler(
                lambda u, c: u.callback_query.answer() if u.callback_query else None,
                pattern="^streak_ok$",
            )
        )
        app.add_handler(CallbackQueryHandler(handlers.handle_achievement_ok, pattern="^t20_achievement_ok$"))
        logger.info(f"Registered handlers for {self.title} plugin")

# Экспортируем плагин
plugin = Task20Plugin()