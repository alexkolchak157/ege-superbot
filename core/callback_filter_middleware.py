"""
Middleware для фильтрации старых callback queries при запуске бота.

Проблема:
При перезапуске бота Telegram отправляет все накопившиеся обновления,
включая старые callback queries (от нажатий на кнопки). Telegram разрешает
отвечать на callback query только в течение 30-60 секунд. Если бот пытается
ответить на старый callback query, возникает ошибка:
"Query is too old and response timeout expired or query id is invalid"

Решение:
Этот middleware проверяет возраст callback query и игнорирует те,
которые старше CALLBACK_MAX_AGE секунд. Это предотвращает задержки
при запуске и ошибки в логах.
"""

import logging
import time
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler, BaseHandler
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

# Максимальный возраст callback query в секундах (30 секунд - безопасное значение)
CALLBACK_MAX_AGE = 30

# Время запуска бота (устанавливается при регистрации middleware)
BOT_START_TIME = None


async def filter_old_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Фильтрует старые callback queries, чтобы избежать ошибок при запуске.

    Возвращает:
        None - если callback query слишком старый (блокирует дальнейшую обработку)
        True - если callback query свежий (продолжает обработку)
    """
    # Проверяем только callback queries
    if not update.callback_query:
        return

    callback_query = update.callback_query

    # Получаем время создания callback query
    # callback_query.message.date содержит время создания сообщения с кнопкой
    if callback_query.message and callback_query.message.date:
        callback_time = callback_query.message.date.timestamp()
        current_time = time.time()
        age = current_time - callback_time

        # Если callback старше максимального возраста, игнорируем его
        if age > CALLBACK_MAX_AGE:
            logger.info(
                f"Ignoring old callback query (age: {age:.1f}s, "
                f"user: {update.effective_user.id}, "
                f"data: {callback_query.data})"
            )

            # Тихо отвечаем на callback, чтобы убрать "часики" у пользователя
            # Используем try-except, т.к. даже answer может провалиться для старых queries
            try:
                await callback_query.answer()
            except BadRequest as e:
                # Это ожидаемая ошибка для очень старых callback queries
                logger.debug(f"Failed to answer old callback query: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error answering old callback: {e}")

            # Возвращаем None, чтобы остановить дальнейшую обработку этого update
            return None

    # Callback query свежий или мы не можем определить его возраст - продолжаем обработку
    return


def register_callback_filter_middleware(app):
    """
    Регистрирует middleware для фильтрации старых callback queries.

    Должен быть зарегистрирован с group=-2 (раньше других middleware),
    чтобы блокировать старые callbacks до их обработки.
    """
    global BOT_START_TIME
    BOT_START_TIME = time.time()

    # Регистрируем middleware для всех callback queries
    app.add_handler(
        CallbackQueryHandler(
            filter_old_callbacks,
            pattern=".*"  # Для всех callback queries
        ),
        group=-2  # Выполняется раньше других middleware (до user_middleware с group=-1)
    )

    logger.info(
        f"Callback filter middleware registered "
        f"(max age: {CALLBACK_MAX_AGE}s)"
    )
