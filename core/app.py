# core/app.py - исправленная версия с правильной интеграцией платежей

import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, PicklePersistence
from telegram.constants import ParseMode
import sys
import os

# Добавляем путь к корневой директории для импорта модулей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, db
from payment import init_payment_module

logger = logging.getLogger(__name__)

async def post_init(application: Application) -> None:
    """Инициализация после запуска бота"""
    logger.info("Выполняется post-init...")
    
    # Инициализация БД
    await db.init_db()
    
    # Добавляем базовые команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", menu_command))
    
    # Инициализация модуля платежей
    # Модуль сам регистрирует все обработчики и запускает webhook
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
    
    # Проверяем/создаем пользователя в БД
    await db.ensure_user(user_id)
    
    # Проверяем подписку
    subscription_manager = context.bot_data.get('subscription_manager')
    if subscription_manager:
        subscription_info = await subscription_manager.get_subscription_info(user_id)
        if subscription_info and subscription_info.get('is_active'):
            status_text = f"✅ У вас активная подписка: {subscription_info.get('plan_name', 'Неизвестный план')}"
        else:
            status_text = "❌ У вас нет активной подписки"
    else:
        status_text = ""
    
    welcome_text = f"""
👋 Добро пожаловать в бот для подготовки к ЕГЭ по обществознанию!

{status_text}

Доступные команды:
/help - справка по командам
/menu - главное меню
/subscribe - оформить подписку
/status - статус подписки

Выберите раздел для начала работы:
    """
    
    # Показываем главное меню если есть плагины
    try:
        from core import plugin_loader
        if hasattr(plugin_loader, 'build_main_menu'):
            menu = plugin_loader.build_main_menu()
            await update.message.reply_text(welcome_text, reply_markup=menu, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)

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

По всем вопросам: @your_support_bot
    """
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

async def menu_command(update: Update, context):
    """Обработчик команды /menu"""
    try:
        from core import plugin_loader
        if hasattr(plugin_loader, 'build_main_menu'):
            menu = plugin_loader.build_main_menu()
            await update.message.reply_text(
                "📚 Выберите раздел для подготовки:",
                reply_markup=menu
            )
        else:
            await update.message.reply_text(
                "📚 Главное меню временно недоступно.\n"
                "Используйте /help для просмотра доступных команд."
            )
    except Exception as e:
        logger.error(f"Error showing menu: {e}")
        await update.message.reply_text("❌ Ошибка при загрузке меню")

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
        persistence = PicklePersistence(filepath="bot_persistence.pickle")
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