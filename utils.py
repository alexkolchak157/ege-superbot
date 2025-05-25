# core/utils.py
"""Общие утилиты для всех плагинов."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

async def safe_edit_message(
    update: Update, 
    new_text: str, 
    reply_markup=None, 
    parse_mode=None
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
            new_text, 
            reply_markup=reply_markup, 
            parse_mode=parse_mode
        )
        return True
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.debug(f"Message not modified for user {query.from_user.id}")
            return False
        else:
            # Если это другая ошибка - пробрасываем
            raise

async def safe_answer_callback(update: Update, text: str = None, show_alert: bool = False):
    """Безопасно отвечает на callback query."""
    if update.callback_query:
        try:
            await update.callback_query.answer(text, show_alert=show_alert)
        except Exception as e:
            logger.warning(f"Failed to answer callback query: {e}")

def create_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """Создаёт универсальную клавиатуру возврата в главное меню."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])

async def handle_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальный обработчик возврата в главное меню."""
    from .plugin_loader import build_main_menu
    
    await safe_answer_callback(update)
    kb = build_main_menu()
    
    await safe_edit_message(
        update, 
        "👋 Что хотите потренировать?", 
        reply_markup=kb
    )
    
    # Очищаем пользовательские данные
    context.user_data.clear()
    return ConversationHandler.END

def get_plugin_keyboard_pattern(plugin_code: str) -> str:
    """Возвращает паттерн для callback_data плагина."""
    return f"^choose_{plugin_code}$"

class CallbackData:
    """Стандартные callback_data для всех плагинов."""
    
    # Основные действия
    TO_MAIN_MENU = "to_main_menu"
    TO_MENU = "to_menu" 
    CANCEL = "cancel"
    
    # Навигация по режимам
    MODE_RANDOM = "mode:random"
    MODE_TOPIC = "mode:choose_topic"
    MODE_EXAM_NUM = "mode:choose_exam_num"
    
    # Действия после ответа
    NEXT_RANDOM = "next_random"
    NEXT_TOPIC = "next_topic" 
    CHANGE_TOPIC = "change_topic"
    
    # Работа с ошибками
    SHOW_EXPLANATION = "show_explanation"
    NEXT_MISTAKE = "next_mistake"
    SKIP_MISTAKE = "skip_mistake"
    EXIT_MISTAKES = "exit_mistakes"
    
    @classmethod
    def get_plugin_entry(cls, plugin_code: str) -> str:
        """Возвращает callback_data для входа в плагин."""
        return f"choose_{plugin_code}"