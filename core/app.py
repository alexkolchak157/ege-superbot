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
        # Код для активной подписки остается без изменений
        if subscription_info.get('type') == 'modular':
            text = "💳 <b>Ваша подписка</b>\n\n"
            text += "✅ <b>Активные модули:</b>\n"
            
            for module in subscription_info.get('modules', []):
                text += f"   • {module}\n"
            
            text += f"\n📅 <b>Действует до:</b> {subscription_info.get('expires_at').strftime('%d.%m.%Y')}\n"
            
            # Проверяем доступ к каждому модулю для детальной информации
            text += "\n📊 <b>Детали доступа:</b>\n"
            modules_to_check = ['test_part', 'task19', 'task20', 'task24', 'task25']
            module_names = {
                'test_part': '📝 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '📖 Задание 20',  # ИСПРАВЛЕНО: добавлена иконка
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
        # ИСПРАВЛЕНИЕ: Используем то же оформление, что и в show_modular_interface
        text = "💎 <b>Модульная система подписок</b>\n\n"
        text += "У вас пока нет активной подписки.\n\n"
        text += "<b>Доступные тарифы:</b>\n\n"
        
        # Добавляем информацию о доступных планах
        text += "🎁 <b>Пробный период</b> — 1₽\n"
        text += "   • Полный доступ на 7 дней\n"
        text += "   • Все модули включены\n\n"
        
        text += "🎯 <b>Пакет «Вторая часть»</b> — 499₽/мес\n"
        text += "   • Задание 19, 20, 25\n"
        text += "   <i>Экономия 98₽</i>\n\n"
        
        text += "👑 <b>Полный доступ</b> — 999₽/мес\n"
        text += "   • Все модули\n"
        text += "   • Приоритетная поддержка\n"
        text += "   <i>Экономия 346₽</i>\n\n"
        
        text += "📚 Или выберите отдельные модули"
    
    buttons = []
    
    if not subscription_info:
        buttons.append([InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe_start")])  # Изменить с "show_payment_plans"
    else:
        buttons.append([InlineKeyboardButton("🔄 Продлить подписку", callback_data="subscribe")])
    
    buttons.extend([
        #[InlineKeyboardButton("📊 Моя статистика", callback_data="my_statistics")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="to_main_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )

async def post_init(application: Application) -> None:
    """Инициализация после запуска бота"""
    logger.info("Выполняется post-init...")
    
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
    
    # Инициализация модуля платежей
    await init_payment_module(application)
    
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
    
    logger.info("Post-init завершен")

async def post_shutdown(application: Application) -> None:
    """Очистка ресурсов при остановке бота"""
    logger.info("Выполняется shutdown...")
    
    # Закрываем соединение с БД
    await db.close_db()
    
    logger.info("Shutdown завершен")

async def start_command(update: Update, context):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    user = update.effective_user
    
    # НОВОЕ: Сохраняем/обновляем информацию о пользователе
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
    
    # Проверяем подписку
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
    
    # НОВОЕ: Используем имя пользователя в приветствии
    welcome_name = user.first_name or "друг"
    welcome_text = f"""
👋 Добро пожаловать, {welcome_name}!

Это бот для подготовки к ЕГЭ по обществознанию.

{status_text}

Используйте кнопки ниже для навигации:
"""
    
    # Получаем меню с проверкой доступа
    menu_keyboard = await show_main_menu_with_access(context, user_id)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=menu_keyboard,
        parse_mode="HTML"
    )

async def show_main_menu_with_access(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> InlineKeyboardMarkup:
    """Показывает главное меню с индикацией доступа к модулям."""
    from core.plugin_loader import PLUGINS
    from payment.config import SUBSCRIPTION_MODE
    
    subscription_manager = context.bot_data.get('subscription_manager')
    buttons = []
    
    # Соответствие кодов плагинов и модулей
    plugin_to_module = {
        'test_part': 'test_part',
        'task19': 'task19', 
        'task20': 'task20',
        't20': 'task20',
        'task24': 'task24',
        'task25': 'task25'
    }
    
    for plugin in PLUGINS:
        module_code = plugin_to_module.get(plugin.code)
        
        if module_code and subscription_manager and SUBSCRIPTION_MODE == 'modular':
            # Проверяем доступ к модулю
            has_access = await subscription_manager.check_module_access(user_id, module_code)
            
            if has_access:
                # Доступ есть - используем оригинальный title плагина (с иконкой)
                button_text = plugin.title
            else:
                # Доступа нет - показываем с замком
                button_text = f"🔒 {plugin.title}"
        else:
            # Если не модульная система или модуль не требует проверки
            button_text = plugin.title
        
        buttons.append([InlineKeyboardButton(
            button_text,
            callback_data=f"choose_{plugin.code}"
        )])
    
    # Добавляем дополнительные кнопки
    buttons.extend([
        [InlineKeyboardButton("💳 Моя подписка", callback_data="my_subscriptions")],  # ИСПРАВЛЕНО: с 's'
        #[InlineKeyboardButton("⚙️ Настройки", callback_data="settings")]
    ])
    
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
            modules_to_check = ['test_part', 'task19', 'task20', 'task24', 'task25']
            module_names = {
                'test_part': 'Тестовая часть',
                'task19': 'Задание 19',
                'task20': 'Задание 20',
                'task24': 'Задание 24',
                'task25': 'Задание 25'
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
        text = "❌ <b>У вас нет активной подписки</b>\n\n"
        text += "Оформите подписку, чтобы получить доступ ко всем модулям:\n\n"
        text += "📚 <b>Доступные планы:</b>\n"
        text += "• Пакет «Вторая часть» - задания 19, 20, 25\n"
        text += "• Полный доступ - все модули\n"
        text += "• Пробный период - 7 дней\n"
    
    buttons = []
    
    if not subscription_info:
        buttons.append([InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe_start")])

    # Удалить кнопку "Моя статистика", так как для неё нет обработчика
    # Или создать заглушку
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
        
        # Добавляем persistence для сохранения состояний
        #persistence = PicklePersistence(filepath="bot_persistence.pickle")
        #builder.persistence(persistence)
        
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