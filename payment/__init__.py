# payment/__init__.py
"""Модуль платежей и подписок."""
import logging
import asyncio
from telegram.ext import Application
from .auto_renewal_scheduler import AutoRenewalScheduler
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
    
    # Пробуем импортировать и регистрировать обработчики автопродления
    try:
        from .auto_renewal_handlers import register_auto_renewal_handlers
        register_auto_renewal_handlers(app)
        logger.info("Auto-renewal handlers registered")
    except ImportError as e:
        logger.warning(f"Auto-renewal handlers not available: {e}")
    except Exception as e:
        logger.error(f"Error registering auto-renewal handlers: {e}")
    
    # Пробуем запустить планировщик (если доступен)
    try:
        from .scheduler import SubscriptionScheduler
        scheduler = AutoRenewalScheduler(
            bot=app.bot,
            subscription_manager=subscription_manager,
            tinkoff_api=TinkoffPayment()
        )
        scheduler.start()
        app.bot_data['auto_renewal_scheduler'] = scheduler
        
        # ИСПРАВЛЕНИЕ: Используем правильный метод для регистрации обработчика завершения
        async def shutdown_scheduler(application: Application) -> None:
            if 'subscription_scheduler' in application.bot_data:
                application.bot_data['subscription_scheduler'].stop()
        
        # Регистрируем через post_shutdown (это метод, а не список!)
        app.post_shutdown(shutdown_scheduler)
        logger.info("Subscription scheduler initialized")
        
    except ImportError:
        logger.info("Subscription scheduler not available (scheduler.py not found)")
    except Exception as e:
        logger.error(f"Error initializing subscription scheduler: {e}")
    
    # ИСПРАВЛЕНИЕ: Передаем объект бота в webhook сервер
    webhook_task = asyncio.create_task(start_webhook_server(bot=app.bot))
    
async def shutdown_webhook(application: Application) -> None:
    """Останавливает webhook сервер при завершении приложения."""
    if 'auto_renewal_scheduler' in app.bot_data:
        app.bot_data['auto_renewal_scheduler'].stop()
    if webhook_task and not webhook_task.done():
        await stop_webhook_server()
    
    # Регистрируем через post_shutdown (это метод, а не список!)
    app.post_shutdown(shutdown_webhook)
    
    logger.info("Payment module initialized successfully")
    
    return subscription_manager