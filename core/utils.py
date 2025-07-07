# core/utils.py - обновленная версия с проверкой платных подписок

import logging
from typing import Optional, Union
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime

from core import config, db
from payment.subscription_manager import SubscriptionManager

logger = logging.getLogger(__name__)

async def check_subscription(
    user_id: int, 
    bot, 
    channel: Optional[str] = None,
    check_paid: bool = True,
    check_channel: bool = False
) -> bool:
    """
    Проверяет подписку пользователя.
    
    Args:
        user_id: ID пользователя
        bot: Объект бота
        channel: Канал для проверки (если check_channel=True)
        check_paid: Проверять платную подписку (по умолчанию True)
        check_channel: Проверять подписку на канал (по умолчанию False)
    
    Returns:
        True если есть активная подписка, False иначе
    """
    
    # Сначала проверяем платную подписку
    if check_paid:
        subscription_manager = SubscriptionManager()
        subscription_info = await subscription_manager.get_subscription_info(user_id)
        
        if subscription_info['is_active']:
            return True
    
    # Опционально проверяем подписку на канал (для обратной совместимости)
    if check_channel and channel:
        try:
            chat_member = await bot.get_chat_member(channel, user_id)
            if chat_member.status in ['member', 'administrator', 'creator']:
                return True
        except Exception as e:
            logger.error(f"Ошибка при проверке подписки на канал: {e}")
    
    return False

async def send_subscription_required(
    query_or_update: Union[Update, any],
    channel: Optional[str] = None,
    show_plans: bool = True
) -> None:
    """
    Отправляет сообщение о необходимости подписки.
    
    Args:
        query_or_update: Update или CallbackQuery
        channel: Канал для подписки (опционально)
        show_plans: Показывать ли планы подписок
    """
    
    # Определяем, как отправить сообщение
    if hasattr(query_or_update, 'message'):
        message = query_or_update.message
        answer_func = message.reply_text
    elif hasattr(query_or_update, 'answer'):
        answer_func = query_or_update.answer
        message = query_or_update.message
    else:
        logger.error("Неизвестный тип объекта для отправки сообщения")
        return
    
    text = "❌ Для доступа к этой функции необходима подписка!\n\n"
    
    # Кнопки
    keyboard = []
    
    if show_plans:
        text += "💎 Выберите подходящий план:\n"
        text += "• Базовый (299₽/мес) - 100 вопросов в день\n"
        text += "• Pro (599₽/мес) - неограниченно\n"
        text += "• Pro до ЕГЭ (1999₽) - неограниченно до ЕГЭ 2025\n"
        
        keyboard.append([
            InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe_start")
        ])
    
    if channel:
        text += f"\n📣 Или подпишитесь на канал {channel} для бесплатного доступа"
        keyboard.append([
            InlineKeyboardButton("📣 Подписаться на канал", url=f"https://t.me/{channel[1:]}")
        ])
    
    keyboard.append([
        InlineKeyboardButton("🔄 Проверить подписку", callback_data="check_subscription")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отправляем сообщение
    if hasattr(answer_func, '__call__'):
        if hasattr(query_or_update, 'answer'):
            # Для CallbackQuery используем answer и edit_message_text
            await query_or_update.answer("Требуется подписка!", show_alert=True)
            await message.edit_text(text, reply_markup=reply_markup)
        else:
            # Для обычного сообщения
            await answer_func(text, reply_markup=reply_markup)

async def check_daily_limit(user_id: int) -> tuple[bool, int, int]:
    """
    Проверяет дневной лимит использования для пользователя.
    
    Returns:
        (можно_использовать, использовано_сегодня, лимит)
    """
    subscription_manager = SubscriptionManager()
    subscription_info = await subscription_manager.get_subscription_info(user_id)
    
    # Для Pro подписок нет лимита
    if subscription_info['is_active'] and subscription_info['plan_id'] in ['pro_month', 'pro_ege']:
        return True, 0, -1  # -1 означает безлимит
    
    # Получаем использование за сегодня
    today = datetime.now().date().isoformat()
    user_data = await db.get_user(user_id)
    
    if not user_data:
        return False, 0, 0
    
    # Сбрасываем счетчик, если новый день
    if user_data.get('last_usage_date') != today:
        await db.execute_query(
            "UPDATE users SET daily_usage_count = 0, last_usage_date = ? WHERE user_id = ?",
            (today, user_id)
        )
        daily_count = 0
    else:
        daily_count = user_data.get('daily_usage_count', 0)
    
    # Определяем лимит
    if subscription_info['is_active'] and subscription_info['plan_id'] == 'basic_month':
        limit = 100  # Базовый план - 100 в день
    else:
        # Бесплатный план - используем месячный лимит
        monthly_count = user_data.get('monthly_usage_count', 0)
        if monthly_count >= 50:
            return False, monthly_count, 50
        limit = 50 - monthly_count  # Оставшийся месячный лимит
    
    return daily_count < limit, daily_count, limit

async def increment_usage(user_id: int) -> None:
    """Увеличивает счетчик использования"""
    today = datetime.now().date().isoformat()
    
    # Увеличиваем дневной и месячный счетчики
    await db.execute_query("""
        UPDATE users 
        SET daily_usage_count = daily_usage_count + 1,
            monthly_usage_count = monthly_usage_count + 1,
            last_usage_date = ?
        WHERE user_id = ?
    """, (today, user_id))

async def reset_monthly_usage(user_id: int) -> None:
    """Сбрасывает месячный счетчик использования"""
    await db.execute_query(
        "UPDATE users SET monthly_usage_count = 0 WHERE user_id = ?",
        (user_id,)
    )

# Декоратор для проверки подписки (для удобства)
def requires_subscription(check_channel: bool = False):
    """
    Декоратор для проверки подписки перед выполнением обработчика.
    
    Args:
        check_channel: Также проверять подписку на канал
    """
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            
            # Проверяем подписку
            has_subscription = await check_subscription(
                user_id,
                context.bot,
                channel=config.REQUIRED_CHANNEL if check_channel else None,
                check_paid=True,
                check_channel=check_channel
            )
            
            if not has_subscription:
                if update.callback_query:
                    await send_subscription_required(update.callback_query)
                else:
                    await send_subscription_required(update)
                return
            
            # Проверяем дневной лимит
            can_use, used, limit = await check_daily_limit(user_id)
            if not can_use:
                text = f"❌ Вы достигли лимита использования!\n\n"
                if limit == 50:
                    text += f"Использовано: {used}/50 вопросов в месяц\n"
                    text += "Оформите подписку для увеличения лимита!"
                else:
                    text += f"Использовано: {used}/{limit} вопросов сегодня\n"
                    text += "Попробуйте завтра или улучшите подписку!"
                
                keyboard = [[
                    InlineKeyboardButton("💳 Улучшить подписку", callback_data="subscribe_start")
                ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if update.callback_query:
                    await update.callback_query.answer(text, show_alert=True)
                else:
                    await update.message.reply_text(text, reply_markup=reply_markup)
                return
            
            # Увеличиваем счетчик использования
            await increment_usage(user_id)
            
            # Выполняем оригинальную функцию
            return await func(update, context)
        
        return wrapper
    return decorator