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
from collections import defaultdict
import time
from typing import Dict, List
from core import config
from .subscription_manager import SubscriptionManager
from .tinkoff import TinkoffPayment
from .admin_alerts import (
    notify_admin_payment_activation_failed,
    notify_admin_webhook_processing_error
)

logger = logging.getLogger(__name__)

# Глобальные переменные для webhook приложения
webhook_app = None
webhook_runner = None
webhook_site = None

# ==================== RATE LIMITING ====================
# Защита webhook от DDoS атак и спама
WEBHOOK_RATE_LIMIT_WINDOW = 60  # Окно в секундах (1 минута)
WEBHOOK_MAX_REQUESTS_PER_WINDOW = 60  # Максимум запросов за окно
_webhook_rate_limit_data: Dict[str, List[float]] = defaultdict(list)


def check_webhook_rate_limit(client_ip: str) -> tuple[bool, str]:
    """
    Проверяет rate limit для webhook запросов с конкретного IP.

    Args:
        client_ip: IP адрес клиента

    Returns:
        (allowed, message): allowed=True если запрос разрешен,
                           message содержит причину отказа если allowed=False
    """
    now = time.time()
    cutoff = now - WEBHOOK_RATE_LIMIT_WINDOW

    # Очищаем старые записи
    _webhook_rate_limit_data[client_ip] = [
        ts for ts in _webhook_rate_limit_data[client_ip]
        if ts > cutoff
    ]

    # Проверяем лимит
    request_count = len(_webhook_rate_limit_data[client_ip])

    if request_count >= WEBHOOK_MAX_REQUESTS_PER_WINDOW:
        logger.warning(
            f"⚠️  Rate limit exceeded for IP {client_ip}: "
            f"{request_count} requests in last {WEBHOOK_RATE_LIMIT_WINDOW}s"
        )
        return False, f"Rate limit exceeded: max {WEBHOOK_MAX_REQUESTS_PER_WINDOW} requests per minute"

    # Записываем новый запрос
    _webhook_rate_limit_data[client_ip].append(now)

    return True, ""


async def cleanup_rate_limit_data():
    """Периодически очищает старые данные rate limit."""
    while True:
        try:
            await asyncio.sleep(300)  # Каждые 5 минут
            now = time.time()
            cutoff = now - WEBHOOK_RATE_LIMIT_WINDOW

            # Очищаем данные старше окна
            ips_to_clean = []
            for ip, timestamps in _webhook_rate_limit_data.items():
                # Оставляем только свежие timestamp
                fresh = [ts for ts in timestamps if ts > cutoff]
                if fresh:
                    _webhook_rate_limit_data[ip] = fresh
                else:
                    ips_to_clean.append(ip)

            # Удаляем пустые записи
            for ip in ips_to_clean:
                del _webhook_rate_limit_data[ip]

            if ips_to_clean:
                logger.debug(f"Cleaned up rate limit data for {len(ips_to_clean)} IPs")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in rate limit cleanup: {e}")

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
    
    # Преобразуем булевые значения в строки с маленькой буквы
    for key, value in check_data.items():
        if isinstance(value, bool):
            check_data[key] = 'true' if value else 'false'

    # Сортируем по ключам и конкатенируем значения
    sorted_data = sorted(check_data.items())
    concat_values = ''.join(str(value) for key, value in sorted_data)

    # Вычисляем SHA256 и сравниваем
    calculated_token = hashlib.sha256(concat_values.encode()).hexdigest()
    is_valid = calculated_token.upper() == received_token.upper()

    if not is_valid:
        logger.warning(f"Signature verification failed for payment notification")

    return is_valid


def sanitize_webhook_data(data: dict) -> dict:
    """
    Маскирует чувствительные данные для безопасного логирования.

    Args:
        data: Данные webhook

    Returns:
        Словарь с замаскированными чувствительными полями
    """
    safe_data = data.copy()

    # Маскируем токен (оставляем только первые 10 символов)
    if 'Token' in safe_data and safe_data['Token']:
        token = str(safe_data['Token'])
        safe_data['Token'] = token[:10] + '...' if len(token) > 10 else '***'

    # Маскируем данные карты если есть
    if 'CardData' in safe_data:
        safe_data['CardData'] = '***MASKED***'

    # Маскируем RebillId (токен для рекуррентов)
    if 'RebillId' in safe_data and safe_data['RebillId']:
        rebill = str(safe_data['RebillId'])
        safe_data['RebillId'] = rebill[:8] + '...' if len(rebill) > 8 else '***'

    # Маскируем PAN (номер карты) если есть
    if 'Pan' in safe_data and safe_data['Pan']:
        safe_data['Pan'] = '****' + str(safe_data['Pan'])[-4:] if len(str(safe_data['Pan'])) > 4 else '****'

    return safe_data


async def handle_webhook(request: web.Request) -> web.Response:
    """Обработчик webhook от Tinkoff с полной защитой от дублирования."""
    try:
        # НОВОЕ: Проверяем rate limit для защиты от DDoS
        client_ip = request.remote or 'unknown'
        allowed, error_msg = check_webhook_rate_limit(client_ip)

        if not allowed:
            logger.warning(f"🚫 Rate limit blocked request from {client_ip}")
            return web.Response(text='RATE_LIMIT_EXCEEDED', status=429)

        # Получаем данные
        data = await request.json()

        # ИСПРАВЛЕНИЕ: Маскируем чувствительные данные перед логированием
        logger.info(f"Webhook received: {json.dumps(sanitize_webhook_data(data), ensure_ascii=False)}")

        # Проверяем подпись
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

        if not all([order_id, status]):
            logger.error(f"Missing required fields: OrderId={order_id}, Status={status}")
            return web.Response(text='MISSING_FIELDS', status=400)

        logger.info(f"Processing payment: order={order_id}, status={status}, payment_id={payment_id}")

        # Проверяем, не обработали ли мы уже этот webhook
        async with aiosqlite.connect(config.DATABASE_PATH) as db:
            # ИСПРАВЛЕНИЕ: Таблицы webhook_logs и notification_history создаются через миграции
            # (см. payment/apply_payment_migrations.py)
            # Это предотвращает создание таблиц при каждом webhook запросе

            # Флаг, указывающий, является ли это дубликатом webhook
            is_duplicate = False

            # Пытаемся вставить запись о webhook
            try:
                await db.execute(
                    """
                    INSERT INTO webhook_logs (order_id, status, payment_id, raw_data)
                    VALUES (?, ?, ?, ?)
                    """,
                    (order_id, status, payment_id, json.dumps(data))
                )
                await db.commit()
            except aiosqlite.IntegrityError:
                # Если запись уже существует - webhook дублируется
                logger.info(f"Duplicate webhook detected for order {order_id} with status {status}")
                is_duplicate = True
        
        # Получаем subscription_manager
        subscription_manager = SubscriptionManager()

        # Обрабатываем успешные статусы
        if status in ['AUTHORIZED', 'CONFIRMED']:
            logger.info(f"Payment {order_id} confirmed with status {status}")

            # ИСПРАВЛЕНИЕ: Для дубликатов webhook проверяем, была ли успешная активация
            if is_duplicate:
                is_already_activated = await subscription_manager.is_payment_already_activated(order_id)
                if is_already_activated:
                    logger.info(f"Duplicate webhook for already activated payment {order_id}. Returning OK.")
                    return web.Response(text='OK')
                else:
                    logger.warning(
                        f"Duplicate webhook for order {order_id}, but payment not fully activated. "
                        f"Retrying activation..."
                    )

            # Активируем подписку (или повторно активируем если предыдущая попытка не удалась)
            success = await subscription_manager.activate_subscription(
                order_id=order_id,
                payment_id=payment_id
            )

            if success:
                logger.info(f"✅ Payment {order_id} successfully activated")

                # Трекинг конверсии из retention уведомлений
                try:
                    # Получаем user_id, metadata и amount из платежа
                    import aiosqlite
                    async with aiosqlite.connect(subscription_manager.database_file) as db:
                        cursor = await db.execute("""
                            SELECT user_id, metadata, amount_kopecks FROM payments
                            WHERE order_id = ?
                        """, (order_id,))
                        payment_row = await cursor.fetchone()

                        if payment_row:
                            user_id = payment_row[0]
                            metadata_str = payment_row[1]
                            amount_kopecks = payment_row[2]

                            # Извлекаем promo_code из metadata (JSON string)
                            promo_code = None
                            if metadata_str:
                                import json
                                try:
                                    metadata = json.loads(metadata_str)
                                    promo_code = metadata.get('promo_code')
                                except:
                                    pass

                            # Трекинг конверсии (retention notifications)
                            from core.notification_handlers import track_notification_conversion
                            await track_notification_conversion(user_id, promo_code)
                            logger.info(f"Tracked conversion for user {user_id} with promo {promo_code}")

                            # Трекинг конверсии для UTM-аналитики (реклама)
                            try:
                                # Определяем тип конверсии и сумму
                                plan_id = metadata.get('plan_id', '') if metadata_str else ''
                                amount_rub = amount_kopecks / 100 if amount_kopecks else 0

                                conversion_type = 'subscription_purchase'
                                if 'trial' in plan_id.lower():
                                    conversion_type = 'trial_purchase'

                                from analytics.utm_tracker import track_conversion
                                await track_conversion(
                                    user_id=user_id,
                                    conversion_type=conversion_type,
                                    value=amount_rub,
                                    metadata={'order_id': order_id, 'plan_id': plan_id}
                                )
                                logger.info(f"Tracked {conversion_type} conversion for user {user_id}, amount: {amount_rub}₽")
                            except Exception as utm_err:
                                logger.error(f"Failed to track UTM conversion: {utm_err}")

                except Exception as e:
                    # Не падаем если трекинг не сработал
                    logger.error(f"Failed to track conversion for {order_id}: {e}")

                # Отправляем уведомление только если оно еще не было отправлено
                bot = request.app.get('bot')
                if bot:
                    await notify_user_success_safe(bot, order_id)

                return web.Response(text='OK')
            else:
                logger.error(f"Failed to activate subscription for order {order_id}")

                # Уведомляем админа о критичной ошибке активации
                bot = request.app.get('bot')
                if bot and not is_duplicate:
                    # Получаем информацию о платеже для алерта
                    async with aiosqlite.connect(config.DATABASE_PATH) as db:
                        cursor = await db.execute(
                            "SELECT user_id, plan_id, amount FROM payments WHERE order_id = ?",
                            (order_id,)
                        )
                        payment_info = await cursor.fetchone()
                        if payment_info:
                            user_id, plan_id, amount = payment_info
                            await notify_admin_payment_activation_failed(
                                bot=bot,
                                order_id=order_id,
                                user_id=user_id,
                                plan_id=plan_id,
                                amount=amount // 100 if amount else 0,  # Конвертируем из копеек
                                error="Subscription activation failed"
                            )

                # ИСПРАВЛЕНИЕ: Возвращаем OK даже если активация не удалась для дубликата
                # чтобы не вызывать бесконечные повторы от Tinkoff
                if is_duplicate:
                    logger.error(
                        f"Duplicate webhook: Activation failed for {order_id}. "
                        f"Returning OK to prevent infinite retries."
                    )
                    return web.Response(text='OK')
                else:
                    # Для первого webhook возвращаем ошибку, чтобы Tinkoff повторил
                    return web.Response(text='ACTIVATION_FAILED', status=500)
        
        elif status in ['REJECTED', 'CANCELED']:
            logger.warning(f"Payment {order_id} rejected/canceled")
            await subscription_manager.update_payment_status(order_id, 'failed')

            bot = request.app.get('bot')
            if bot:
                if status == 'REJECTED':
                    await notify_user_rejected(bot, order_id)
                else:
                    await notify_user_canceled(bot, order_id)

            return web.Response(text='OK')
        
        else:
            logger.info(f"Payment {order_id} status update: {status}")
            return web.Response(text='OK')
            
    except Exception as e:
        logger.exception(f"Webhook processing error: {e}")
        return web.Response(text='INTERNAL_ERROR', status=500)

async def is_payment_already_processed(order_id: str, status: str) -> bool:
    """Проверяет, был ли уже обработан платеж с таким статусом."""
    try:
        from core.db import DATABASE_FILE
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM payments 
                WHERE order_id = ? AND status = 'confirmed'
                """,
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
            # ИСПРАВЛЕНИЕ: Таблица создается через миграции (apply_payment_migrations.py)
            # а не при каждом логировании webhook

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

async def notify_user_success_safe(bot, order_id: str):
    """Отправляет уведомление об успешной оплате с защитой от дублирования."""
    import aiosqlite
    
    try:
        # Проверяем и записываем факт отправки уведомления
        async with aiosqlite.connect(config.DATABASE_PATH) as db:
            # Получаем информацию о платеже
            cursor = await db.execute(
                "SELECT user_id, plan_id FROM payments WHERE order_id = ?",
                (order_id,)
            )
            payment_info = await cursor.fetchone()
            
            if not payment_info:
                logger.error(f"Payment info not found for order {order_id}")
                return
            
            user_id, plan_id = payment_info
            
            # Пытаемся вставить запись об уведомлении
            try:
                await db.execute(
                    """
                    INSERT INTO notification_history (user_id, order_id, notification_type)
                    VALUES (?, ?, 'success')
                    """,
                    (user_id, order_id)
                )
                await db.commit()
            except aiosqlite.IntegrityError:
                # Уведомление уже было отправлено
                logger.info(f"Success notification for order {order_id} already sent")
                return
        
        # Если дошли сюда - уведомление еще не отправлялось
        subscription_manager = SubscriptionManager()
        subscription_info = await subscription_manager.get_subscription_info(user_id)
        
        from .config import SUBSCRIPTION_PLANS
        plan = SUBSCRIPTION_PLANS.get(plan_id, {})
        plan_name = plan.get('name', plan_id)
        
        # Формируем сообщение
        message = f"✅ <b>Оплата прошла успешно!</b>\n\n"
        message += f"План: {plan_name}\n"
        
        if subscription_info and subscription_info.get('type') == 'modular':
            modules = subscription_info.get('modules', [])
            if modules:
                message += "\n<b>Активированные модули:</b>\n"
                for module in modules:
                    message += f"• {module}\n"
        
        if subscription_info and subscription_info.get('expires_at'):
            message += f"\n📅 Действует до: {subscription_info['expires_at'].strftime('%d.%m.%Y')}\n"
        
        message += "\n🎉 Теперь вам доступны все материалы выбранного плана!"
        message += "\n\nИспользуйте /my_subscriptions для просмотра деталей."
        
        # Отправляем сообщение
        await bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode='HTML'
        )
        
        logger.info(f"Successfully notified user {user_id} about payment {order_id}")
        
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
    """Отправляет уведомление об отклоненном платеже с защитой от дублирования."""
    import aiosqlite
    
    try:
        async with aiosqlite.connect(config.DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT user_id FROM payments WHERE order_id = ?",
                (order_id,)
            )
            result = await cursor.fetchone()
            
            if not result:
                return
            
            user_id = result[0]
            
            # Проверяем дублирование
            try:
                await db.execute(
                    """
                    INSERT INTO notification_history (user_id, order_id, notification_type)
                    VALUES (?, ?, 'rejected')
                    """,
                    (user_id, order_id)
                )
                await db.commit()
            except aiosqlite.IntegrityError:
                return
        
        await bot.send_message(
            user_id,
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
    """Отправляет уведомление об отмененном платеже с защитой от дублирования."""
    import aiosqlite
    
    try:
        async with aiosqlite.connect(config.DATABASE_PATH) as db:
            cursor = await db.execute(
                "SELECT user_id FROM payments WHERE order_id = ?",
                (order_id,)
            )
            result = await cursor.fetchone()
            
            if not result:
                return
            
            user_id = result[0]
            
            # Проверяем дублирование
            try:
                await db.execute(
                    """
                    INSERT INTO notification_history (user_id, order_id, notification_type)
                    VALUES (?, ?, 'canceled')
                    """,
                    (user_id, order_id)
                )
                await db.commit()
            except aiosqlite.IntegrityError:
                return
        
        await bot.send_message(
            user_id,
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
    """Запускает webhook сервер с rate limiting и cleanup."""
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

        # НОВОЕ: Запускаем фоновую задачу очистки rate limit данных
        asyncio.create_task(cleanup_rate_limit_data())
        logger.info("✅ Rate limit cleanup task started")

        # Создаем и запускаем runner
        webhook_runner = web.AppRunner(webhook_app)
        await webhook_runner.setup()

        # Запускаем сайт
        webhook_site = web.TCPSite(webhook_runner, '0.0.0.0', port)
        await webhook_site.start()

        logger.info(f"🚀 Webhook server started on port {port}")
        logger.info(f"🛡️  Rate limiting enabled: max {WEBHOOK_MAX_REQUESTS_PER_WINDOW} requests per {WEBHOOK_RATE_LIMIT_WINDOW}s")
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