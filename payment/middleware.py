# payment/middleware.py
"""Middleware для проверки платной подписки."""
import logging
from functools import wraps
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import db
from .subscription_manager import SubscriptionManager

logger = logging.getLogger(__name__)

# Лимиты для бесплатных пользователей
FREE_MONTHLY_LIMIT = 50

subscription_manager = SubscriptionManager()


def requires_subscription(func=None, *, feature=None, check_limit=True):
    """
    Декоратор для проверки подписки перед выполнением функции.
    
    Args:
        feature: Название функции для логирования
        check_limit: Проверять ли месячный лимит для бесплатных пользователей
    """
    def decorator(handler_func):
        @wraps(handler_func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            
            # Получаем статус пользователя
            user_status = await db.get_or_create_user_status(user_id)
            is_subscribed = user_status.get('is_subscribed', False)
            monthly_usage = user_status.get('monthly_usage_count', 0)
            
            # Если есть подписка - пропускаем
            if is_subscribed:
                return await handler_func(update, context)
            
            # Для бесплатных пользователей проверяем лимит
            if check_limit and monthly_usage >= FREE_MONTHLY_LIMIT:
                await show_subscription_required(update, monthly_usage)
                return
            
            # Увеличиваем счетчик использования
            if check_limit:
                await db.increment_usage(user_id)
            
            # Выполняем основную функцию
            return await handler_func(update, context)
        
        return wrapper
    
    if func:
        return decorator(func)
    return decorator


async def show_subscription_required(update: Update, current_usage: int):
    """Показывает сообщение о необходимости подписки."""
    text = f"""❌ <b>Достигнут месячный лимит</b>

Вы использовали {current_usage} из {FREE_MONTHLY_LIMIT} бесплатных вопросов в этом месяце.

Оформите подписку для получения:
• Неограниченного доступа к вопросам
• Расширенной статистики
• Приоритетной поддержки
• Экспорта результатов

Выберите подходящий план:"""
    
    keyboard = [
        [InlineKeyboardButton("💎 Оформить подписку", callback_data="to_subscription")],
        [InlineKeyboardButton("📊 Мой статус", callback_data="check_subscription_status")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )


async def check_subscription_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для проверки статуса подписки."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем данные
    user_status = await db.get_or_create_user_status(user_id)
    subscription = await subscription_manager.check_active_subscription(user_id)
    
    if subscription:
        from .config import SUBSCRIPTION_PLANS
        plan = SUBSCRIPTION_PLANS[subscription['plan_id']]
        expires = subscription['expires_at'].strftime('%d.%m.%Y')
        days_left = (subscription['expires_at'] - datetime.now(timezone.utc)).days
        
        text = f"""✅ <b>У вас есть активная подписка!</b>

📋 План: {plan['name']}
📅 Действует до: {expires}
⏳ Осталось дней: {days_left}

Вы можете использовать все функции бота без ограничений."""
        
        keyboard = [[
            InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
        ]]
        
    else:
        usage = user_status.get('monthly_usage_count', 0)
        remaining = max(0, FREE_MONTHLY_LIMIT - usage)
        
        text = f"""❌ <b>Подписка не активна</b>

📊 Использовано в этом месяце: {usage} / {FREE_MONTHLY_LIMIT}
📝 Осталось вопросов: {remaining}

В бесплатной версии доступно {FREE_MONTHLY_LIMIT} вопросов в месяц."""
        
        keyboard = [
            [InlineKeyboardButton("💎 Оформить подписку", callback_data="to_subscription")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


def register_subscription_middleware(app):
    """Регистрирует middleware и обработчики подписки."""
    from telegram.ext import CallbackQueryHandler
    
    # Обработчик проверки статуса
    app.add_handler(
        CallbackQueryHandler(
            check_subscription_status_handler,
            pattern="^check_subscription_status$"
        ),
        group=1
    )