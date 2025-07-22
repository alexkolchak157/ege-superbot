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
        
        # Проверяем подписку для правильного отображения статуса
        subscription_manager = context.bot_data.get('subscription_manager')
        if subscription_manager:
            subscription_info = await subscription_manager.get_subscription_info(user_id)
            
            if subscription_info:
                if subscription_info.get('type') == 'modular':
                    modules = subscription_info.get('modules', [])
                    if modules:
                        status_text = f"✅ У вас активная подписка на модули:\n"
                        for module in modules:
                            status_text += f"   • {module}\n"
                        status_text += f"\nДействует до: {subscription_info.get('expires_at').strftime('%d.%m.%Y')}"
                    else:
                        status_text = "❌ У вас нет активной подписки"
                else:
                    plan_name = subscription_info.get('plan_name', 'Подписка')
                    status_text = f"✅ У вас активная подписка: {plan_name}"
                    status_text += f"\nДействует до: {subscription_info.get('expires_at').strftime('%d.%m.%Y')}"
            else:
                status_text = "❌ У вас нет активной подписки"
        else:
            status_text = ""
        
        # Используем тот же текст, что и в start_command
        welcome_text = f"""
👋 Добро пожаловать в бот для подготовки к ЕГЭ по обществознанию!

{status_text}

Используйте кнопки ниже для навигации:
"""
        
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
                welcome_text, 
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception as e:
            # Если не удалось отредактировать, отправляем новое сообщение
            logger.debug(f"Could not edit message in handle_to_main_menu: {e}")
            await query.message.reply_text(
                welcome_text, 
                reply_markup=kb,
                parse_mode="HTML"
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