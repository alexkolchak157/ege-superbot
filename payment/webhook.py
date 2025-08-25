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
    
    # ИСПРАВЛЕНИЕ: Преобразуем булевые значения в строки с маленькой буквы
    for key, value in check_data.items():
        if isinstance(value, bool):
            check_data[key] = 'true' if value else 'false'
    
    # ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ
    logger.info(f"=== SIGNATURE VERIFICATION DEBUG ===")
    logger.info(f"Secret key: {secret_key[:4]}...{secret_key[-4:]}")
    logger.info(f"Terminal key: {terminal_key}")
    logger.info(f"Received token: {received_token}")
    
    # Логируем все поля для проверки
    logger.info("Fields for signature:")
    for key, value in sorted(check_data.items()):
        logger.info(f"  {key}: {value} (type: {type(value).__name__})")
    
    # Сортируем по ключам
    sorted_data = sorted(check_data.items())
    
    # Конкатенируем значения
    concat_values = ''.join(str(value) for key, value in sorted_data)
    
    # Логируем конкатенированную строку
    logger.info(f"Concatenated string: {concat_values}")
    logger.info(f"String length: {len(concat_values)}")
    
    # Вычисляем SHA256
    calculated_token = hashlib.sha256(concat_values.encode()).hexdigest()
    
    # Сравниваем токены
    logger.info(f"Calculated token: {calculated_token.upper()}")
    logger.info(f"Received token:   {received_token.upper()}")
    logger.info(f"Tokens match: {calculated_token.upper() == received_token.upper()}")
    logger.info(f"=== END DEBUG ===")
    
    return calculated_token.upper() == received_token.upper()


async def handle_webhook(request: web.Request) -> web.Response:
    """Обрабатывает webhook от Т-Банка (исправленная версия)."""
    try:
        # Получаем данные
        data = await request.json()
        logger.info(f"Webhook received: {json.dumps(data, ensure_ascii=False)}")
        
        # ИСПРАВЛЕНИЕ: используем правильную функцию и передаем нужные параметры
        if not verify_tinkoff_signature(
            data, 
            data.get('Token', ''),
            config.TINKOFF_TERMINAL_KEY,
            config.TINKOFF_SECRET_KEY
        ):
            logger.error("Invalid webhook signature")
            return web.Response(text='INVALID_SIGNATURE', status=400)
        
        # Извлекаем данные
        order_id = data.get('OrderId')
        status = data.get('Status')
        payment_id = data.get('PaymentId')
        rebill_id = data.get('RebillId')  # Получаем RebillId для автопродления
        
        if not all([order_id, status]):
            logger.error(f"Missing required fields: OrderId={order_id}, Status={status}")
            return web.Response(text='MISSING_FIELDS', status=400)
        
        # Логируем в БД
        await log_webhook(data)
        
        # Проверяем, не обрабатывали ли уже этот webhook
        if await is_payment_already_processed(order_id, status):
            logger.info(f"Payment {order_id} with status {status} already processed")
            return web.Response(text='OK')
        
        # Получаем subscription_manager
        subscription_manager = SubscriptionManager()
        
        # Обрабатываем различные статусы
        if status in ['AUTHORIZED', 'CONFIRMED']:
            logger.info(f"Payment {order_id} confirmed with status {status}")
            
            # Активируем подписку
            success = await subscription_manager.activate_subscription(order_id)
            
            if success:
                # Если есть RebillId, сохраняем его для автопродления
                if rebill_id:
                    # Получаем user_id из платежа
                    payment_info = await subscription_manager.get_payment_by_order_id(order_id)
                    if payment_info:
                        user_id = payment_info.get('user_id')
                        if user_id:
                            await handle_rebill_id(order_id, rebill_id, user_id)
                            logger.info(f"RebillId saved for user {user_id}")
                
                # Уведомляем пользователя об успешной оплате
                bot = request.app.get('bot')
                if bot:
                    await notify_user_success(bot, order_id)
                    
                return web.Response(text='OK')
            else:
                logger.error(f"Failed to activate subscription for order {order_id}")
                return web.Response(text='ACTIVATION_FAILED', status=500)
        
        elif status in ['REJECTED', 'CANCELED']:
            logger.warning(f"Payment {order_id} rejected/canceled with status {status}")
            # Обновляем статус платежа
            await subscription_manager.update_payment_status(order_id, 'failed')
            
            # Уведомляем пользователя об отмене
            bot = request.app.get('bot')
            if bot:
                await notify_user_failed(bot, order_id)
            
            return web.Response(text='OK')
        
        else:
            # Другие статусы просто логируем
            logger.info(f"Payment {order_id} status update: {status}")
            return web.Response(text='OK')
            
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in webhook: {e}")
        return web.Response(text='INVALID_JSON', status=400)
    except Exception as e:
        logger.exception(f"Webhook processing error: {e}")
        return web.Response(text='INTERNAL_ERROR', status=500)

async def is_payment_already_processed(order_id: str, status: str) -> bool:
    """Проверяет, был ли уже обработан платеж."""
    try:
        from core.db import DATABASE_FILE
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM payments WHERE order_id = ? AND status = 'confirmed'",
                (order_id,)
            )
            count = await cursor.fetchone()
            return count[0] > 0 if count else False
    except Exception as e:
        logger.error(f"Error checking payment: {e}")
        return False

async def notify_user_failed(bot, order_id: str):
    """Уведомляет пользователя об отмене платежа."""
    try:
        user_id = int(order_id.split('_')[0])
        if bot:
            await bot.send_message(
                chat_id=user_id,
                text="❌ Платеж был отменен или отклонен.\n\nПопробуйте оформить подписку заново."
            )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

async def log_webhook(data: dict):
    """Логирует webhook для отладки (упрощенная версия)."""
    logger.info(f"Webhook log: OrderId={data.get('OrderId')}, Status={data.get('Status')}, PaymentId={data.get('PaymentId')}")
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
        
        if not payment_info:
            logger.error(f"Payment info not found for order {order_id}")
            return
            
        # Получаем информацию о плане
        from .config import SUBSCRIPTION_PLANS
        plan = SUBSCRIPTION_PLANS.get(payment_info['plan_id'], {})
        plan_name = plan.get('name', payment_info['plan_id'])
        
        # Формируем сообщение в зависимости от типа подписки
        message = f"✅ <b>Оплата прошла успешно!</b>\n\n"
        message += f"План: {plan_name}\n"
        
        # Получаем детальную информацию о подписке
        subscription_info = await subscription_manager.get_subscription_info(payment_info['user_id'])
        
        if subscription_info and subscription_info.get('type') == 'modular':
            # Модульная подписка
            modules = subscription_info.get('modules', [])
            if modules:
                message += "\n<b>Активированные модули:</b>\n"
                module_names = {
                    'test_part': '📝 Тестовая часть',
                    'task19': '🎯 Задание 19',
                    'task20': '📖 Задание 20',
                    'task24': '💎 Задание 24',
                    'task25': '✍️ Задание 25'
                }
                for module in modules:
                    message += f"• {module_names.get(module, module)}\n"
        
        if subscription_info and subscription_info.get('expires_at'):
            message += f"\n📅 Действует до: {subscription_info['expires_at'].strftime('%d.%m.%Y')}\n"
        
        message += "\n🎉 Теперь вам доступны все материалы выбранного плана!"
        message += "\n\nИспользуйте /my_subscriptions для просмотра деталей."
        
        # Отправляем сообщение
        await bot.send_message(
            chat_id=payment_info['user_id'],
            text=message,
            parse_mode='HTML'
        )
        
        logger.info(f"Successfully notified user {payment_info['user_id']} about payment {order_id}")
        
    except Exception as e:
        logger.exception(f"Failed to notify user about successful payment: {e}")

async def handle_rebill_id(order_id: str, rebill_id: str, user_id: int):
    """
    ОБНОВЛЕННАЯ версия - обрабатывает и сохраняет RebillId с активацией автопродления.
    
    Args:
        order_id: ID заказа
        rebill_id: Токен для рекуррентных платежей
        user_id: ID пользователя
    """
    try:
        from .subscription_manager import SubscriptionManager
        import json
        
        subscription_manager = SubscriptionManager()
        
        # Сохраняем RebillId в БД
        await subscription_manager.save_rebill_id(user_id, order_id, rebill_id)
        
        # Получаем информацию о платеже
        payment_info = await subscription_manager.get_payment_by_order_id(order_id)
        
        if payment_info:
            # Проверяем метаданные платежа
            metadata = json.loads(payment_info.get('metadata', '{}'))
            
            # Если пользователь дал согласие на автопродление
            if metadata.get('enable_auto_renewal'):
                # Активируем автопродление
                success = await subscription_manager.enable_auto_renewal(
                    user_id=user_id,
                    payment_method='recurrent',
                    recurrent_token=rebill_id
                )
                
                if success:
                    logger.info(f"Auto-renewal enabled for user {user_id} with RebillId")
                    
                    # Отправляем уведомление пользователю (если есть bot в контексте)
                    # Это нужно добавить в handle_tinkoff_webhook
                    return True
                else:
                    logger.error(f"Failed to enable auto-renewal for user {user_id}")
            else:
                logger.info(f"RebillId saved but auto-renewal not requested by user {user_id}")
        
        logger.info(f"RebillId processed for order {order_id}, user {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling rebill_id: {e}")

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
    
    # ИСПРАВЛЕНИЕ: Добавляем несколько путей для совместимости
    # Основной путь
    app.router.add_post('/payment/webhook', handle_webhook)
    # Альтернативные пути для обратной совместимости
    app.router.add_post('/webhook', handle_webhook)
    app.router.add_post('/payment-notification', handle_webhook)
    
    # Health check
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
        logger.info("Webhook paths registered:")
        logger.info("  - /payment/webhook (основной)")
        logger.info("  - /webhook (альтернативный)")
        logger.info("  - /payment-notification (legacy)")
        
        # Логируем webhook URL для настройки в Tinkoff
        if hasattr(config, 'WEBHOOK_BASE_URL'):
            logger.info(f"Webhook URLs for Tinkoff:")
            logger.info(f"  Primary: {config.WEBHOOK_BASE_URL}/payment/webhook")
            logger.info(f"  Alternative: {config.WEBHOOK_BASE_URL}/webhook")
        
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