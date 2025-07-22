# core/menu_handlers.py
"""Универсальные обработчики для главного меню."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler
from core.plugin_loader import build_main_menu

async def handle_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальный возврат в главное меню из любого плагина."""
    query = update.callback_query
    if query:
        await query.answer()
        
        user_id = update.effective_user.id
        
        # Используем функцию с проверкой доступа
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
            # Если не удалось отредактировать, отправляем новое сообщение
            logger.debug(f"Could not edit message in handle_to_main_menu: {e}")
            await query.message.reply_text(
                "👋 Что хотите потренировать?", 
                reply_markup=kb
            )
    
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
    
    # Универсальный возврат в главное меню с высоким приоритетом
    app.add_handler(
        CallbackQueryHandler(
            handle_to_main_menu, 
            pattern="^to_main_menu$"
        ),
        group=-1  # Высокий приоритет, чтобы обработчик срабатывал раньше других
    )