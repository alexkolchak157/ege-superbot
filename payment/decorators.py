# payment/decorators.py
"""Декораторы для проверки подписки."""
import functools
import logging
from typing import Callable, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from .subscription_manager import SubscriptionManager

logger = logging.getLogger(__name__)


def requires_subscription(
    plan_level: Optional[str] = None,
    send_message: bool = True,
    check_channel: bool = False
) -> Callable:
    """
    Декоратор для проверки подписки перед выполнением функции.
    
    Args:
        plan_level: Минимальный уровень подписки (basic_month, pro_month, pro_ege)
        send_message: Отправлять ли сообщение о необходимости подписки
        check_channel: Проверять ли также подписку на канал
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            if not update.effective_user:
                return await func(update, context, *args, **kwargs)
            
            user_id = update.effective_user.id
            subscription_manager = SubscriptionManager()
            
            # Проверяем активную подписку
            subscription = await subscription_manager.check_active_subscription(user_id)
            
            if subscription:
                # Проверяем уровень подписки если указан
                if plan_level:
                    plan_hierarchy = {
                        'basic_month': 1,
                        'pro_month': 2,
                        'pro_ege': 3
                    }
                    
                    user_level = plan_hierarchy.get(subscription['plan_id'], 0)
                    required_level = plan_hierarchy.get(plan_level, 0)
                    
                    if user_level >= required_level:
                        return await func(update, context, *args, **kwargs)
                else:
                    return await func(update, context, *args, **kwargs)
            
            # Проверяем подписку на канал как альтернативу
            if check_channel:
                from core import config, utils
                if hasattr(config, 'REQUIRED_CHANNEL'):
                    is_member = await utils.check_subscription(
                        context.bot, 
                        user_id, 
                        config.REQUIRED_CHANNEL
                    )
                    if is_member:
                        return await func(update, context, *args, **kwargs)
            
            # Нет подписки - отправляем сообщение
            if send_message:
                text = """❌ <b>Требуется подписка!</b>

Для доступа к этой функции необходима активная подписка.

Оформите подписку с помощью команды /subscribe"""
                
                keyboard = [[
                    InlineKeyboardButton("💳 Оформить подписку", callback_data="to_subscription")
                ]]
                
                if update.callback_query:
                    await update.callback_query.answer("Требуется подписка!", show_alert=True)
                    await update.callback_query.message.reply_text(
                        text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await update.message.reply_text(
                        text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
            
            return None
        
        return wrapper
    return decorator