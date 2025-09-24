# payment/middleware.py - ПОЛНАЯ версия с оптимизациями
"""Middleware для проверки подписок и лимитов использования с поддержкой модулей."""
import logging
from typing import Optional, Dict, Set, Tuple
from datetime import datetime, timezone
from functools import lru_cache

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackContext, ApplicationHandlerStop, ContextTypes

from core import db
from core import config

logger = logging.getLogger(__name__)


class SubscriptionMiddleware:
    """Оптимизированный middleware для проверки подписок с поддержкой модульной системы."""
    
    def __init__(
        self,
        free_commands: Optional[Set[str]] = None,
        free_patterns: Optional[Set[str]] = None,
        check_channel: bool = False
    ):
        """
        Инициализация middleware.
        
        Args:
            free_commands: Команды, доступные без подписки
            free_patterns: Паттерны callback, доступные без подписки
            check_channel: Проверять ли подписку на канал
        """
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
        
        # Паттерны для определения модулей (оптимизированы)
        self.module_patterns = {
            'test_part': {
                'commands': ['test', 'test_stats', 'quiz', 'mistakes', 'score'],
                'callbacks': [
                    'choose_test_part', 'to_test_part_menu', 'test_',
                    'initial:', 'block:', 'topic:', 'exam_num:', 
                    'next_random', 'next_topic', 'skip_question',
                    'mode:', 'exam_', 'mistake_', 'test_part_'
                ],
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
        
        # Кэш для ускорения проверок
        self._module_cache = {}  # {update_key: module_code}
        self._access_cache = {}  # {(user_id, module): has_access}
        self._cache_ttl = 60
        self._cache_timestamps = {}
    
    @lru_cache(maxsize=256)
    def _get_update_key(self, update: Update) -> Optional[str]:
        """Получает уникальный ключ из update для кэширования."""
        if update.message and update.message.text:
            return f"msg:{update.message.text}"
        elif update.callback_query and update.callback_query.data:
            return f"cb:{update.callback_query.data}"
        return None
    
    def _get_module_from_update(self, update: Update) -> Optional[str]:
        """
        Определяет модуль по update с использованием кэша.
        
        Args:
            update: Telegram update
            
        Returns:
            Код модуля или None
        """
        # Пытаемся получить из кэша
        update_key = self._get_update_key(update)
        if update_key and update_key in self._module_cache:
            return self._module_cache[update_key]
        
        module_code = None
        
        # Для команд
        if update.message and update.message.text and update.message.text.startswith('/'):
            command = update.message.text.split()[0][1:].split('@')[0].lower()
            
            for module, patterns in self.module_patterns.items():
                if command in patterns['commands']:
                    module_code = module
                    break
        
        # Для callback_query
        elif update.callback_query and update.callback_query.data:
            callback_data = update.callback_query.data
            
            # Прямое соответствие для кнопок главного меню
            direct_mapping = {
                'choose_test_part': 'test_part',
                'choose_task19': 'task19',
                'choose_task20': 'task20',
                'choose_task24': 'task24',
                'choose_task25': 'task25',
            }
            
            if callback_data in direct_mapping:
                module_code = direct_mapping[callback_data]
            else:
                # Проверяем паттерны
                for module, patterns in self.module_patterns.items():
                    # Проверяем исключения
                    if any(callback_data == exc or callback_data.startswith(exc) 
                           for exc in patterns.get('exclude', [])):
                        continue
                    
                    # Проверяем паттерны
                    for pattern in patterns['callbacks']:
                        if pattern.endswith('_') and callback_data.startswith(pattern):
                            module_code = module
                            break
                        elif callback_data == pattern:
                            module_code = module
                            break
                    
                    if module_code:
                        break
        
        # Сохраняем в кэш
        if update_key and module_code:
            self._module_cache[update_key] = module_code
        
        return module_code
    
    async def process_update(
        self,
        update: Update,
        application: Application,
        check_update: bool,
        context: CallbackContext
    ) -> bool:
        """
        Основной метод обработки обновления и проверки подписки.
        
        Args:
            update: Telegram update
            application: Приложение
            check_update: Проверять ли обновление
            context: Контекст
            
        Returns:
            True если доступ разрешен
            
        Raises:
            ApplicationHandlerStop: Если доступ запрещен
        """
        # КРИТИЧЕСКИ ВАЖНО: /start всегда работает
        if update.message and update.message.text:
            text = update.message.text.strip()
            if text.startswith('/start'):
                logger.debug(f"Command /start detected - bypassing ALL subscription checks")
                return True
        
        # Пропускаем если нет пользователя
        if not update.effective_user:
            return True
        
        user_id = update.effective_user.id
        
        # Проверяем админов
        admin_ids = self._get_admin_ids()
        if user_id in admin_ids:
            logger.debug(f"Admin user {user_id} - skipping subscription check")
            return True
        
        # Проверяем бесплатные действия
        if self._is_free_action(update, context):
            logger.debug(f"Free action detected for user {user_id}")
            return True
        
        # Определяем модуль
        module_code = self._get_module_from_update(update)
        
        # Если модуль не определен, берем из контекста
        if not module_code and context:
            module_code = context.user_data.get('active_module')
        
        # Сохраняем активный модуль в контексте
        if module_code and context:
            context.user_data['active_module'] = module_code
        
        # Если модуль не определен - пропускаем
        if not module_code:
            logger.debug(f"No module detected for user {user_id}")
            return True
        
        # Бесплатные модули (test_part) доступны всем
        from .config import FREE_MODULES
        if module_code in FREE_MODULES:
            logger.info(f"Free module {module_code} accessed by user {user_id}")
            return True
        
        # Получаем менеджер подписок
        subscription_manager = application.bot_data.get('subscription_manager')
        if not subscription_manager:
            logger.warning("SubscriptionManager not found in bot_data")
            return True
        
        # Проверяем доступ к модулю (с кэшем)
        cache_key = (user_id, module_code)
        if cache_key in self._access_cache:
            has_access = self._access_cache[cache_key]
        else:
            has_access = await subscription_manager.check_module_access(user_id, module_code)
            self._access_cache[cache_key] = has_access
        
        if not has_access:
            logger.info(f"Access denied for user {user_id} to module {module_code}")
            await self._send_module_subscription_required(update, context, module_code)
            raise ApplicationHandlerStop()
        
        # Проверяем лимиты использования
        can_use, used, limit = await self._check_usage_limit(user_id, subscription_manager)
        
        if not can_use:
            await self._send_limit_exceeded(update, context, used, limit)
            raise ApplicationHandlerStop()
        
        # Увеличиваем счетчик использования для платных модулей
        if module_code not in FREE_MODULES:
            await self._increment_usage(user_id)
        
        # Сохраняем информацию в context
        if context:
            context.user_data['subscription_info'] = await subscription_manager.get_subscription_info(user_id)
            context.user_data['usage_info'] = {'used': used + 1, 'limit': limit}
        
        # Показываем оставшийся лимит при необходимости
        if update.callback_query and limit > 0 and limit != -1:
            remaining = limit - used - 1
            if remaining > 0 and remaining <= 10 and module_code not in FREE_MODULES:
                await update.callback_query.answer(f"Осталось вопросов: {remaining}")
        
        logger.info(f"Access granted for user {user_id} to module {module_code}")
        return True
    
    def _is_free_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """
        Проверяет, является ли действие бесплатным.
        
        Args:
            update: Telegram update
            context: Контекст
            
        Returns:
            True если действие бесплатное
        """
        # Проверка команд
        if update.message and update.message.text:
            text = update.message.text.strip()
            
            if text.startswith('/'):
                command = text.split()[0][1:].split('@')[0].lower()
                if command in self.free_commands:
                    return True
        
        # Проверка callback
        if update.callback_query and update.callback_query.data:
            callback_data = update.callback_query.data
            
            # Проверяем по паттернам
            for pattern in self.free_patterns:
                if pattern.endswith('_'):
                    if callback_data.startswith(pattern):
                        return True
                else:
                    if callback_data == pattern:
                        return True
        
        # Проверка состояния тестовой части в контексте
        if context and context.user_data.get('test_state') in ['ANSWERING', 'EXAM_MODE', 'CHOOSING_MODE']:
            return True
        
        return False
    
    def _get_admin_ids(self) -> list:
        """Получает список ID администраторов."""
        admin_ids = []
        if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
            if isinstance(config.ADMIN_IDS, str):
                admin_ids = [int(id.strip()) for id in config.ADMIN_IDS.split(',') if id.strip()]
            elif isinstance(config.ADMIN_IDS, list):
                admin_ids = config.ADMIN_IDS
        return admin_ids
    
    async def _check_channel_membership(self, user_id: int, bot) -> bool:
        """
        Проверяет подписку на канал.
        
        Args:
            user_id: ID пользователя
            bot: Экземпляр бота
            
        Returns:
            True если подписан
        """
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
        
        Args:
            user_id: ID пользователя
            subscription_manager: Менеджер подписок
            
        Returns:
            (can_use, used_count, limit)
        """
        # Получаем данные пользователя
        user_data = await db.get_or_create_user_status(user_id)
        usage_count = user_data.get('monthly_usage_count', 0)
        
        # Проверяем подписку
        subscription = await subscription_manager.check_active_subscription(user_id)
        
        if subscription:
            # Для активной подписки нет лимитов (или большие лимиты)
            plan_id = subscription.get('plan_id')
            
            # Pro планы без лимитов
            if plan_id in ['pro_month', 'pro_ege', 'package_full']:
                return (True, usage_count, -1)  # -1 = безлимит
            
            # Базовые планы с лимитами
            elif plan_id in ['basic_month', 'package_second']:
                limit = 100  # вопросов в день
                # Проверяем дневной лимит
                today_count = user_data.get('daily_usage_count', 0)
                if today_count >= limit:
                    return (False, today_count, limit)
                return (True, today_count, limit)
        
        # Для бесплатных пользователей - месячный лимит
        FREE_LIMIT = 50
        
        if usage_count >= FREE_LIMIT:
            return (False, usage_count, FREE_LIMIT)
        
        return (True, usage_count, FREE_LIMIT)
    
    async def _increment_usage(self, user_id: int):
        """
        Увеличивает счетчик использования.
        
        Args:
            user_id: ID пользователя
        """
        try:
            today = datetime.now().date().isoformat()
            
            # Обновляем оба счетчика
            await db.execute_with_retry(
                """
                UPDATE users 
                SET monthly_usage_count = monthly_usage_count + 1,
                    daily_usage_count = CASE 
                        WHEN last_usage_date = ? THEN daily_usage_count + 1 
                        ELSE 1 
                    END,
                    last_usage_date = ?
                WHERE user_id = ?
                """,
                (today, today, user_id)
            )
        except Exception as e:
            logger.error(f"Error incrementing usage for user {user_id}: {e}")
    
    async def _send_subscription_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет общее сообщение о необходимости подписки."""
        from .config import SUBSCRIPTION_MODE, MODULE_PLANS, LEGACY_SUBSCRIPTION_PLANS
        
        text = "❌ <b>Для доступа к этой функции необходима подписка!</b>\n\n"
        
        if SUBSCRIPTION_MODE == 'modular':
            text += "💎 <b>Доступные пакеты:</b>\n\n"
            text += "🎁 Пробный период — 1₽ за 7 дней\n"
            text += "📚 Пакет «Вторая часть» — 499₽/мес\n"
            text += "👑 Полный доступ — 799₽/мес\n"
        else:
            plans = LEGACY_SUBSCRIPTION_PLANS
            text += f"• {plans['basic_month']['name']} — {plans['basic_month']['price_rub']}₽/мес\n"
            text += f"• {plans['pro_month']['name']} — {plans['pro_month']['price_rub']}₽/мес\n"
        
        keyboard = [
            [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe_start")],
            [InlineKeyboardButton("⬅️ Главное меню", callback_data="to_main_menu")]
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
    
    async def _send_module_subscription_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE, module_code: str):
        """
        Отправляет сообщение о необходимости подписки на конкретный модуль.
        
        Args:
            update: Telegram update
            context: Контекст
            module_code: Код модуля
        """
        # Названия модулей
        module_names = {
            'test_part': '📝 Тестовая часть',
            'task19': '🎯 Задание 19',
            'task20': '📖 Задание 20',
            'task24': '📋 Задание 24',
            'task25': '✍️ Задание 25'
        }
        
        module_name = module_names.get(module_code, module_code)
        
        # Импортируем конфигурацию
        from .config import MODULE_PLANS, get_module_price
        
        # Находим подходящие пакеты
        suitable_packages = []
        for plan_id, plan in MODULE_PLANS.items():
            if module_code in plan.get('modules', []):
                suitable_packages.append((plan_id, plan))
        
        # Формируем сообщение
        text = f"🔒 <b>Модуль «{module_name}» требует подписку</b>\n\n"
        
        # Сортируем пакеты по цене
        suitable_packages.sort(key=lambda x: x[1]['price_rub'])
        
        if suitable_packages:
            text += "<b>Доступен в пакетах:</b>\n\n"
            for plan_id, plan in suitable_packages[:3]:  # Показываем топ-3 варианта
                text += f"• {plan['name']} — {plan['price_rub']}₽\n"
        
        # Цена отдельного модуля
        module_price = get_module_price(module_code)
        if module_price > 0:
            text += f"\n<b>Или отдельно:</b> {module_price}₽/мес"
        
        text += "\n\n💡 <i>Совет: Попробуйте пробный период за 1₽</i>"
        
        # Кнопки
        buttons = []
        
        # Пробный период всегда первый
        buttons.append([InlineKeyboardButton("🎁 Попробовать за 1₽", callback_data="pay_trial")])
        
        # Добавляем подходящие пакеты
        for plan_id, plan in suitable_packages[:2]:
            if plan['type'] != 'trial':
                button_text = f"{plan['name']}"
                buttons.append([InlineKeyboardButton(button_text, callback_data=f"pay_{plan_id}")])
        
        # Кнопка возврата
        buttons.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="to_main_menu")])
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        # Отправляем сообщение
        if update.callback_query:
            await update.callback_query.answer(f"❌ {module_name} требует подписку", show_alert=True)
            await update.callback_query.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
    
    async def _send_limit_exceeded(self, update: Update, context: ContextTypes.DEFAULT_TYPE, used: int, limit: int):
        """
        Отправляет сообщение о превышении лимита.
        
        Args:
            update: Telegram update  
            context: Контекст
            used: Использовано
            limit: Лимит
        """
        if limit == 50:
            text = f"❌ <b>Вы достигли месячного лимита!</b>\n\n"
            text += f"Использовано: {used}/50 вопросов в месяц\n\n"
            text += "Оформите подписку для увеличения лимита!"
        else:
            text = f"❌ <b>Вы достигли дневного лимита!</b>\n\n"
            text += f"Использовано: {used}/{limit} вопросов сегодня\n\n"
            text += "Попробуйте завтра или улучшите подписку!"
        
        keyboard = [
            [InlineKeyboardButton("💳 Улучшить подписку", callback_data="subscribe_start")],
            [InlineKeyboardButton("⬅️ Главное меню", callback_data="to_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.answer("Лимит исчерпан!", show_alert=True)
            try:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            except:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        elif update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    async def _send_channel_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет сообщение о необходимости подписки на канал."""
        text = f"❌ <b>Для использования бота необходима подписка на канал {self.channel}</b>\n\n"
        text += "После подписки нажмите кнопку «Проверить подписку»"
        
        keyboard = [
            [InlineKeyboardButton("📣 Подписаться на канал", url=f"https://t.me/{self.channel[1:]}")],
            [InlineKeyboardButton("🔄 Проверить подписку", callback_data="check_subscription")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.answer("Требуется подписка на канал!", show_alert=True)
            try:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            except:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        elif update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    def clear_cache(self, user_id: Optional[int] = None):
        """
        Очищает кэш.
        
        Args:
            user_id: ID пользователя (если None - очищает весь кэш)
        """
        if user_id:
            # Очищаем кэш для конкретного пользователя
            self._access_cache = {
                k: v for k, v in self._access_cache.items()
                if k[0] != user_id
            }
        else:
            # Полная очистка кэшей
            self._module_cache.clear()
            self._access_cache.clear()


def setup_subscription_middleware(
    application: Application,
    free_commands: Optional[Set[str]] = None,
    free_patterns: Optional[Set[str]] = None,
    check_channel: bool = False
) -> SubscriptionMiddleware:
    """
    Настраивает middleware для проверки подписок.
    
    Args:
        application: Приложение Telegram
        free_commands: Бесплатные команды
        free_patterns: Бесплатные паттерны
        check_channel: Проверять ли канал
        
    Returns:
        Экземпляр middleware
    """
    # Дефолтные бесплатные паттерны
    default_free_patterns = {
        # Базовые паттерны
        'main_menu', 'to_main_menu', 'start_', 'help_',
        'subscribe', 'pay_', 'confirm_', 'cancel_',
        'module_info_', 'duration_', 'back_to_',
        'check_subscription', 'support_', 'settings_',
        
        # Паттерны для подписки
        'my_subscription', 'subscribe_start', 'my_subscriptions',
        
        # Паттерны для выбора модулей
        'toggle_', 'info_', 'proceed_with_modules',
        'pay_individual_modules', 'pay_package_',
        'pay_trial', 'pay_full',
        
        # Паттерны для навигации
        'back_to_module_selection', 'back_to_main',
        'back_to_plans', 'back_to_modules',
        
        # Админские паттерны
        'admin_', 'broadcast_', 'stats_', 'test_',
        'add_user_', 'remove_user_', 'list_users_',
        'refresh_'
    }
    
    # Дефолтные бесплатные команды
    default_free_commands = {
        # Базовые команды
        'start', 'help', 'subscribe', 'status', 
        'my_subscriptions', 'menu', 'cancel', 'support',
        
        # Админские команды
        'grant_subscription', 'activate_payment', 'check_webhook',
        'list_subscriptions', 'check_user_subscription', 'revoke',
        'payment_stats', 'check_admin', 'grant', 'revoke_subscription'
    }
    
    # Объединяем с пользовательскими
    if free_commands:
        default_free_commands.update(free_commands)
    if free_patterns:
        default_free_patterns.update(free_patterns)
    
    # Создаем middleware
    middleware = SubscriptionMiddleware(
        free_commands=default_free_commands,
        free_patterns=default_free_patterns,
        check_channel=check_channel
    )
    
    # Сохраняем в bot_data
    application.bot_data['subscription_middleware'] = middleware
    
    # Создаем обработчик
    async def check_subscription_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик для проверки подписки."""
        try:
            await middleware.process_update(update, application, True, context)
        except ApplicationHandlerStop:
            raise
    
    # Регистрируем с высоким приоритетом
    from telegram.ext import TypeHandler
    application.add_handler(
        TypeHandler(Update, check_subscription_handler),
        group=-100  # Выполняется первым
    )
    
    logger.info("Subscription middleware установлен с полным функционалом")
    
    return middleware