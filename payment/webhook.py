# payment/webhook.py
"""Webhook сервер для обработки уведомлений от Tinkoff."""
import json
import logging
from datetime import datetime
from aiohttp import web

from telegram import Bot

from core.config import BOT_TOKEN
from .config import PAYMENT_ADMIN_CHAT_ID, WEBHOOK_PATH
from .subscription_manager import SubscriptionManager
from .tinkoff import TinkoffPayment

logger = logging.getLogger(__name__)

# Инициализация
subscription_manager = SubscriptionManager()
tinkoff_payment = TinkoffPayment()
bot = Bot(token=BOT_TOKEN)

routes = web.RouteTableDef()


@routes.post(WEBHOOK_PATH)
async def handle_payment_webhook(request: web.Request):
    """Обработчик webhook от Tinkoff."""
    try:
        # Получаем данные
        data = await request.json()
        logger.info(f"Received webhook: {json.dumps(data, ensure_ascii=False)}")
        
        # Проверяем подпись
        if not tinkoff_payment.verify_webhook_token(data):
            logger.warning("Invalid webhook signature")
            return web.Response(status=403, text="Invalid signature")
        
        # Извлекаем данные
        status = data.get("Status")
        order_id = data.get("OrderId")
        payment_id = data.get("PaymentId")
        amount = data.get("Amount", 0)
        
        # Обрабатываем только успешные платежи
        if status in ["CONFIRMED", "AUTHORIZED"]:
            logger.info(f"Payment confirmed: {order_id}")
            
            # Активируем подписку
            success = await subscription_manager.confirm_payment(order_id, payment_id)
            
            if success:
                # Получаем данные пользователя из DATA
                user_data = data.get("DATA", {})
                user_id = int(user_data.get("user_id", 0))
                plan_id = user_data.get("plan_id", "unknown")
                
                if user_id:
                    # Отправляем уведомление пользователю
                    try:
                        from .config import SUBSCRIPTION_PLANS
                        plan = SUBSCRIPTION_PLANS.get(plan_id, {})
                        
                        user_text = f"""✅ <b>Оплата прошла успешно!</b>

Ваша подписка "{plan.get('name', 'Premium')}" активирована.
Спасибо за доверие!

Используйте /status для просмотра информации о подписке."""
                        
                        await bot.send_message(
                            user_id,
                            user_text,
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify user {user_id}: {e}")
                
                # Уведомляем админа
                if PAYMENT_ADMIN_CHAT_ID:
                    admin_text = f"""✅ Платеж подтвержден:
                    
Order: {order_id}
User: {user_id}
План: {plan_id}
Сумма: {amount / 100} ₽"""
                    
                    try:
                        await bot.send_message(PAYMENT_ADMIN_CHAT_ID, admin_text)
                    except Exception as e:
                        logger.error(f"Failed to notify admin: {e}")
            else:
                logger.error(f"Failed to activate subscription for order {order_id}")
        
        elif status in ["REFUNDED", "PARTIAL_REFUNDED"]:
            logger.info(f"Payment refunded: {order_id}")
            
            # Здесь можно добавить логику отмены подписки при возврате
            # user_id = ... получить из БД по order_id
            # await subscription_manager.cancel_subscription(user_id)
        
        # Всегда отвечаем OK для Tinkoff
        return web.Response(status=200, text="OK")
        
    except Exception as e:
        logger.exception(f"Error processing webhook: {e}")
        # Даже при ошибке отвечаем 200, чтобы Tinkoff не повторял запрос
        return web.Response(status=200, text="OK")


@routes.get('/payment/success')
async def handle_payment_success(request: web.Request):
    """Страница успешной оплаты."""
    order_id = request.query.get('order', 'unknown')
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Оплата успешна</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background-color: #f0f2f5;
            }}
            .container {{
                text-align: center;
                padding: 40px;
                background: white;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            .success-icon {{
                font-size: 64px;
                color: #4CAF50;
                margin-bottom: 20px;
            }}
            h1 {{
                color: #333;
                margin-bottom: 10px;
            }}
            p {{
                color: #666;
                margin-bottom: 30px;
            }}
            .button {{
                display: inline-block;
                padding: 12px 30px;
                background-color: #0088cc;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                transition: background-color 0.3s;
            }}
            .button:hover {{
                background-color: #0077b5;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="success-icon">✅</div>
            <h1>Оплата прошла успешно!</h1>
            <p>Заказ: {order_id}</p>
            <p>Ваша подписка активирована. Вернитесь в Telegram для продолжения работы.</p>
            <a href="https://t.me/{(await bot.get_me()).username}" class="button">Вернуться в бот</a>
        </div>
    </body>
    </html>
    """
    
    return web.Response(text=html, content_type='text/html')


@routes.get('/payment/fail')
async def handle_payment_fail(request: web.Request):
    """Страница неудачной оплаты."""
    order_id = request.query.get('order', 'unknown')
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Ошибка оплаты</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background-color: #f0f2f5;
            }}
            .container {{
                text-align: center;
                padding: 40px;
                background: white;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            .error-icon {{
                font-size: 64px;
                color: #f44336;
                margin-bottom: 20px;
            }}
            h1 {{
                color: #333;
                margin-bottom: 10px;
            }}
            p {{
                color: #666;
                margin-bottom: 30px;
            }}
            .button {{
                display: inline-block;
                padding: 12px 30px;
                background-color: #0088cc;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                transition: background-color 0.3s;
            }}
            .button:hover {{
                background-color: #0077b5;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="error-icon">❌</div>
            <h1>Оплата не завершена</h1>
            <p>Заказ: {order_id}</p>
            <p>Платеж был отменен или произошла ошибка. Попробуйте еще раз.</p>
            <a href="https://t.me/{(await bot.get_me()).username}" class="button">Вернуться в бот</a>
        </div>
    </body>
    </html>
    """
    
    return web.Response(text=html, content_type='text/html')


async def start_webhook_server(host='0.0.0.0', port=8080):
    """Запускает webhook сервер."""
    # Инициализируем таблицы БД
    await subscription_manager.init_tables()
    
    app = web.Application()
    app.add_routes(routes)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    
    logger.info(f"Starting webhook server on {host}:{port}")
    await site.start()
    
    return runner