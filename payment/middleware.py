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
# НЕ импортируем SubscriptionManager в начале файла!

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
        self.module_patterns = {
            'task19': {
                'commands': ['task19'],  # Команды модуля
                'callbacks': ['t19_', 'task19'],  # Префиксы callback и точные значения
                'exclude': []  # Исключения (необязательно)
            },
            'task20': {
                'commands': ['task20'],
                'callbacks': ['t20_', 'task20'],
                'exclude': []
            },
            'task24': {
                'commands': ['task24'],
                'callbacks': ['t24_', 'task24'],
                'exclude': []
            },
            'task25': {
                'commands': ['task25'],
                'callbacks': ['t25_', 'task25'],
                'exclude': []
            },
            'test_part': {
                'commands': ['quiz', 'test'],
                'callbacks': ['test_', 'quiz_', 'test_part'],
                'exclude': []
            }
        }
        self.check_channel = check_channel
        self.channel = channel or config.REQUIRED_CHANNEL
        # НЕ создаем subscription_manager здесь!
    
    def _get_module_from_update(self, update: Update) -> Optional[str]:
        """Определяет модуль по update."""
        # Для команд
        if update.message and update.message.text and update.message.text.startswith('/'):
            command = update.message.text.split()[0][1:].split('@')[0].lower()
            
            for module_code, patterns in self.module_patterns.items():
                if command in patterns['commands']:
                    logger.debug(f"Command {command} matched module {module_code}")
                    return module_code
        
        # Для callback_query
        elif update.callback_query and update.callback_query.data:
            callback_data = update.callback_query.data
            
            for module_code, patterns in self.module_patterns.items():
                # Проверяем исключения
                if any(callback_data == exc or callback_data.startswith(exc) 
                       for exc in patterns.get('exclude', [])):
                    continue
                
                # Проверяем паттерны
                for pattern in patterns['callbacks']:
                    # Если паттерн заканчивается на _, это префикс
                    if pattern.endswith('_') and callback_data.startswith(pattern):
                        logger.debug(f"Callback {callback_data} matched module {module_code} by prefix {pattern}")
                        return module_code
                    # Иначе проверяем точное совпадение
                    elif callback_data == pattern:
                        logger.debug(f"Callback {callback_data} matched module {module_code} exactly")
                        return module_code
        
        return None        
    
    async def process_update(
        self,
        update: Update,
        application: Application,
        check_update: bool,
        context: CallbackContext
    ) -> bool:
        """Обрабатывает обновление и проверяет подписку.
        
        Returns:
            True - есть подписка, продолжить обработку
            False - нет подписки, обработка остановлена
        """
        # Пропускаем обновления без пользователя
        if not update.effective_user:
            return True
            
        user_id = update.effective_user.id
        
        # НОВОЕ: Проверяем, является ли пользователь админом
        from core import config
        admin_ids = []
        if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
            if isinstance(config.ADMIN_IDS, str):
                admin_ids = [int(id.strip()) for id in config.ADMIN_IDS.split(',') if id.strip()]
            elif isinstance(config.ADMIN_IDS, list):
                admin_ids = config.ADMIN_IDS
        
        # Если пользователь админ - пропускаем все проверки
        if user_id in admin_ids:
            logger.info(f"Admin {user_id} bypassing subscription check")
            # Добавляем флаг админа в context для использования в других местах
            context.user_data['is_admin'] = True
            return True
        
        # Определяем, нужна ли проверка
        if self._is_free_action(update):
            return True
            
        from core import config
        if hasattr(config, 'SUBSCRIPTION_MODE') and config.SUBSCRIPTION_MODE == 'modular':
            module_code = self._get_module_from_update(update)
            
            if module_code:
                logger.info(f"Checking module access for user {user_id} to module {module_code}")
                
                # Получаем subscription_manager
                subscription_manager = application.bot_data.get('subscription_manager')
                if not subscription_manager:
                    from .subscription_manager import SubscriptionManager
                    subscription_manager = SubscriptionManager()
                
                # Проверяем доступ к модулю
                has_access = await subscription_manager.check_module_access(user_id, module_code)
                
                if not has_access:
                    logger.warning(f"User {user_id} has no access to module {module_code}")
                    await self._send_module_subscription_required(update, context, module_code)
                    raise ApplicationHandlerStop()
                else:
                    logger.info(f"User {user_id} has access to module {module_code}")
                    # Сохраняем информацию о модуле в контексте
                    context.user_data['current_module'] = module_code
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
        from payment.subscription_manager import SubscriptionManager
        subscription_manager = SubscriptionManager()
        context.user_data['subscription_info'] = await subscription_manager.get_subscription_info(user_id)
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
        # Импортируем только когда нужно
        from payment.subscription_manager import SubscriptionManager
        
        subscription_manager = SubscriptionManager()
        
        # Проверяем платную подписку
        subscription_info = await subscription_manager.get_subscription_info(user_id)
        if subscription_info and subscription_info.get('is_active'):
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
        # Импортируем только когда нужно
        from payment.subscription_manager import SubscriptionManager
        
        subscription_manager = SubscriptionManager()
        subscription_info = await subscription_manager.get_subscription_info(user_id)
        
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

    async def _send_module_subscription_required(
        self, 
        update: Update, 
        context: ContextTypes.DEFAULT_TYPE,
        module_code: str
    ):
        """Отправляет сообщение о необходимости подписки на модуль."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.constants import ParseMode
        
        module_names = {
            'task19': 'Задание 19 - Примеры социальных объектов',
            'task20': 'Задание 20 - Текст с пропусками',
            'task24': 'Задание 24 - План текста (премиум)',
            'task25': 'Задание 25 - Понятия и термины',
            'test_part': 'Тестовая часть ЕГЭ'
        }
        
        module_name = module_names.get(module_code, f'Модуль {module_code}')
        
        text = f"""🔒 <b>Требуется подписка на модуль!</b>

    Для доступа к <b>{module_name}</b> необходима активная подписка на этот модуль.

    💡 С модульной системой вы платите только за те задания, которые вам нужны!

    Используйте команду /subscribe для просмотра доступных модулей и оформления подписки."""
        
        keyboard = [[
            InlineKeyboardButton("💳 Оформить подписку", callback_data="to_subscription"),
            InlineKeyboardButton("ℹ️ Подробнее", callback_data=f"module_info_{module_code}")
        ]]
        
        if update.callback_query:
            await update.callback_query.answer(
                f"Требуется подписка на {module_name.split(' - ')[0]}!", 
                show_alert=True
            )
            # Отправляем новое сообщение вместо редактирования
            await update.callback_query.message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        elif update.message:
            await update.message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )

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