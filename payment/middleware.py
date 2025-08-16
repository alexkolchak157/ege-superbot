# payment/middleware.py
"""Middleware для проверки подписок и лимитов использования с поддержкой модулей."""
import logging
from typing import Optional, Dict, Set, Tuple
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackContext, ApplicationHandlerStop, ContextTypes

from core import db
from core import config

logger = logging.getLogger(__name__)


class SubscriptionMiddleware:
    """Middleware для проверки подписок с поддержкой модульной системы."""
    
    def __init__(
        self,
        free_commands: Optional[Set[str]] = None,
        free_patterns: Optional[Set[str]] = None,
        check_channel: bool = False
    ):
        self.free_commands = free_commands or {
            'start', 'help', 'subscribe', 'status', 
            'my_subscriptions', 'menu', 'cancel', 'support'
        }
        
        self.free_patterns = free_patterns or {
            'subscribe', 'subscribe_start', 'payment_', 'pay_',
            'to_main_menu', 'main_menu', 'check_subscription',
            'module_info_', 'back_to_main', 'my_subscriptions',
            'duration_', 'confirm_payment'
        }
        
        self.check_channel = check_channel
        self.channel = config.REQUIRED_CHANNEL if check_channel else None
        
        # Паттерны для определения модулей
        self.module_patterns = {
            'test_part': {
                'commands': ['test', 'test_stats'],
                'callbacks': ['choose_test_part', 'to_test_part_menu', 'test_'],
                'exclude': ['test_back_to_mode']
            },
            'task19': {
                'commands': ['task19'],
                'callbacks': ['choose_task19', 'to_task19_menu', 't19_', 'task19_'],
            },
            'task20': {
                'commands': ['task20'],
                'callbacks': ['choose_task20', 'to_task20_menu', 't20_', 'task20_'],
            },
            'task24': {
                'commands': ['task24'],
                'callbacks': ['choose_task24', 'to_task24_menu', 't24_'],
            },
            'task25': {
                'commands': ['task25'],
                'callbacks': ['choose_task25', 'to_task25_menu', 't25_', 'task25_'],
            }
        }
    
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
        """Обрабатывает обновление и проверяет подписку."""
        # Пропускаем если нет пользователя
        if not update.effective_user:
            return True
            
        user_id = update.effective_user.id
        
        # ИСПРАВЛЕНИЕ: Проверяем админов ДО проверки подписки
        from core import config
        admin_ids = []
        if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
            if isinstance(config.ADMIN_IDS, str):
                admin_ids = [int(id.strip()) for id in config.ADMIN_IDS.split(',') if id.strip()]
            elif isinstance(config.ADMIN_IDS, list):
                admin_ids = config.ADMIN_IDS
        
        # Если пользователь админ - пропускаем все проверки
        if user_id in admin_ids:
            logger.debug(f"Admin user {user_id} - skipping subscription check")
            return True
        
        # Проверяем, является ли это бесплатным действием
        if self._is_free_action(update, context):  # ✅ Передаем context
            logger.debug(f"Free action for user {user_id}")
            return True
        
        # Определяем модуль
        module_code = self._get_module_from_update(update)
        logger.debug(f"Detected module: {module_code}")
        
        # Получаем менеджер подписок
        subscription_manager = application.bot_data.get('subscription_manager')
        if not subscription_manager:
            logger.warning("SubscriptionManager not found in bot_data")
            return True
        
        # Проверяем доступ
        if module_code:
            logger.info(f"Checking access for user {user_id} to module {module_code}")
            
            # Проверка доступа к конкретному модулю
            has_access = await subscription_manager.check_module_access(user_id, module_code)
            
            logger.info(f"Access check result for user {user_id}, module {module_code}: {has_access}")
            
            if not has_access:
                logger.warning(f"Access denied for user {user_id} to module {module_code}")
                await self._send_module_subscription_required(update, context, module_code)
                raise ApplicationHandlerStop()
            else:
                logger.info(f"Access granted for user {user_id} to module {module_code}")
        else:
            # Проверка общей подписки
            subscription = await subscription_manager.check_active_subscription(user_id)
            if not subscription:
                # Проверяем подписку на канал
                if self.check_channel and self.channel:
                    is_member = await self._check_channel_membership(user_id, application.bot)
                    if not is_member:
                        await self._send_channel_required(update, context)
                        raise ApplicationHandlerStop()
                else:
                    await self._send_subscription_required(update, context)
                    raise ApplicationHandlerStop()
        
        # Проверяем лимиты использования
        can_use, used, limit = await self._check_usage_limit(user_id, subscription_manager)
        
        if not can_use:
            await self._send_limit_exceeded(update, context, used, limit)
            raise ApplicationHandlerStop()
        
        # Увеличиваем счетчик использования
        await self._increment_usage(user_id)
        
        # Сохраняем информацию в context для использования в обработчиках
        context.user_data['subscription_info'] = await subscription_manager.get_subscription_info(user_id)
        context.user_data['usage_info'] = {'used': used + 1, 'limit': limit}
        
        # Показываем оставшийся лимит для базовых подписок
        if update.callback_query and limit > 0 and limit != -1:
            remaining = limit - used - 1
            if remaining > 0 and remaining <= 10:
                await update.callback_query.answer(f"Осталось вопросов: {remaining}")
        
        return True
    
    def _is_free_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Проверяет, является ли действие бесплатным."""
        
        # Добавляем проверку для пользователей в процессе оплаты
        if context and context.user_data.get('in_payment_process'):
            return True
        # Проверяем команды
        if update.message and update.message.text:
            # Извлекаем команду без /
            text = update.message.text
            if text.startswith('/'):
                command = text.split()[0][1:].split('@')[0].lower()
                if command in self.free_commands:
                    return True
            else:
                # ВАЖНО: Проверяем, не является ли это вводом email
                # Простая проверка на наличие @ в тексте
                if '@' in text and '.' in text:
                    logger.debug(f"Detected possible email input: {text[:20]}...")
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
        
        subscription = await subscription_manager.check_active_subscription(user_id)
        return subscription is not None
    
    async def _check_channel_membership(self, user_id: int, bot) -> bool:
        """Проверяет подписку на канал"""
        if not self.channel:
            return True
            
        try:
            member = await bot.get_chat_member(self.channel, user_id)
            return member.status in ['member', 'administrator', 'creator']
        except Exception as e:
            logger.error(f"Error checking channel membership: {e}")
            return False
    
    async def _check_usage_limit(self, user_id: int, subscription_manager) -> Tuple[bool, int, int]:
        """
        Проверяет лимиты использования.
        
        Returns:
            (can_use, used_count, limit)
        """
        # Получаем данные пользователя
        user_data = await db.get_or_create_user_status(user_id)
        usage_count = user_data.get('monthly_usage_count', 0)
        
        # Проверяем подписку
        subscription = await subscription_manager.check_active_subscription(user_id)
        
        if subscription:
            # Для активной подписки нет лимитов
            return (True, usage_count, -1)
        
        # Для бесплатных пользователей - лимит
        FREE_LIMIT = 50  # или другой лимит
        
        if usage_count >= FREE_LIMIT:
            return (False, usage_count, FREE_LIMIT)
        
        return (True, usage_count, FREE_LIMIT)

    async def _increment_usage(self, user_id: int):
        """Увеличивает счетчик использования."""
        try:
            # Используем execute_with_retry из core.db
            await db.execute_with_retry(
                "UPDATE users SET monthly_usage_count = monthly_usage_count + 1 WHERE user_id = ?",
                (user_id,)
            )
        except Exception as e:
            logger.error(f"Error incrementing usage for user {user_id}: {e}")
    
    async def _send_subscription_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет сообщение о необходимости подписки"""
        text = "❌ Для доступа к этой функции необходима подписка!\n\n"
        text += "💎 Выберите подходящий план:\n"
        
        # Импортируем конфигурацию для получения актуальных цен
        from .config import SUBSCRIPTION_MODE, MODULE_PLANS, LEGACY_SUBSCRIPTION_PLANS
        
        if SUBSCRIPTION_MODE == 'modular':
            # Модульная система - показываем модули
            text += "📦 <b>Модульная система подписок:</b>\n"
            text += "• Тестовая часть - 149₽/мес\n"
            text += "• Задания 19, 20, 25 - по 199₽/мес\n"
            text += "• Задание 24 (премиум) - 399₽/мес\n"
            text += "• Пакет 'Вторая часть' - 499₽/мес\n"
            text += "• Полный доступ - 999₽/мес\n"
        else:
            # Старая система
            plans = LEGACY_SUBSCRIPTION_PLANS
            text += f"• {plans['basic_month']['name']} ({plans['basic_month']['price_rub']}₽/мес) - 100 вопросов в день\n"
            text += f"• {plans['pro_month']['name']} ({plans['pro_month']['price_rub']}₽/мес) - неограниченно\n"
            text += f"• {plans['pro_ege']['name']} ({plans['pro_ege']['price_rub']}₽) - неограниченно до ЕГЭ 2025\n"
        
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
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            except:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        elif update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
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
            InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe"),
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
    
    async def _send_channel_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет сообщение о необходимости подписки на канал"""
        text = f"❌ Для использования бота необходима подписка на канал {self.channel}\n\n"
        text += "После подписки нажмите кнопку 'Проверить подписку'"
        
        keyboard = [
            [InlineKeyboardButton("📣 Подписаться на канал", url=f"https://t.me/{self.channel[1:]}")],
            [InlineKeyboardButton("🔄 Проверить подписку", callback_data="check_subscription")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.answer("Требуется подписка на канал!", show_alert=True)
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
    """Настраивает middleware для проверки подписок."""
    default_free_patterns = {
        # Базовые паттерны
        'main_menu', 'to_main_menu', 'start_', 'help_',
        'subscribe', 'pay_', 'confirm_', 'cancel_',
        'module_info_', 'duration_', 'back_to_',
        'check_subscription', 'support_', 'settings_',
        
        # Паттерны для подписки
        'my_subscription', 'subscribe_start',
        'my_subscriptions',  # ДОБАВИТЬ этот паттерн!
        
        # Паттерны для выбора модулей
        'toggle_', 'info_', 'proceed_with_modules',
        'pay_individual_modules', 'pay_package_',
        'pay_trial', 'pay_full',
        
        # Паттерны для навигации в подписке
        'back_to_module_selection', 'back_to_main',
        'back_to_plans', 'back_to_modules',
        
        # Админские паттерны
        'admin_', 'broadcast_', 'stats_', 'test_',
        'add_user_', 'remove_user_', 'list_users_',
        'refresh_'
    }
    # Расширяем список бесплатных команд, включая админские
    default_free_commands = {
        # Базовые команды
        'start', 'help', 'subscribe', 'status', 
        'my_subscriptions', 'menu', 'cancel', 'support',
        
        # ВАЖНО: Админские команды должны быть доступны без подписки!
        'grant_subscription', 'activate_payment', 'check_webhook',
        'list_subscriptions', 'check_user_subscription', 'revoke',
        'payment_stats', 'check_admin', 'grant', 'revoke_subscription'
    }
    
    # Объединяем с пользовательскими командами если есть
    if free_commands:
        default_free_commands.update(free_commands)
    
    middleware = SubscriptionMiddleware(
        free_commands=default_free_commands,
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
    
    logger.info("Subscription middleware установлен с админскими командами в whitelist")