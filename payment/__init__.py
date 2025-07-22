# payment/__init__.py
"""Модуль платежей и подписок."""
import logging
import asyncio
from telegram.ext import Application

from .subscription_manager import SubscriptionManager
from .handlers import register_payment_handlers
from .middleware import setup_subscription_middleware
from .decorators import requires_subscription
from .webhook import start_webhook_server, stop_webhook_server
from .admin_commands import register_admin_commands
from core import config

logger = logging.getLogger(__name__)

# Экспортируемые объекты
__all__ = [
    'init_payment_module',
    'requires_subscription',
    'SubscriptionManager'
]

# Глобальные объекты
subscription_manager = None
webhook_task = None


async def init_payment_module(app: Application):
    """Инициализирует модуль платежей."""
    global subscription_manager, webhook_task
    
    logger.info("Initializing payment module...")
    
    # Создаем менеджер подписок
    subscription_manager = SubscriptionManager()
    
    # Сохраняем менеджер в bot_data для доступа из других модулей
    app.bot_data['subscription_manager'] = subscription_manager
    
    # Инициализируем таблицы БД
    await subscription_manager.init_tables()
    
    # Регистрируем обработчики
    register_payment_handlers(app)
    
    # Регистрируем админские команды (если пользователь админ)
    if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
        register_admin_commands(app)
        logger.info("Admin commands registered")
    
    # Регистрируем middleware для проверки подписок
    setup_subscription_middleware(app)
    
    # ИСПРАВЛЕНИЕ: Передаем объект бота в webhook сервер
    webhook_task = asyncio.create_task(start_webhook_server(bot=app.bot))
    
    # Добавляем обработчик для корректной остановки webhook при завершении
    async def shutdown_webhook():
        """Останавливает webhook сервер при завершении приложения."""
        if webhook_task and not webhook_task.done():
            await stop_webhook_server()
    
    app.post_shutdown.append(shutdown_webhook)
    
    logger.info("Payment module initialized successfully")
    
    return subscription_manager