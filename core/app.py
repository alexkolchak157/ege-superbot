# core/app.py - исправленная версия с правильной интеграцией платежей

import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram.constants import ParseMode
import sys
import os

# Добавляем путь к корневой директории для импорта модулей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, db, plugin_loader
from payment import init_payment_module

logger = logging.getLogger(__name__)

async def post_init(application: Application) -> None:
    """Инициализация после запуска бота"""
    logger.info("Выполняется post-init...")
    
    # Инициализация БД
    await db.init_db()
    
    # Добавляем базовые команды до инициализации модулей
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Инициализация модуля платежей
    # Модуль сам регистрирует все обработчики и запускает webhook
    await init_payment_module(application)
    
    # Загрузка остальных модулей
    plugin_loader.load_modules(application)
    
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
/subscribe - оформить подписку
/status - статус подписки

Выберите раздел для начала работы:
    """
    
    # Здесь должна быть клавиатура с основными разделами
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)

async def help_command(update: Update, context):
    """Обработчик команды /help"""
    help_text = """
📚 Справка по командам:

/start - начать работу с ботом
/subscribe - оформить подписку
/status - проверить статус подписки
/help - показать эту справку

💎 О подписках:
• Бесплатно: 50 вопросов в месяц
• Базовая (299₽/мес): 100 вопросов в день
• Pro (599₽/мес): неограниченно
• Pro до ЕГЭ (1999₽): неограниченно до ЕГЭ 2025

По всем вопросам: @your_support_bot
    """
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

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
        # Настройка persistence для сохранения состояний
        from telegram.ext import PicklePersistence
        persistence = PicklePersistence(filepath='bot_persistence.pickle')
        
        builder = Application.builder()
        builder.token(config.BOT_TOKEN)
        builder.persistence(persistence)  # ← Добавляем persistence
        
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