# payment/subscription_middleware.py - Централизованная проверка подписок для python-telegram-bot v20

import logging
from typing import Optional, Set, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, Application, TypeHandler, 
    ApplicationHandlerStop, CallbackContext
)
from datetime import datetime

from core import config, db
from payment.subscription_manager import SubscriptionManager

logger = logging.getLogger(__name__)

class SubscriptionMiddleware:
    """Middleware для автоматической проверки подписок"""
    
    def __init__(
        self,
        free_commands: Optional[Set[str]] = None,
        free_patterns: Optional[Set[str]] = None,
        check_channel: bool = False,
        channel: Optional[str] = None
    ):
        """
        Args:
            free_commands: Команды, доступные без подписки
            free_patterns: Паттерны callback_data, доступные без подписки
            check_channel: Также проверять подписку на канал
            channel: Канал для проверки
        """
        # Команды, доступные всем пользователям
        self.free_commands = free_commands or {
            'start', 'help', 'subscribe', 'subscription', 
            'grant_subscription', 'revoke_subscription', 'payment_stats'
        }
        
        # Паттерны callback_data, доступные без подписки
        self.free_patterns = free_patterns or {
            'main_menu', 'subscribe_', 'plan_', 'check_payment_',
            'check_subscription', 'help_', 'lang_', 'settings_'
        }
        
        self.check_channel = check_channel
        self.channel = channel or config.REQUIRED_CHANNEL
        self.subscription_manager = SubscriptionManager()
        
    async def process_update(
        self,
        update: Update,
        application: Application,
        check_update: bool,
        context: CallbackContext
    ) -> bool:
        """
        Обрабатывает обновление и проверяет подписку.
        
        Returns:
            True - есть подписка, продолжить обработку
            False - нет подписки, обработка остановлена
        """
        # Пропускаем обновления без пользователя
        if not update.effective_user:
            return True
            
        user_id = update.effective_user.id
        
        # Определяем, нужна ли проверка
        if self._is_free_action(update):
            return True
        
        # Обеспечиваем наличие пользователя в БД
        await db.ensure_user(user_id)
        
        # Проверяем подписку
        has_subscription = await self._check_subscription(user_id, application.bot)
        
        if not has_subscription:
            await self._send_subscription_required(update, context)
            raise ApplicationHandlerStop()
        
        # Проверяем лимиты использования
        can_use, used, limit = await self._check_limits(user_id)
        
        if not can_use:
            await self._send_limit_exceeded(update, context, used, limit)
            raise ApplicationHandlerStop()
        
        # Увеличиваем счетчик использования
        await self._increment_usage(user_id)
        
        # Добавляем информацию о подписке в context
        context.user_data['subscription_info'] = await self.subscription_manager.get_subscription_info(user_id)
        context.user_data['usage_info'] = {'used': used + 1, 'limit': limit}
        
        # Показываем оставшийся лимит для базовых подписок
        if update.callback_query and limit > 0 and limit != -1:
            remaining = limit - used - 1
            if remaining > 0 and remaining <= 10:
                await update.callback_query.answer(f"Осталось вопросов: {remaining}")
        
        return True
    
    def _is_free_action(self, update: Update) -> bool:
        """Проверяет, является ли действие бесплатным"""
        # Проверяем команды
        if update.message and update.message.text:
            # Извлекаем команду без /
            text = update.message.text
            if text.startswith('/'):
                command = text.split()[0][1:].split('@')[0].lower()
                if command in self.free_commands:
                    return True
                    
        # Проверяем callback_query
        elif update.callback_query and update.callback_query.data:
            callback_data = update.callback_query.data
            # Проверяем паттерны
            for pattern in self.free_patterns:
                if callback_data.startswith(pattern):
                    return True
        
        # Проверяем inline_query (всегда бесплатно для preview)
        elif update.inline_query:
            return True
            
        return False
    
    async def _check_subscription(self, user_id: int, bot) -> bool:
        """Проверяет наличие активной подписки"""
        # Проверяем платную подписку
        subscription_info = await self.subscription_manager.get_subscription_info(user_id)
        if subscription_info['is_active']:
            return True
        
        # Опционально проверяем канал
        if self.check_channel and self.channel:
            try:
                chat_member = await bot.get_chat_member(self.channel, user_id)
                if chat_member.status in ['member', 'administrator', 'creator']:
                    return True
            except Exception as e:
                logger.error(f"Ошибка при проверке подписки на канал: {e}")
        
        return False
    
    async def _check_limits(self, user_id: int) -> tuple[bool, int, int]:
        """Проверяет лимиты использования"""
        subscription_info = await self.subscription_manager.get_subscription_info(user_id)
        
        # Безлимитные планы
        if subscription_info['is_active'] and subscription_info['plan_id'] in ['pro_month', 'pro_ege']:
            return True, 0, -1
        
        # Получаем данные пользователя
        today = datetime.now().date().isoformat()
        user_data = await db.get_user(user_id)
        
        if not user_data:
            return False, 0, 0
        
        # Сбрасываем дневной счетчик при необходимости
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
            limit = 100  # Базовый план
        else:
            # Бесплатный план - месячный лимит
            monthly_count = user_data.get('monthly_usage_count', 0)
            if monthly_count >= 50:
                return False, monthly_count, 50
            limit = 50 - monthly_count
        
        return daily_count < limit, daily_count, limit
    
    async def _increment_usage(self, user_id: int) -> None:
        """Увеличивает счетчики использования"""
        today = datetime.now().date().isoformat()
        await db.execute_query("""
            UPDATE users 
            SET daily_usage_count = daily_usage_count + 1,
                monthly_usage_count = monthly_usage_count + 1,
                last_usage_date = ?
            WHERE user_id = ?
        """, (today, user_id))
    
    async def _send_subscription_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет сообщение о необходимости подписки"""
        text = "❌ Для доступа к этой функции необходима подписка!\n\n"
        text += "💎 Выберите подходящий план:\n"
        text += "• Базовый (299₽/мес) - 100 вопросов в день\n"
        text += "• Pro (599₽/мес) - неограниченно\n"
        text += "• Pro до ЕГЭ (1999₽) - неограниченно до ЕГЭ 2025\n"
        
        keyboard = [
            [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe_start")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ]
        
        if self.channel and self.check_channel:
            text += f"\n📣 Или подпишитесь на канал {self.channel} для бесплатного доступа"
            keyboard.insert(1, [
                InlineKeyboardButton("📣 Подписаться на канал", url=f"https://t.me/{self.channel[1:]}")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.answer("Требуется подписка!", show_alert=True)
            try:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
            except:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
        elif update.message:
            await update.message.reply_text(text, reply_markup=reply_markup)
    
    async def _send_limit_exceeded(self, update: Update, context: ContextTypes.DEFAULT_TYPE, used: int, limit: int):
        """Отправляет сообщение о превышении лимита"""
        if limit == 50:
            text = f"❌ Вы достигли месячного лимита!\n\n"
            text += f"Использовано: {used}/50 вопросов в месяц\n"
            text += "Оформите подписку для увеличения лимита!"
        else:
            text = f"❌ Вы достигли дневного лимита!\n\n"
            text += f"Использовано: {used}/{limit} вопросов сегодня\n"
            text += "Попробуйте завтра или улучшите подписку!"
        
        keyboard = [
            [InlineKeyboardButton("💳 Улучшить подписку", callback_data="subscribe_start")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.answer("Лимит исчерпан!", show_alert=True)
            try:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
            except:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
        elif update.message:
            await update.message.reply_text(text, reply_markup=reply_markup)


def setup_subscription_middleware(
    application: Application,
    free_commands: Optional[Set[str]] = None,
    free_patterns: Optional[Set[str]] = None,
    check_channel: bool = False
) -> None:
    """
    Настраивает middleware для проверки подписок.
    Должен вызываться в post_init после инициализации БД.
    """
    middleware = SubscriptionMiddleware(
        free_commands=free_commands,
        free_patterns=free_patterns,
        check_channel=check_channel
    )
    
    # Сохраняем middleware в application для доступа из других мест
    application.bot_data['subscription_middleware'] = middleware
    
    # Создаем обработчик, который будет проверять все обновления
    async def check_subscription_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик для проверки подписки перед другими обработчиками"""
        try:
            await middleware.process_update(update, application, True, context)
        except ApplicationHandlerStop:
            # Останавливаем дальнейшую обработку
            raise
    
    # Добавляем обработчик с группой -100 (выполняется первым)
    # TypeHandler обрабатывает ВСЕ типы обновлений
    from telegram.ext import TypeHandler
    application.add_handler(
        TypeHandler(Update, check_subscription_handler),
        group=-100
    )
    
    logger.info("Subscription middleware установлен")