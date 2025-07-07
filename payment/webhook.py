# payment/webhook.py
"""Webhook сервер для приема уведомлений от платежной системы."""
import logging
import json
import hashlib
import hmac
from aiohttp import web
from telegram import Bot

from core import config
from .subscription_manager import SubscriptionManager
from .tinkoff import TinkoffPayment

logger = logging.getLogger(__name__)

# Глобальные переменные для webhook приложения
webhook_app = None
webhook_runner = None
webhook_site = None


def verify_tinkoff_signature(data: dict, token: str, terminal_key: str, secret_key: str) -> bool:
    """Проверяет подпись от Tinkoff."""
    # Копируем данные для проверки
    check_data = data.copy()
    
    # Удаляем Token из данных
    received_token = check_data.pop('Token', '')
    
    # Добавляем пароль и TerminalKey
    check_data['Password'] = secret_key
    check_data['TerminalKey'] = terminal_key
    
    # Сортируем по ключам
    sorted_data = sorted(check_data.items())
    
    # Конкатенируем значения
    concat_values = ''.join(str(value) for key, value in sorted_data)
    
    # Вычисляем SHA256
    calculated_token = hashlib.sha256(concat_values.encode()).hexdigest()
    
    return calculated_token.upper() == received_token.upper()


async def handle_webhook(request: web.Request) -> web.Response:
    """Обработчик webhook запросов от Tinkoff."""
    try:
        # Читаем данные
        data = await request.json()
        logger.info(f"Webhook received: {data}")
        
        # Проверяем наличие необходимых полей
        if 'TerminalKey' not in data or 'Token' not in data:
            logger.warning("Missing required fields in webhook data")
            return web.Response(text="FAIL", status=400)
        
        # Проверяем подпись
        if not verify_tinkoff_signature(
            data,
            data.get('Token', ''),
            config.TINKOFF_TERMINAL_KEY,
            config.TINKOFF_SECRET_KEY
        ):
            logger.warning("Invalid webhook signature")
            return web.Response(text="FAIL", status=401)
        
        # Обрабатываем разные статусы
        status = data.get('Status')
        order_id = data.get('OrderId')
        payment_id = data.get('PaymentId')
        
        if not order_id:
            logger.warning("No OrderId in webhook data")
            return web.Response(text="OK")
        
        subscription_manager = SubscriptionManager()
        
        if status == 'CONFIRMED':
            # Платеж подтвержден - активируем подписку
            logger.info(f"Payment confirmed for order {order_id}")
            
            success = await subscription_manager.activate_subscription(
                order_id=order_id,
                payment_id=str(payment_id)
            )
            
            if success:
                logger.info(f"Subscription activated for order {order_id}")
                
                # Уведомляем пользователя
                bot = request.app.get('bot')
                if bot:
                    payment_info = await subscription_manager.get_payment_by_order_id(order_id)
                    if payment_info:
                        try:
                            await bot.send_message(
                                payment_info['user_id'],
                                "✅ Оплата прошла успешно! Подписка активирована.\n\n"
                                "Используйте /status для просмотра информации о подписке."
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify user: {e}")
            else:
                logger.error(f"Failed to activate subscription for order {order_id}")
        
        elif status in ['REJECTED', 'REFUNDED', 'PARTIAL_REFUNDED']:
            # Платеж отклонен/возвращен
            logger.info(f"Payment {status} for order {order_id}")
            await subscription_manager.update_payment_status(order_id, status.lower())
        
        return web.Response(text="OK")
        
    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook request")
        return web.Response(text="FAIL", status=400)
    except Exception as e:
        logger.exception(f"Error processing webhook: {e}")
        return web.Response(text="FAIL", status=500)


def create_webhook_app(bot: Bot = None) -> web.Application:
    """Создает aiohttp приложение для webhook."""
    app = web.Application()
    app['bot'] = bot
    app.router.add_post('/webhook', handle_webhook)
    return app


async def start_webhook_server(bot: Bot = None, port: int = 8080):
    """Запускает webhook сервер."""
    global webhook_app, webhook_runner, webhook_site
    
    try:
        # Проверяем конфигурацию
        if not all([
            getattr(config, 'TINKOFF_TERMINAL_KEY', None),
            getattr(config, 'TINKOFF_SECRET_KEY', None)
        ]):
            logger.warning("Tinkoff credentials not configured, webhook server not started")
            return
        
        # Создаем приложение
        webhook_app = create_webhook_app(bot)
        
        # Создаем и запускаем runner
        webhook_runner = web.AppRunner(webhook_app)
        await webhook_runner.setup()
        
        # Запускаем сайт
        webhook_site = web.TCPSite(webhook_runner, '0.0.0.0', port)
        await webhook_site.start()
        
        logger.info(f"Webhook server started on port {port}")
        
        # Логируем webhook URL для настройки в Tinkoff
        if hasattr(config, 'WEBHOOK_BASE_URL'):
            webhook_url = f"{config.WEBHOOK_BASE_URL}/webhook"
            logger.info(f"Webhook URL for Tinkoff: {webhook_url}")
        
    except Exception as e:
        logger.exception(f"Failed to start webhook server: {e}")


async def stop_webhook_server():
    """Останавливает webhook сервер."""
    global webhook_site, webhook_runner
    
    if webhook_site:
        await webhook_site.stop()
        webhook_site = None
    
    if webhook_runner:
        await webhook_runner.cleanup()
        webhook_runner = None
    
    logger.info("Webhook server stopped")