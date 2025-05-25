# core/menu_handlers.py
"""Универсальные обработчики для главного меню."""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler
from .utils import safe_edit_message, safe_answer_callback, CallbackData
from .plugin_loader import build_main_menu

async def handle_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальный возврат в главное меню из любого плагина."""
    await safe_answer_callback(update)
    
    kb = build_main_menu()
    await safe_edit_message(
        update, 
        "👋 Что хотите потренировать?", 
        reply_markup=kb
    )
    
    # Очищаем данные пользователя
    context.user_data.clear()
    return ConversationHandler.END

def register_global_handlers(app):
    """Регистрирует глобальные обработчики, работающие во всех плагинах."""
    
    # Универсальный возврат в главное меню
    app.add_handler(
        CallbackQueryHandler(
            handle_to_main_menu, 
            pattern=f"^{CallbackData.TO_MAIN_MENU}$"
        ),
        group=0  # Высокий приоритет
    )