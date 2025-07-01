# payment/__init__.py
"""Модуль платежей и подписок."""
import logging
import asyncio
from telegram.ext import Application

from .subscription_manager import SubscriptionManager
from .handlers import register_payment_handlers
from .middleware import register_subscription_middleware, requires_subscription
from .webhook import start_webhook_server

logger = logging.getLogger(__name__)

# Экспортируемые объекты
__all__ = [
    'init_payment_module',
    'requires_subscription',
    'SubscriptionManager'
]

# Глобальные объекты
subscription_manager = None
webhook_runner = None


async def init_payment_module(app: Application):
    """Инициализирует модуль платежей."""
    global subscription_manager
    
    logger.info("Initializing payment module...")
    
    # Создаем менеджер подписок
    subscription_manager = SubscriptionManager()
    
    # Инициализируем таблицы БД
    await subscription_manager.init_tables()
    
    # Регистрируем обработчики
    register_payment_handlers(app)
    register_subscription_middleware(app)
    
    # Запускаем webhook сервер в фоне
    webhook_task = asyncio.create_task(start_webhook_server())
    
    logger.info("Payment module initialized successfully")
    
    return subscription_manager