# core/app.py - обновленная версия с интеграцией платежей

import asyncio
import logging
from telegram import Update
from telegram.ext import Application
import sys
import os

# Добавляем путь к корневой директории для импорта модулей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, db, plugin_loader
from payment import init_payment_module

logger = logging.getLogger(__name__)

# Глобальные переменные для webhook сервера
webhook_runner = None
webhook_site = None

async def post_init(application: Application) -> None:
    """Инициализация после запуска бота"""
    logger.info("Выполняется post-init...")
    
    # Инициализация БД
    await db.init_db()
    
    # Инициализация модуля платежей
    await init_payment_module(application)
    
    # Настройка middleware для проверки подписок
    # Это ДОЛЖНО быть после init_payment_module но ДО загрузки других модулей
    setup_subscription_middleware(
        application,
        free_commands={'start', 'help', 'subscribe', 'subscription', 'settings', 'about'},
        free_patterns={'main_menu', 'subscribe_', 'plan_', 'check_payment_', 'help_', 'settings_'},
        check_channel=True  # Также проверять подписку на канал
    )
    logger.info("Middleware для проверки подписок настроен")
    
    # Загрузка остальных модулей
    plugin_loader.load_modules(application)
    
    # Запуск webhook сервера для платежей
    await start_webhook_server(application)
    
    logger.info("Post-init завершен")

async def init_payment_module(application: Application) -> None:
    """Инициализация модуля платежей"""
    logger.info("Инициализация модуля платежей...")
    
    # Создаем менеджер подписок и сохраняем в bot_data
    subscription_manager = SubscriptionManager()
    application.bot_data['subscription_manager'] = subscription_manager
    
    # Регистрируем обработчики платежей
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("subscription", subscription_status_command))
    application.add_handler(CallbackQueryHandler(plan_callback, pattern="^plan_"))
    application.add_handler(CallbackQueryHandler(check_payment_callback, pattern="^check_payment_"))
    
    # Админские команды (если пользователь в списке админов)
    if hasattr(config, 'ADMIN_IDS'):
        application.add_handler(CommandHandler("grant_subscription", grant_subscription_command))
        application.add_handler(CommandHandler("revoke_subscription", revoke_subscription_command))
        application.add_handler(CommandHandler("payment_stats", payment_stats_command))
    
    logger.info("Модуль платежей инициализирован")

async def start_webhook_server(application: Application) -> None:
    """Запуск webhook сервера для приема уведомлений об оплате"""
    global webhook_runner, webhook_site
    
    # Проверяем наличие необходимых переменных окружения
    if not all([
        getattr(config, 'TINKOFF_TERMINAL_KEY', None),
        getattr(config, 'TINKOFF_SECRET_KEY', None),
        getattr(config, 'WEBHOOK_BASE_URL', None)
    ]):
        logger.warning("Переменные окружения для платежей не настроены. Webhook сервер не будет запущен.")
        return
    
    try:
        # Создаем aiohttp приложение для webhook
        webhook_app = create_webhook_app(application.bot)
        
        # Запускаем сервер на порту 8080
        webhook_runner = web.AppRunner(webhook_app)
        await webhook_runner.setup()
        webhook_site = web.TCPSite(webhook_runner, 'localhost', 8080)
        await webhook_site.start()
        
        logger.info("Webhook сервер запущен на порту 8080")
        
    except Exception as e:
        logger.error(f"Ошибка при запуске webhook сервера: {e}")

async def post_shutdown(application: Application) -> None:
    """Очистка ресурсов при остановке бота"""
    global webhook_runner, webhook_site
    
    logger.info("Выполняется shutdown...")
    
    # Останавливаем webhook сервер
    if webhook_site:
        await webhook_site.stop()
    if webhook_runner:
        await webhook_runner.cleanup()
    
    # Закрываем соединение с БД
    await db.close_db()
    
    logger.info("Shutdown завершен")

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
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    # Добавляем базовые команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Запуск бота
    logger.info("Запуск бота...")
    application.run_polling(allowed_updates=True)

async def start_command(update, context):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    # Проверяем/создаем пользователя в БД
    await db.ensure_user(user_id)
    
    # Проверяем подписку
    subscription_manager = context.bot_data.get('subscription_manager')
    if subscription_manager:
        subscription_info = await subscription_manager.get_subscription_info(user_id)
        if subscription_info['is_active']:
            status_text = f"✅ У вас активная подписка: {subscription_info['plan_name']}"
        else:
            status_text = "❌ У вас нет активной подписки"
    else:
        status_text = ""
    
    welcome_text = f"""
👋 Добро пожаловать в бот для подготовки к ЕГЭ по обществознанию!

{status_text}

Доступные команды:
/help - справка по командам
/subscribe - оформить подписку
/subscription - статус подписки

Выберите раздел для начала работы:
    """
    
    # Здесь должна быть клавиатура с основными разделами
    await update.message.reply_text(welcome_text)

async def help_command(update, context):
    """Обработчик команды /help"""
    help_text = """
📚 Справка по командам:

/start - начать работу с ботом
/subscribe - оформить подписку
/subscription - проверить статус подписки
/help - показать эту справку

💎 О подписках:
• Бесплатно: 50 вопросов в месяц
• Базовая (299₽/мес): 100 вопросов в день
• Pro (599₽/мес): неограниченно
• Pro до ЕГЭ (1999₽): неограниченно до ЕГЭ 2025

По всем вопросам: @your_support_bot
    """
    await update.message.reply_text(help_text)

if __name__ == '__main__':
    main()