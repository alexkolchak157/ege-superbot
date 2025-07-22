# payment/webhook.py
"""Webhook сервер для приема уведомлений от платежной системы."""
import logging
import json
import hashlib
import hmac
from aiohttp import web
from telegram import Bot
import asyncio
from datetime import datetime
import aiosqlite
from enum import Enum
from core import config
from .subscription_manager import SubscriptionManager
from .tinkoff import TinkoffPayment

logger = logging.getLogger(__name__)

# Глобальные переменные для webhook приложения
webhook_app = None
webhook_runner = None
webhook_site = None

class TinkoffStatus(Enum):
    """Статусы платежей Tinkoff"""
    INIT = "INIT"
    NEW = "NEW"
    FORM_SHOWED = "FORM_SHOWED"
    AUTHORIZED = "AUTHORIZED"
    CONFIRMED = "CONFIRMED"
    CANCELED = "CANCELED"
    DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
    REJECTED = "REJECTED"
    AUTH_FAIL = "AUTH_FAIL"
    REFUNDED = "REFUNDED"
    PARTIAL_REFUNDED = "PARTIAL_REFUNDED"
    REVERSED = "REVERSED"

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
        logger.info(f"Webhook received: {json.dumps(data, indent=2)}")
        
        # Логируем событие в БД
        await log_webhook_event(data)
        
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
        
        # Проверяем, не обработан ли уже этот платеж
        if await is_payment_processed(order_id, status):
            logger.info(f"Payment {order_id} with status {status} already processed")
            return web.Response(text="OK")
        
        subscription_manager = SubscriptionManager()
        
        # Обновляем статус платежа в БД
        await subscription_manager.update_payment_status(order_id, status.lower())
        
        if status == TinkoffStatus.CONFIRMED.value:
            logger.info(f"Payment confirmed for order {order_id}")
            
            # Добавляем дополнительное логирование
            logger.info(f"Attempting to activate subscription for order {order_id}")
            
            success = await subscription_manager.activate_subscription(
                order_id=order_id,
                payment_id=str(payment_id)
            )
            
            if success:
                logger.info(f"✅ Subscription activated successfully for order {order_id}")
                
                # Получаем информацию о платеже для отправки уведомления
                payment_info = await subscription_manager.get_payment_by_order_id(order_id)
                logger.info(f"Payment info: {payment_info}")
                # Уведомляем пользователя
                bot = request.app.get('bot')
                if bot:
                    await notify_user_success(bot, order_id)
            else:
                logger.error(f"❌ Failed to activate subscription for order {order_id}")
        
        elif status == TinkoffStatus.REJECTED.value:
            bot = request.app.get('bot')
            if bot:
                await notify_user_rejected(bot, order_id)
                
        elif status == TinkoffStatus.REFUNDED.value:
            # При возврате деактивируем подписку
            payment_info = await subscription_manager.get_payment_by_order_id(order_id)
            if payment_info:
                await subscription_manager.deactivate_subscription(
                    payment_info['user_id'], 
                    payment_info['plan_id']
                )
                bot = request.app.get('bot')
                if bot:
                    await notify_user_refunded(bot, order_id)
        
        elif status == TinkoffStatus.CANCELED.value:
            bot = request.app.get('bot')
            if bot:
                await notify_user_canceled(bot, order_id)
        
        return web.Response(text="OK")
        
    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook request")
        return web.Response(text="FAIL", status=400)
    except Exception as e:
        logger.exception(f"Error processing webhook: {e}")
        return web.Response(text="FAIL", status=500)

# Добавьте эти новые функции:

async def log_webhook_event(data: dict):
    """Логирует webhook событие в БД."""
    try:
        async with aiosqlite.connect(config.DATABASE_PATH) as db:
            # Создаем таблицу если не существует
            await db.execute("""
                CREATE TABLE IF NOT EXISTS webhook_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT,
                    payment_id TEXT,
                    status TEXT,
                    data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.execute("""
                INSERT INTO webhook_logs (order_id, payment_id, status, data)
                VALUES (?, ?, ?, ?)
            """, (
                data.get('OrderId'),
                data.get('PaymentId'),
                data.get('Status'),
                json.dumps(data, ensure_ascii=False)
            ))
            
            await db.commit()
            
    except Exception as e:
        logger.error(f"Error logging webhook event: {e}")

async def is_payment_processed(order_id: str, status: str) -> bool:
    """Проверяет, обработан ли уже платеж с таким статусом."""
    try:
        async with aiosqlite.connect(config.DATABASE_PATH) as db:
            cursor = await db.execute("""
                SELECT COUNT(*) FROM webhook_logs 
                WHERE order_id = ? AND status = ?
            """, (order_id, status))
            
            count = await cursor.fetchone()
            return count[0] > 1  # Если больше 1, значит уже обрабатывали
            
    except Exception as e:
        logger.error(f"Error checking payment processing: {e}")
        return False

async def notify_user_success(bot, order_id: str):
    """Уведомляет пользователя об успешной оплате."""
    try:
        subscription_manager = SubscriptionManager()
        payment_info = await subscription_manager.get_payment_by_order_id(order_id)
        
        if payment_info:
            plan_names = {
                'package_second_part': 'Вторая часть ЕГЭ',
                'package_full': 'Полный доступ',
                'trial_7days': 'Пробный период на 7 дней'
            }
            
            plan_name = plan_names.get(payment_info['plan_id'], payment_info['plan_id'])
            
            await bot.send_message(
                payment_info['user_id'],
                f"✅ Подписка «{plan_name}» успешно активирована!\n\n"
                f"Теперь вам доступны все материалы выбранного плана.\n"
                f"Приятной подготовки к ЕГЭ! 📚\n\n"
                f"Используйте /status для просмотра информации о подписке."
            )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

async def notify_user_rejected(bot, order_id: str):
    """Уведомляет об отклоненном платеже."""
    try:
        subscription_manager = SubscriptionManager()
        payment_info = await subscription_manager.get_payment_by_order_id(order_id)
        
        if payment_info:
            await bot.send_message(
                payment_info['user_id'],
                "❌ К сожалению, ваш платеж был отклонен банком.\n\n"
                "Возможные причины:\n"
                "• Недостаточно средств на карте\n"
                "• Превышен лимит операций\n"
                "• Карта заблокирована\n\n"
                "Попробуйте оплатить снова или используйте другую карту."
            )
    except Exception as e:
        logger.error(f"Failed to notify user about rejection: {e}")

async def notify_user_refunded(bot, order_id: str):
    """Уведомляет о возврате средств."""
    try:
        subscription_manager = SubscriptionManager()
        payment_info = await subscription_manager.get_payment_by_order_id(order_id)
        
        if payment_info:
            await bot.send_message(
                payment_info['user_id'],
                "💸 Произведен возврат средств по вашей подписке.\n\n"
                "Доступ к материалам приостановлен.\n"
                "Средства поступят на вашу карту в течение 3-5 рабочих дней."
            )
    except Exception as e:
        logger.error(f"Failed to notify user about refund: {e}")

async def notify_user_canceled(bot, order_id: str):
    """Уведомляет об отмененном платеже."""
    try:
        subscription_manager = SubscriptionManager()
        payment_info = await subscription_manager.get_payment_by_order_id(order_id)
        
        if payment_info:
            await bot.send_message(
                payment_info['user_id'],
                "⚠️ Платеж был отменен.\n\n"
                "Если вы хотите оформить подписку, "
                "попробуйте создать новый платеж."
            )
    except Exception as e:
        logger.error(f"Failed to notify user about cancellation: {e}")


def create_webhook_app(bot: Bot = None) -> web.Application:
    """Создает aiohttp приложение для webhook."""
    app = web.Application()
    app['bot'] = bot
    # ВАЖНО: путь должен быть /payment-notification
    app.router.add_post('/payment-notification', handle_webhook)  # Изменено!
    app.router.add_get('/health', health_check)
    return app

async def health_check(request: web.Request) -> web.Response:
    """Проверка работоспособности webhook сервера."""
    return web.Response(text='OK', status=200)

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