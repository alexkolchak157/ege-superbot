"""
Плагин карточек (Flashcards) для заучивания материала ЕГЭ.

Поддерживает:
- Колоды карточек (Конституция РФ, глоссарий, ошибки)
- Интервальное повторение SM-2
- Quiz-режимы (Верно/Неверно, Выбор из вариантов)
- Ежедневный челлендж
- Конструктор планов (задание 24)
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
from . import quiz_handlers
from . import daily_challenge
from . import plan_constructor

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

        # Общие навигационные хендлеры (используются во многих состояниях)
        nav_back_to_decks = CallbackQueryHandler(
            handlers.back_to_decks,
            pattern="^fc_back_to_decks$"
        )
        nav_main_menu = CallbackQueryHandler(
            handlers.back_to_main_menu,
            pattern="^to_main_menu$"
        )
        nav_deck = CallbackQueryHandler(
            handlers.show_deck,
            pattern=r"^fc_deck_"
        )

        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    handlers.entry_from_menu,
                    pattern=f"^choose_{self.code}$"
                ),
                CommandHandler("flashcards", handlers.cmd_flashcards),
            ],
            states={
                # ── Главное меню карточек ──
                states.FC_MENU: [
                    # Выбор колоды
                    CallbackQueryHandler(
                        handlers.show_deck,
                        pattern=r"^fc_deck_"
                    ),
                    # Ежедневный челлендж
                    CallbackQueryHandler(
                        daily_challenge.show_daily_menu,
                        pattern="^fc_daily_menu$"
                    ),
                    # Конструктор планов
                    CallbackQueryHandler(
                        plan_constructor.show_plan_menu,
                        pattern="^fc_plan_menu$"
                    ),
                    # Генерация колоды из ошибок
                    CallbackQueryHandler(
                        handlers.generate_mistakes,
                        pattern="^fc_gen_mistakes$"
                    ),
                    # Навигация
                    nav_main_menu,
                ],

                # ── Просмотр колоды ──
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
                    # Quiz-режим
                    CallbackQueryHandler(
                        quiz_handlers.start_quiz,
                        pattern="^fc_start_quiz$"
                    ),
                    # Навигация
                    nav_back_to_decks,
                    nav_deck,
                    nav_main_menu,
                ],

                # ── Сессия повторения карточек ──
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
                    nav_back_to_decks,
                    nav_deck,
                    nav_main_menu,
                ],

                # ── Quiz-режим ──
                states.FC_QUIZ: [
                    # True/False ответы
                    CallbackQueryHandler(
                        quiz_handlers.handle_tf_answer,
                        pattern=r"^fc_quiz_tf_"
                    ),
                    # Multiple Choice ответы
                    CallbackQueryHandler(
                        quiz_handlers.handle_mc_answer,
                        pattern=r"^fc_quiz_mc_\d"
                    ),
                    # Следующий вопрос
                    CallbackQueryHandler(
                        quiz_handlers.quiz_next,
                        pattern="^fc_quiz_next$"
                    ),
                    # Результаты
                    CallbackQueryHandler(
                        quiz_handlers.quiz_results,
                        pattern="^fc_quiz_results$"
                    ),
                    # Досрочное завершение
                    CallbackQueryHandler(
                        quiz_handlers.quiz_end,
                        pattern="^fc_quiz_end$"
                    ),
                    # Новый quiz (из экрана результатов)
                    CallbackQueryHandler(
                        quiz_handlers.start_quiz,
                        pattern="^fc_start_quiz$"
                    ),
                    # Навигация из результатов
                    nav_back_to_decks,
                    nav_deck,
                    nav_main_menu,
                ],

                # ── Ежедневный челлендж ──
                states.FC_DAILY: [
                    # Начать челлендж
                    CallbackQueryHandler(
                        daily_challenge.start_daily,
                        pattern="^fc_daily_start$"
                    ),
                    # True/False ответы
                    CallbackQueryHandler(
                        daily_challenge.handle_daily_tf,
                        pattern=r"^fc_daily_tf_"
                    ),
                    # Multiple Choice ответы
                    CallbackQueryHandler(
                        daily_challenge.handle_daily_mc,
                        pattern=r"^fc_daily_mc_\d"
                    ),
                    # Навигация
                    nav_back_to_decks,
                    nav_main_menu,
                ],

                # ── Конструктор планов ──
                states.FC_PLAN: [
                    # Выбор блока → начать сессию
                    CallbackQueryHandler(
                        plan_constructor.start_plan_session,
                        pattern=r"^fc_plan_block_"
                    ),
                    # Ответ на вопрос
                    CallbackQueryHandler(
                        plan_constructor.handle_plan_answer,
                        pattern=r"^fc_plan_ans_\d"
                    ),
                    # Досрочное завершение
                    CallbackQueryHandler(
                        plan_constructor.plan_end,
                        pattern="^fc_plan_end$"
                    ),
                    # Вернуться к меню планов
                    CallbackQueryHandler(
                        plan_constructor.show_plan_menu,
                        pattern="^fc_plan_menu$"
                    ),
                    # Навигация
                    nav_back_to_decks,
                    nav_main_menu,
                ],
            },
            fallbacks=[
                CommandHandler("cancel", handlers.cmd_cancel),
                nav_back_to_decks,
                nav_main_menu,
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
            ("quiz", quiz_handlers.start_quiz),
            ("daily", daily_challenge.show_daily_menu),
            ("plans", plan_constructor.show_plan_menu),
            ("back_to_decks", handlers.back_to_decks),
            ("main_menu", handlers.back_to_main_menu),
        ]


# Экспортируем плагин
plugin = FlashcardsPlugin()
