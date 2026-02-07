"""
Плагин карточек (Flashcards) для заучивания материала ЕГЭ.

Поддерживает колоды:
- Конституция РФ (задание 23)
- Глоссарий обществознания (по категориям)
- Интервальное повторение по алгоритму SM-2
"""

import logging
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)
from core.plugin_base import BotPlugin
from core import states
from . import handlers

logger = logging.getLogger(__name__)


class FlashcardsPlugin(BotPlugin):
    """Плагин карточек для заучивания материала ЕГЭ."""

    code = "flashcards"
    title = "🃏 Карточки (Flashcards)"
    menu_priority = 25  # После всех заданий, перед personal_cabinet

    async def post_init(self, app) -> None:
        """Инициализация данных карточек."""
        try:
            await handlers.init_flashcards_data()
            logger.info("Flashcards plugin initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize flashcards data: {e}")

    def entry_handler(self):
        """Возвращает обработчик для входа из главного меню."""
        return CallbackQueryHandler(
            handlers.entry_from_menu,
            pattern=f"^choose_{self.code}$"
        )

    def register(self, app) -> None:
        """Регистрация обработчиков в приложении."""

        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    handlers.entry_from_menu,
                    pattern=f"^choose_{self.code}$"
                ),
                CommandHandler("flashcards", handlers.cmd_flashcards),
            ],
            states={
                states.FC_MENU: [
                    # Выбор колоды
                    CallbackQueryHandler(
                        handlers.show_deck,
                        pattern=r"^fc_deck_"
                    ),
                    # Навигация
                    CallbackQueryHandler(
                        handlers.back_to_main_menu,
                        pattern="^to_main_menu$"
                    ),
                ],
                states.FC_DECK_VIEW: [
                    # Начать повторение
                    CallbackQueryHandler(
                        handlers.start_review,
                        pattern="^fc_start_review$"
                    ),
                    CallbackQueryHandler(
                        handlers.start_review_all,
                        pattern="^fc_start_review_all$"
                    ),
                    # Навигация
                    CallbackQueryHandler(
                        handlers.back_to_decks,
                        pattern="^fc_back_to_decks$"
                    ),
                    CallbackQueryHandler(
                        handlers.show_deck,
                        pattern=r"^fc_deck_"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_main_menu,
                        pattern="^to_main_menu$"
                    ),
                ],
                states.FC_REVIEWING: [
                    # Показать обратную сторону
                    CallbackQueryHandler(
                        handlers.show_card_back,
                        pattern="^fc_show_back$"
                    ),
                    # Подсказка
                    CallbackQueryHandler(
                        handlers.show_hint,
                        pattern="^fc_show_hint$"
                    ),
                    # Самооценка
                    CallbackQueryHandler(
                        handlers.rate_card,
                        pattern=r"^fc_rate_\d$"
                    ),
                    # Завершить сессию
                    CallbackQueryHandler(
                        handlers.end_session,
                        pattern="^fc_end_session$"
                    ),
                    # Навигация после завершения
                    CallbackQueryHandler(
                        handlers.start_review,
                        pattern="^fc_start_review$"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_decks,
                        pattern="^fc_back_to_decks$"
                    ),
                    CallbackQueryHandler(
                        handlers.show_deck,
                        pattern=r"^fc_deck_"
                    ),
                    CallbackQueryHandler(
                        handlers.back_to_main_menu,
                        pattern="^to_main_menu$"
                    ),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                CallbackQueryHandler(
                    handlers.back_to_decks,
                    pattern="^fc_back_to_decks$"
                ),
                CallbackQueryHandler(
                    handlers.back_to_main_menu,
                    pattern="^to_main_menu$"
                ),
            ],
            name="flashcards_conversation",
            persistent=True,
            allow_reentry=True,
            per_message=False,
            per_chat=True,
            per_user=True,
        )

        app.add_handler(conv_handler)
        logger.info(f"Registered handlers for {self.title} plugin")

    def get_commands(self):
        """Возвращает список команд для меню."""
        return [
            {
                "command": "flashcards",
                "description": "Карточки для заучивания"
            }
        ]

    def get_handlers(self):
        """Возвращает список обработчиков."""
        return [
            ("entry", handlers.entry_from_menu),
            ("deck_view", handlers.show_deck),
            ("start_review", handlers.start_review),
            ("show_back", handlers.show_card_back),
            ("rate", handlers.rate_card),
            ("back_to_decks", handlers.back_to_decks),
            ("main_menu", handlers.back_to_main_menu),
        ]


# Экспортируем плагин
plugin = FlashcardsPlugin()
