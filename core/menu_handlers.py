# core/menu_handlers.py
"""Универсальные обработчики для главного меню."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler
from core.plugin_loader import build_main_menu

async def handle_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальный возврат в главное меню из любого плагина."""
    query = update.callback_query
    if query:
        await query.answer()
        
        user_id = update.effective_user.id
        
        # Проверяем, есть ли функция show_main_menu_with_access
        try:
            from core.app import show_main_menu_with_access
            kb = await show_main_menu_with_access(context, user_id)
        except ImportError:
            # Если функция еще не добавлена, используем стандартное меню
            from core.plugin_loader import build_main_menu
            kb = build_main_menu()
        
        try:
            await query.edit_message_text(
                "👋 Что хотите потренировать?", 
                reply_markup=kb
            )
        except Exception as e:
            # Просто отвечаем на callback без создания нового сообщения
            logger.debug(f"Could not edit message in handle_to_main_menu: {e}")
    
    # Очищаем данные пользователя
    context.user_data.clear()
    return ConversationHandler.END

async def handle_plugin_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора плагина из главного меню."""
    query = update.callback_query
    
    # Очищаем предыдущее состояние
    context.user_data.clear()
    
    # Логируем для отладки
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Plugin choice: {query.data}")
    
    # Отвечаем на callback
    await query.answer()
    
    # ConversationHandler плагина сам обработает вход
    return None  # Не возвращаем состояние

def register_global_handlers(app):
    """Регистрирует глобальные обработчики, работающие во всех плагинах."""
    
    # Универсальный возврат в главное меню
    app.add_handler(
        CallbackQueryHandler(
            handle_to_main_menu, 
            pattern="^to_main_menu$"
        ),
        group=0  # Высокий приоритет
    )