# core/app.py - исправленная версия с правильной интеграцией платежей

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from typing import Optional, Dict, Any
from datetime import datetime
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, PicklePersistence, ContextTypes
from telegram.constants import ParseMode
import sys
import os

# Добавляем путь к корневой директории для импорта модулей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, db
from payment import init_payment_module

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный обработчик ошибок для бота."""
    from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut

    # Логируем всю информацию об ошибке
    logger.error(f"Exception while handling an update:", exc_info=context.error)

    # Получаем информацию об ошибке
    error = context.error

    # Обрабатываем специфичные типы ошибок
    if isinstance(error, BadRequest):
        if "Message is not modified" in str(error):
            # Это не критичная ошибка - сообщение просто не изменилось
            logger.debug(f"Ignored 'Message is not modified' error")
            return
        logger.warning(f"BadRequest error: {error}")

    elif isinstance(error, Forbidden):
        # Пользователь заблокировал бота
        logger.warning(f"Bot was blocked by user")
        # Можно добавить логику деактивации пользователя

    elif isinstance(error, (NetworkError, TimedOut)):
        # Сетевые ошибки - можно игнорировать или залогировать
        logger.warning(f"Network error: {error}")

    else:
        # Все остальные ошибки
        logger.error(f"Unhandled error: {type(error).__name__}: {error}")

    # Пытаемся уведомить пользователя об ошибке (если возможно)
    try:
        if update and hasattr(update, 'effective_message') and update.effective_message:
            await update.effective_message.reply_text(
                "😔 Произошла ошибка при обработке вашего запроса.\n"
                "Пожалуйста, попробуйте позже или обратитесь в поддержку."
            )
        elif update and hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.answer(
                "❌ Произошла ошибка. Попробуйте позже.",
                show_alert=True
            )
    except Exception as e:
        # Не удалось отправить сообщение пользователю
        logger.error(f"Failed to send error message to user: {e}")


async def post_init(application: Application) -> None:
    """Инициализация после запуска бота"""
    logger.info("Выполняется post-init...")

    # Регистрация глобального обработчика ошибок
    application.add_error_handler(error_handler)
    logger.info("Global error handler registered")

    # Инициализация БД
    await db.init_db()
    try:
        from core.admin_tools import init_price_tables
        await init_price_tables()
        logger.info("Price tables initialized")
    except Exception as e:
        logger.error(f"Failed to initialize price tables: {e}")
    try:
        from core.user_middleware import register_user_middleware
        register_user_middleware(application)
        logger.info("User middleware registered")
    except Exception as e:
        logger.error(f"Failed to register user middleware: {e}")
        # Добавляем глобальную команду cancel
    async def global_cancel(update: Update, context):
        """Глобальный обработчик команды /cancel"""
        # Очищаем состояние пользователя
        context.user_data.clear()
        
        # Пробуем получить меню
        try:
            from core.plugin_loader import build_main_menu
            kb = build_main_menu()
            
            await update.message.reply_text(
                "❌ Действие отменено.\n\n"
                "📚 Выберите раздел для подготовки:",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
        except:
            await update.message.reply_text(
                "❌ Действие отменено.\n\n"
                "Используйте /menu для возврата в главное меню."
            )
    # Добавляем базовые команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CallbackQueryHandler(handle_my_subscription, pattern="^my_subscription$"))
    application.add_handler(CommandHandler("cancel", global_cancel), group=10)
    # ВАЖНО: Регистрируем глобальные обработчики меню
    try:
        from core.menu_handlers import register_global_handlers
        register_global_handlers(application)
        logger.info("Registered global menu handlers")
    except ImportError as e:
        logger.error(f"Could not import menu_handlers: {e}")
    except Exception as e:
        logger.error(f"Error registering global handlers: {e}")
    
    # Регистрируем админские обработчики
    try:
        from core.admin_tools import register_admin_handlers
        register_admin_handlers(application)
        logger.info("Admin handlers registered")
    except ImportError as e:
        logger.error(f"Could not import admin_tools: {e}")
    except Exception as e:
        logger.error(f"Error registering admin handlers: {e}")

    # Регистрируем админские обработчики для жалоб
    try:
        from core.complaint_admin import register_admin_complaint_handlers
        register_admin_complaint_handlers(application)
        logger.info("Admin complaint handlers registered")
    except ImportError as e:
        logger.error(f"Could not import complaint_admin: {e}")
    except Exception as e:
        logger.error(f"Error registering admin complaint handlers: {e}")
    
    # Инициализация модуля платежей
    await init_payment_module(application)

    # Инициализация FreemiumManager
    try:
        from core.freemium_manager import get_freemium_manager
        subscription_manager = application.bot_data.get('subscription_manager')
        freemium_manager = get_freemium_manager(subscription_manager)
        application.bot_data['freemium_manager'] = freemium_manager
        logger.info("FreemiumManager initialized and added to bot_data")
    except Exception as e:
        logger.error(f"Failed to initialize FreemiumManager: {e}")

    # Регистрация обработчиков уведомлений
    try:
        from core.notification_handlers import register_notification_handlers
        register_notification_handlers(application)
        logger.info("Notification handlers registered")
    except Exception as e:
        logger.error(f"Failed to register notification handlers: {e}")

    # Инициализация retention scheduler
    try:
        from datetime import time as dt_time
        from core.retention_scheduler import get_retention_scheduler

        scheduler = get_retention_scheduler()
        application.bot_data['retention_scheduler'] = scheduler

        # Запускаем ежедневную отправку уведомлений в 17:00 (после школы)
        application.job_queue.run_daily(
            scheduler.send_daily_notifications,
            time=dt_time(hour=17, minute=0, second=0),
            name='daily_retention_notifications'
        )

        logger.info("Retention scheduler initialized and scheduled for 17:00 daily")
    except Exception as e:
        logger.error(f"Failed to initialize retention scheduler: {e}")

    # Загрузка модулей-плагинов
    try:
        from core import plugin_loader
        if hasattr(plugin_loader, 'load_modules'):
            plugin_loader.load_modules(application)
        else:
            # Если load_modules не существует, используем discover_plugins
            plugin_loader.discover_plugins()
            
            # Регистрируем плагины вручную
            for plugin in plugin_loader.PLUGINS:
                try:
                    logger.info(f"Registering plugin: {plugin.title}")
                    plugin.register(application)
                except Exception as e:
                    logger.error(f"Failed to register plugin {plugin.code}: {e}")
            
            # Добавляем обработчик для главного меню
            application.add_handler(
                CallbackQueryHandler(show_plugin_menu, pattern="^main_menu$")
            )
    except Exception as e:
        logger.error(f"Error loading plugins: {e}")
        logger.info("Bot will work without additional plugins")
    # Инициализируем плагины
    if 'plugin_post_init_tasks' in application.bot_data:
        for plugin in application.bot_data['plugin_post_init_tasks']:
            try:
                logger.info(f"Running post_init for plugin: {plugin.title}")
                await plugin.post_init(application)
                logger.info(f"✅ Plugin {plugin.title} initialized")
            except Exception as e:
                logger.error(f"Failed to initialize plugin {plugin.title}: {e}")
            
    logger.info("Post-init завершен")

async def post_shutdown(application: Application) -> None:
    """Очистка ресурсов при остановке бота"""
    logger.info("Выполняется shutdown...")

    # Вызываем дополнительные shutdown handlers из модулей
    if 'custom_shutdown_handlers' in application.bot_data:
        for handler in application.bot_data['custom_shutdown_handlers']:
            try:
                await handler(application)
                logger.info(f"Custom shutdown handler executed successfully")
            except Exception as e:
                logger.error(f"Error in custom shutdown handler: {e}")

    # Закрываем соединение с БД
    await db.close_db()

    logger.info("Shutdown завершен")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start с улучшенным приветствием."""
    user = update.effective_user
    user_id = user.id
    
    # Сохраняем/обновляем информацию о пользователе
    await db.update_user_info(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    args = context.args
    
    if args and len(args) > 0:
        param = args[0]
        
        # Обработка возврата после оплаты
        if param.startswith('payment_success_'):
            order_id = param.replace('payment_success_', '')
            await update.message.reply_text(
                "✅ <b>Спасибо за оплату!</b>\n\n"
                "Ваша подписка будет активирована в течение нескольких минут.\n"
                "Используйте /my_subscriptions для проверки статуса.",
                parse_mode=ParseMode.HTML
            )
            return
            
        elif param.startswith('payment_fail_'):
            order_id = param.replace('payment_fail_', '')
            await update.message.reply_text(
                "❌ <b>Оплата не прошла</b>\n\n"
                "Попробуйте оформить подписку еще раз.\n"
                "Используйте /subscribe для выбора плана.",
                parse_mode=ParseMode.HTML
            )
            return
    
    # Проверяем/создаем пользователя в БД
    await db.ensure_user(user_id)
    
    # Определяем, новый ли это пользователь (через context.user_data)
    is_new_user = not context.user_data.get('returning_user', False)
    context.user_data['returning_user'] = True
    
    # Проверяем подписку
    subscription_manager = context.bot_data.get('subscription_manager')
    subscription_info = None
    
    if subscription_manager:
        subscription_info = await subscription_manager.get_subscription_info(user_id)
    
    # Персонализированное приветствие
    user_name = user.first_name or "друг"
    current_hour = datetime.now().hour
    
    if 5 <= current_hour < 12:
        greeting = "Доброе утро"
    elif 12 <= current_hour < 17:
        greeting = "Добрый день"
    elif 17 <= current_hour < 23:
        greeting = "Добрый вечер"
    else:
        greeting = "Привет"
    
    # Формируем текст в зависимости от статуса подписки и нового/старого пользователя
    if is_new_user:
        # КРАТКОЕ и убедительное приветствие для НОВЫХ пользователей
        welcome_text = f"{greeting}, {user_name}! 👋\n\n"
        welcome_text += "🎯 <b>Готовься к ЕГЭ по обществознанию с ИИ-репетитором</b>\n\n"

        welcome_text += "✨ <b>Что тебя ждёт:</b>\n\n"

        welcome_text += "🆓 <b>Тестовая часть:</b> 1000+ вопросов с разборами\n"
        welcome_text += "💎 <b>Вторая часть:</b> ИИ проверяет задания 19-25 как эксперт ФИПИ\n"
        welcome_text += "🎁 <b>Бонус:</b> 3 бесплатных AI-проверки каждый день\n\n"

        if not subscription_info or not subscription_info.get('is_active'):
            welcome_text += "🚀 <b>Попробуй прямо сейчас:</b>\n"
            welcome_text += "• Пробный период: 1₽ за 7 дней полного доступа\n"
            welcome_text += "• Полная подписка: от 249₽/мес\n\n"

        welcome_text += "👇 <b>Начни с бесплатной тестовой части или попробуй AI-проверку!</b>"
        
    else:
        # КОРОТКОЕ приветствие для ВОЗВРАЩАЮЩИХСЯ пользователей
        if subscription_info and subscription_info.get('is_active'):
            # Пользователь с активной подпиской
            expires = subscription_info.get('expires_at').strftime('%d.%m.%Y')
            welcome_text = f"{greeting}, {user_name}! С возвращением! 👋\n\n"
            welcome_text += f"✅ <b>Подписка активна до {expires}</b>\n\n"
            
            # Показываем доступные модули
            if subscription_info.get('type') == 'modular':
                welcome_text += "📚 <b>Твои модули:</b>\n"
                modules = subscription_info.get('modules', [])
                
                # Всегда показываем тестовую часть
                welcome_text += "• 🆓 Тестовая часть\n"
                
                module_names = {
                    'task19': '• ✅ Задание 19',
                    'task20': '• ✅ Задание 20', 
                    'task24': '• ✅ Задание 24',
                    'task25': '• ✅ Задание 25'
                }
                
                for module in modules:
                    if module != 'test_part':
                        welcome_text += f"{module_names.get(module, '• ✅ ' + module)}\n"
            else:
                welcome_text += "📚 <b>Все модули доступны!</b>\n"
            
            # Мотивационное сообщение
            if 5 <= current_hour < 9:
                welcome_text += "\n☕ Отличное время для утренней практики!"
            elif 9 <= current_hour < 12:
                welcome_text += "\n🧠 Мозг на пике активности — лови момент!"
            elif 12 <= current_hour < 15:
                welcome_text += "\n📚 Самое время закрепить материал!"
            elif 15 <= current_hour < 18:
                welcome_text += "\n⚡ Используй время с пользой!"
            elif 18 <= current_hour < 22:
                welcome_text += "\n🎯 Вечерняя тренировка — ключ к успеху!"
            else:
                welcome_text += "\n🌙 Полуночная подготовка? Уважаю!"
            
            welcome_text += "\n\nВыбирай модуль и продолжим подготовку:"
            
        else:
            # Возвращающийся пользователь без подписки - среднее по длине сообщение
            welcome_text = f"{greeting}, {user_name}! С возвращением! 👋\n\n"

            # Показываем информацию о лимитах
            freemium_manager = context.bot_data.get('freemium_manager')
            if freemium_manager:
                limit_info = await freemium_manager.get_limit_info(user_id)
                remaining = limit_info.get('checks_remaining', 0)
                if remaining > 0:
                    welcome_text += f"📊 Сегодня доступно: <b>{remaining} AI-проверки</b>\n\n"
                else:
                    welcome_text += "⏳ Лимит проверок исчерпан. Обновится завтра.\n\n"

            welcome_text += "🆓 <b>Тестовая часть всегда бесплатна!</b>\n"
            welcome_text += "• 1000+ вопросов с разборами\n"
            welcome_text += "• Все блоки и темы ЕГЭ\n"
            welcome_text += "• Отслеживание прогресса\n\n"

            welcome_text += "💎 <b>Открой больше возможностей:</b>\n"
            welcome_text += "• ИИ-проверка заданий 19-25\n"
            welcome_text += "• Персональные рекомендации\n"
            welcome_text += "• От 249₽/месяц за полный доступ\n\n"

            welcome_text += "👇 Начни тренировку или оформи подписку:"
    
    # Получаем меню с индикацией доступа (используем оригинальную функцию)
    menu_keyboard = await show_main_menu_with_access(context, user_id)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=menu_keyboard,
        parse_mode="HTML"
    )

async def show_main_menu_with_access(context, user_id):
    """
    ИСПРАВЛЕННАЯ ВЕРСИЯ
    Показывает главное меню с правильной индикацией доступа и системными кнопками.
    
    Изменения:
    1. Исправлен callback_data для "Мои подписки": my_subscriptions → my_subscription
    2. Добавлено добавление системных кнопок в итоговый массив
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    subscription_manager = context.bot_data.get('subscription_manager')
    buttons = []
    
    # Получаем список плагинов
    from core import plugin_loader
    plugins = plugin_loader.PLUGINS
    
    for plugin in plugins:
        if plugin.code == 'test_part':
            # Тестовая часть - всегда доступна бесплатно
            icon = "🆓"
            badge = " БЕСПЛАТНО"
            text = f"{icon} {plugin.title}{badge}"
            
        elif subscription_manager:
            # Проверяем доступ к платным модулям
            has_access = await subscription_manager.check_module_access(user_id, plugin.code)
            
            if has_access:
                icon = "✅"
                text = f"{icon} {plugin.title}"
            else:
                icon = "🔒"
                text = f"{icon} {plugin.title}"
        else:
            # Если система подписок недоступна
            icon = "📚"
            text = f"{icon} {plugin.title}"
        
        button = InlineKeyboardButton(
            text=text,
            callback_data=f"choose_{plugin.code}"
        )
        buttons.append([button])
    
    # Добавляем системные кнопки
    system_buttons = []
    
    if subscription_manager:
        subscription_info = await subscription_manager.get_subscription_info(user_id)
        
        if subscription_info:
            system_buttons.append(
                InlineKeyboardButton("💳 Моя подписка", callback_data="my_subscription")  # ИСПРАВЛЕНО
            )
        else:
            system_buttons.append(
                InlineKeyboardButton("💎 Оформить подписку", callback_data="subscribe_start")
            )
    
    # ИСПРАВЛЕНИЕ: Добавляем системные кнопки в основной массив
    if system_buttons:
        buttons.append(system_buttons)
    
    return InlineKeyboardMarkup(buttons)

async def handle_my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о подписке пользователя."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager')
    
    if not subscription_manager:
        await query.edit_message_text("❌ Сервис подписок временно недоступен")
        return
    
    subscription_info = await subscription_manager.get_subscription_info(user_id)
    
    if subscription_info:
        if subscription_info.get('type') == 'modular':
            # Модульная подписка
            text = "💳 <b>Ваша подписка</b>\n\n"
            text += "✅ <b>Активные модули:</b>\n"
            
            for module in subscription_info.get('modules', []):
                text += f"   • {module}\n"
            
            text += f"\n📅 <b>Действует до:</b> {subscription_info.get('expires_at').strftime('%d.%m.%Y')}\n"
            
            # Проверяем доступ к каждому модулю для детальной информации
            text += "\n📊 <b>Детали доступа:</b>\n"
            # ИСПРАВЛЕНИЕ 3: Убираем test_part из списка проверяемых модулей
            modules_to_check = ['task19', 'task20', 'task24', 'task25']
            module_names = {
                'task19': '🎯 Задание 19',
                'task20': '📖 Задание 20',
                'task24': '💎 Задание 24',
                'task25': '✍️ Задание 25'
            }
            
            for module_code in modules_to_check:
                has_access = await subscription_manager.check_module_access(user_id, module_code)
                status = "✅" if has_access else "❌"
                text += f"   {status} {module_names.get(module_code, module_code)}\n"
        else:
            # Единая подписка
            text = "💳 <b>Ваша подписка</b>\n\n"
            text += f"✅ <b>План:</b> {subscription_info.get('plan_name')}\n"
            text += f"📅 <b>Действует до:</b> {subscription_info.get('expires_at').strftime('%d.%m.%Y')}\n"
    else:
        text = "💎 <b>Модульная система подписок</b>\n\n"
        text += "У вас пока нет активной подписки.\n\n"
        text += "<b>Доступные тарифы:</b>\n\n"
        
        text += "🎁 <b>Пробный период</b> — 1₽\n"
        text += "   • Полный доступ на 7 дней\n"
        text += "   • Все модули включены\n\n"
        
        text += "🎯 <b>Пакет «Вторая часть»</b> — 499₽/мес\n"
        text += "   • Задание 19, 20, 25\n"
        text += "   <i>Экономия 98₽</i>\n\n"
        
        text += "👑 <b>Полный доступ</b> — 799₽/мес\n"
        text += "   • Все модули\n"
        text += "   • Приоритетная поддержка\n"
        text += "   <i>Экономия 97₽</i>\n\n"
        
        text += "📚 Или выберите отдельные модули"
    
    buttons = []
    
    # ИСПРАВЛЕНИЕ 1: Добавляем кнопки продления/обновления подписки
    if subscription_info:
        # Пользователь с активной подпиской
        buttons.append([InlineKeyboardButton("🔄 Продлить подписку", callback_data="renew_subscription")])
        buttons.append([InlineKeyboardButton("➕ Добавить модули", callback_data="subscribe_start")])
    else:
        # Пользователь без подписки
        buttons.append([InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe_start")])
    
    buttons.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="to_main_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )

# Исправленная функция show_main_menu
def show_main_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """Синхронная обертка для совместимости."""
    # Возвращаем базовое меню без проверки доступа
    # Асинхронную версию нужно вызывать отдельно
    from core.plugin_loader import build_main_menu
    return build_main_menu()

async def help_command(update: Update, context):
    """Обработчик команды /help"""
    
    # Попробуем получить актуальные цены
    try:
        from payment.config import SUBSCRIPTION_MODE, MODULE_PLANS, LEGACY_SUBSCRIPTION_PLANS
        
        if SUBSCRIPTION_MODE == 'modular':
            pricing_text = """
💎 О подписках (модульная система):
- Бесплатно: 50 вопросов в месяц
- Отдельные модули: от 149₽/мес
- Пакеты: от 499₽/мес
- Полный доступ: 999₽/мес
"""
        else:
            plans = LEGACY_SUBSCRIPTION_PLANS
            pricing_text = f"""
💎 О подписках:
- Бесплатно: 50 вопросов в месяц
- Базовая ({plans['basic_month']['price_rub']}₽/мес): 100 вопросов в день
- Pro ({plans['pro_month']['price_rub']}₽/мес): неограниченно
- Pro до ЕГЭ ({plans['pro_ege']['price_rub']}₽): неограниченно до ЕГЭ 2025
"""
    except:
        # Fallback
        pricing_text = """
💎 О подписках:
- Бесплатно: 50 вопросов в месяц
- Различные планы подписки доступны
- Используйте /subscribe для просмотра актуальных цен
"""
    
    help_text = f"""
📚 Справка по командам:

/start - начать работу с ботом
/menu - показать главное меню
/subscribe - оформить подписку
/status - проверить статус подписки
/help - показать эту справку

{pricing_text}

По всем вопросам: @obshestvonapalcahsupport
    """
    await update.message.reply_text(help_text, parse_mode="HTML")

async def menu_command(update: Update, context):
    """Обработчик команды /menu"""
    user = update.effective_user
    
    # НОВОЕ: Обновляем информацию о пользователе при каждом вызове /menu
    await db.update_user_info(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    try:
        # Пробуем использовать меню с проверкой доступа
        user_id = update.effective_user.id
        try:
            from core.app import show_main_menu_with_access
            kb = await show_main_menu_with_access(context, user_id)
        except:
            # Если функция недоступна, используем базовое меню
            from core.plugin_loader import build_main_menu
            kb = build_main_menu()
        
        text = "📚 Выберите раздел для подготовки к ЕГЭ:"
        
        # Добавим приветствие с именем если доступно
        if user.first_name:
            text = f"👋 Привет, {user.first_name}!\n\n" + text
        
        await update.message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error in menu_command: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при загрузке меню.\n"
            "Попробуйте /start для перезапуска бота."
        )

async def show_plugin_menu(update: Update, context):
    """Показывает меню плагинов"""
    query = update.callback_query
    await query.answer()
    
    try:
        from core import plugin_loader
        menu = plugin_loader.build_main_menu()
        await query.edit_message_text(
            "📚 Выберите раздел для подготовки:",
            reply_markup=menu
        )
    except Exception as e:
        logger.error(f"Error showing plugin menu: {e}")
        await query.edit_message_text("❌ Ошибка при загрузке меню")

def main():
    """Главная функция запуска бота"""
    # Настройка логирования
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Проверка наличия токена
    if not hasattr(config, 'BOT_TOKEN') or not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не найден в конфигурации!")
        return
    
    # Создание приложения
    try:
        builder = Application.builder()
        builder.token(config.BOT_TOKEN)
        
        persistence = PicklePersistence(
            filepath="bot_persistence.pickle",
            # Сохраняем данные каждые 30 секунд и при завершении
            update_interval=30
        )
        builder.persistence(persistence)
        
        # Настройка параметров
        builder.post_init(post_init)
        builder.post_shutdown(post_shutdown)
        
        # Дополнительные настройки
        if hasattr(config, 'PROXY_URL') and config.PROXY_URL:
            from telegram.request import HTTPXRequest
            builder.request(HTTPXRequest(proxy=config.PROXY_URL))
        
        # Создаем приложение
        application = builder.build()
        
        logger.info("Запуск бота...")
        
        # Запуск бота
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.exception(f"Критическая ошибка при запуске бота: {e}")
        raise

if __name__ == '__main__':
    main()