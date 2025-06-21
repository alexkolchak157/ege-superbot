"""Общие утилиты для всех модулей бота."""
import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def safe_edit_message(
    update: Update, new_text: str, reply_markup=None, parse_mode=None
) -> bool:
    """
    Безопасно редактирует сообщение, игнорируя ошибку "не изменено".

    Returns:
        bool: True если сообщение отредактировано, False если не изменилось
    """
    query = update.callback_query
    if not query:
        return False

    try:
        await query.edit_message_text(
            new_text, reply_markup=reply_markup, parse_mode=parse_mode
        )
        return True
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.debug(f"Message not modified for user {query.from_user.id}")
            return False
        else:
            raise


async def safe_answer_callback(
    update: Update, text: str = None, show_alert: bool = False
):
    """Безопасно отвечает на callback query."""
    if update.callback_query:
        try:
            await update.callback_query.answer(text, show_alert=show_alert)
        except Exception as e:
            logger.warning(f"Failed to answer callback query: {e}")


def create_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """Создаёт универсальную клавиатуру возврата в главное меню."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]]
    )


async def check_subscription(user_id: int, bot, channel: Optional[str] = None) -> bool:
    """Проверяет подписку пользователя на канал.

    Args:
        user_id: Telegram ID пользователя.
        bot: Экземпляр бота для вызова API.
        channel: Канал для проверки. Если не указан, используется
            ``core.config.REQUIRED_CHANNEL``.

    Returns:
        ``True`` если пользователь состоит в канале. При ошибке API функция
        возвращает ``True`` чтобы не блокировать доступ к боту.
    """

    from telegram.constants import ChatMemberStatus

    from core.config import REQUIRED_CHANNEL

    if not channel:
        channel = REQUIRED_CHANNEL

    if not channel:
        logger.warning("Канал для проверки подписки не указан")
        return True

    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)

        # Современный API использует перечисление ChatMemberStatus
        status = getattr(member, "status", None)
        if not status:
            return False

        valid_statuses = {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
        }

        # Поддержка разных версий PTB, где статус назывался OWNER или CREATOR
        if hasattr(ChatMemberStatus, "OWNER"):
            valid_statuses.add(ChatMemberStatus.OWNER)
        if hasattr(ChatMemberStatus, "CREATOR"):
            valid_statuses.add(ChatMemberStatus.CREATOR)

        return status in valid_statuses

    except Exception as e:  # pragma: no cover - защита от нестандартных ошибок
        logger.error(f"Ошибка проверки подписки: {e}")
        # В случае ошибки не блокируем пользователя
        return True


async def send_subscription_required(query, channel: str):
    """Отправка сообщения о необходимости подписки."""
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Подписаться", url=f"https://t.me/{channel.lstrip('@')}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 Я подписался", callback_data="check_subscription"
                )
            ],
        ]
    )

    text = f"Для доступа к боту необходимо подписаться на канал {channel}"

    await query.edit_message_text(text, reply_markup=kb)


class CallbackData:
    """Стандартные callback_data для всех плагинов."""

    # Основные действия
    TO_MAIN_MENU = "to_main_menu"
    TO_MENU = "to_menu"
    CANCEL = "cancel"

    @classmethod
    def get_plugin_entry(cls, plugin_code: str) -> str:
        """Возвращает callback_data для входа в плагин."""
        return f"choose_{plugin_code}"
