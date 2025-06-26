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

    def register_handlers(self, app):
        """Регистрирует обработчики команд и callback'ов в приложении."""
        from . import handlers
        
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("task19", handlers.cmd_task19),
                CallbackQueryHandler(handlers.practice_mode, pattern="^task19$"),
            ],
            states={
                states.CHOOSING_MODE: [
                    # Основные режимы
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.theory_mode, pattern="^t19_theory$"),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t19_examples$"),
                    CallbackQueryHandler(handlers.show_progress, pattern="^t19_progress$"),
                    CallbackQueryHandler(handlers.settings_mode, pattern="^t19_settings$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                    
                    # Выбор тем
                    CallbackQueryHandler(handlers.random_topic, pattern="^t19_random$"),
                    CallbackQueryHandler(handlers.select_block, pattern="^t19_select_block$"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t19_list_topics$"),
                    
                    # Дополнительные функции
                    CallbackQueryHandler(handlers.bank_search, pattern="^t19_bank_search$"),
                    CallbackQueryHandler(handlers.bank_navigation, pattern="^t19_bank_nav:"),
                    CallbackQueryHandler(handlers.export_results, pattern="^t19_export$"),
                    CallbackQueryHandler(handlers.reset_results, pattern="^t19_reset_confirm$"),
                    CallbackQueryHandler(handlers.noop, pattern="^noop$"),
                ],
                
                states.CHOOSING_BLOCK: [
                    CallbackQueryHandler(handlers.block_menu, pattern="^t19_block:"),
                    CallbackQueryHandler(handlers.list_topics, pattern="^t19_list_topics$"),
                    CallbackQueryHandler(handlers.random_topic_block, pattern="^t19_random_block$"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                ],
                
                states.CHOOSING_TOPIC: [
                    CallbackQueryHandler(handlers.select_topic, pattern="^t19_topic:"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.block_menu, pattern="^t19_block:"),
                    CallbackQueryHandler(handlers.list_topics, pattern=r"^t19_list_topics:page:\d+"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                ],
                
                states.ANSWERING: [
                    # ВАЖНО: Убедиться, что обработчики правильно настроены
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_answer),
                    MessageHandler(filters.Document.ALL, handlers.handle_answer_document_task19),
                    # Добавить возможность отмены
                    CallbackQueryHandler(handlers.practice_mode, pattern="^t19_practice$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                ],
                
                states.SEARCHING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_bank_search),
                    CallbackQueryHandler(handlers.examples_bank, pattern="^t19_examples$"),
                ],
                
                # Состояние после оценки ответа
                states.AWAITING_FEEDBACK: [
                    CallbackQueryHandler(handlers.practice_mode, pattern="^next_topic$"),
                    CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                    CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                    CallbackQueryHandler(handlers.practice_mode, pattern="^retry$"),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(handlers.return_to_menu, pattern="^t19_menu$"),
                CallbackQueryHandler(handlers.back_to_main_menu, pattern="^to_main_menu$"),
                # Добавить fallback для неизвестных callback'ов
                CallbackQueryHandler(lambda u, c: u.callback_query.answer("Неизвестная команда"), pattern=".*"),
            ],
            name="task19_conversation",
            persistent=False,  # Важно для правильной работы состояний
            per_message=False,  # Состояние привязано к пользователю, не к сообщению
            per_chat=True,  # Состояние для каждого чата отдельно
            per_user=True,  # Состояние для каждого пользователя отдельно
        )
        
        # Регистрируем обработчики в приложении
        app.add_handler(conv_handler)
        
        # Обработчик для кнопки "OK" после показа streak
        app.add_handler(
            CallbackQueryHandler(
                lambda u, c: u.callback_query.answer("👍"),
                pattern="^streak_ok$"
            )
        )
        
        logger.info(f"Registered handlers for {self.title} plugin")


# Экспортируем плагин
plugin = Task19Plugin()