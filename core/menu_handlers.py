# core/menu_handlers.py
"""Универсальные обработчики для главного меню."""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler
from core.plugin_loader import build_main_menu

async def handle_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальный возврат в главное меню из любого плагина."""
    query = update.callback_query
    if query:
        await query.answer()
        
        kb = build_main_menu()
        try:
            await query.edit_message_text(
                "👋 Что хотите потренировать?", 
                reply_markup=kb
            )
        except Exception as e:
            # Если не удалось отредактировать - отправим новое сообщение
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
    
    # Универсальный возврат в главное меню
    app.add_handler(
        CallbackQueryHandler(
            handle_to_main_menu, 
            pattern="^to_main_menu$"
        ),
        group=0  # Высокий приоритет
    )