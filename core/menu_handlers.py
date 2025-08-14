# core/menu_handlers.py
"""Глобальные обработчики меню."""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler
import logging

logger = logging.getLogger(__name__)

async def handle_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для кнопки 'Главное меню'."""
    query = update.callback_query
    
    if query:
        await query.answer()
        
        user_id = query.from_user.id
        
        welcome_text = """
🎓 <b>Подготовка к ЕГЭ по обществознанию</b>

Используйте кнопки ниже для навигации:
"""
        
        # Используем функцию с проверкой доступа
        try:
            from core.app import show_main_menu_with_access
            kb = await show_main_menu_with_access(context, user_id)
        except ImportError:
            # Если функция еще не добавлена, используем стандартное меню
            try:
                from core.plugin_loader import build_main_menu
                kb = build_main_menu()
            except ImportError as e:
                logger.error(f"Could not import menu builder: {e}")
                kb = None
        
        try:
            if kb:
                await query.edit_message_text(
                    welcome_text, 
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            else:
                await query.edit_message_text(
                    welcome_text,
                    parse_mode="HTML"
                )
        except Exception as e:
            # Если не удалось отредактировать, отправляем новое сообщение
            logger.debug(f"Could not edit message in handle_to_main_menu: {e}")
            try:
                if kb:
                    await query.message.reply_text(
                        welcome_text, 
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                else:
                    await query.message.reply_text(
                        welcome_text,
                        parse_mode="HTML"
                    )
            except Exception as e2:
                logger.error(f"Could not send message: {e2}")
    
    # === ГЛАВНОЕ ИСПРАВЛЕНИЕ: НЕ ОЧИЩАЕМ context.user_data.clear()! ===
    
    # Определяем, какие данные нужно сохранить (всё важное)
    data_to_preserve = []
    
    # Данные всех модулей
    modules = ['task19', 'task20', 'task24', 'task25', 'test_part']
    for module in modules:
        data_to_preserve.extend([
            f'{module}_results',
            f'{module}_practice_stats',
            f'{module}_achievements',
            f'{module}_stats'
        ])
    
    # Специфичные данные
    data_to_preserve.extend([
        'practiced_topics',      # task24
        'scores_history',        # task24
        'correct_streak',        # общий счетчик
        'practice_stats',        # старое хранилище
        'user_preferences',      # настройки
        'subscription_status',   # подписка
        'subscription_expiry',   
        'purchased_modules'      
    ])
    
    # Сохраняем важные данные
    preserved_data = {}
    for key in data_to_preserve:
        if key in context.user_data:
            preserved_data[key] = context.user_data[key]
    
    # Очищаем ТОЛЬКО временные ключи текущей сессии
    temp_keys = [
        'current_topic',
        'task19_current_topic',
        'task20_current_topic',
        'task24_current_topic',
        'task25_current_topic',
        'answer_processing',
        'current_block',
        'waiting_for_bank_search',
        'active_module',
        'current_module',
        'bank_current_idx',
        'current_question_idx',
        'test_answers',
        'viewing_mode',
        'search_query',
        'temp_message_id',
        'thinking_message_id',
        '_state',
        'conversation_state'
    ]
    
    # Удаляем только временные ключи
    removed = 0
    for key in temp_keys:
        if key in context.user_data:
            context.user_data.pop(key)
            removed += 1
    
    # Восстанавливаем сохраненные данные (на случай если что-то случайно удалили)
    context.user_data.update(preserved_data)
    
    logger.info(f"Menu navigation: preserved {len(preserved_data)} keys, removed {removed} temp keys")
    
    return ConversationHandler.END


async def handle_plugin_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора плагина из главного меню."""
    query = update.callback_query
    
    # === ИСПРАВЛЕНИЕ: НЕ ДЕЛАЕМ context.user_data.clear()! ===
    # Очищаем только временное состояние предыдущего модуля
    temp_keys = [
        'current_topic',
        'active_module',
        'current_module',
        'answer_processing',
        'current_block',
        'viewing_mode',
        '_state',
        'conversation_state'
    ]
    
    for key in temp_keys:
        context.user_data.pop(key, None)
    
    # Логируем для отладки
    logger.info(f"Plugin choice: {query.data}, preserved data keys: {len(context.user_data)}")
    
    # Отвечаем на callback
    if query:
        await query.answer()
    
    # ConversationHandler плагина сам обработает вход
    return None


def register_global_handlers(app):
    """Регистрирует глобальные обработчики, работающие во всех плагинах."""
    
    # Универсальный возврат в главное меню с высоким приоритетом
    app.add_handler(
        CallbackQueryHandler(
            handle_to_main_menu, 
            pattern="^to_main_menu$"
        ),
        group=-1  # Высокий приоритет - срабатывает раньше других
    )
    
    # Для обратной совместимости со старым паттерном
    app.add_handler(
        CallbackQueryHandler(
            handle_to_main_menu, 
            pattern="^main_menu$"
        ),
        group=-1
    )