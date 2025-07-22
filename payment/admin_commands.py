# payment/admin_commands.py
"""Админские команды для управления подписками."""
import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, Application
from telegram.constants import ParseMode
from functools import wraps

from core import config
from .subscription_manager import SubscriptionManager

logger = logging.getLogger(__name__)


def admin_only(func):
    """Декоратор для проверки админских прав."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Проверяем список админов
        admin_ids = []
        if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
            if isinstance(config.ADMIN_IDS, str):
                admin_ids = [int(id.strip()) for id in config.ADMIN_IDS.split(',') if id.strip()]
            elif isinstance(config.ADMIN_IDS, list):
                admin_ids = [int(id) for id in config.ADMIN_IDS]
        
        if user_id not in admin_ids:
            await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
            return
        
        return await func(update, context)
    
    return wrapper

@admin_only
async def cmd_test_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестирует webhook, отправляя тестовый запрос."""
    import aiohttp
    
    # Создаем тестовый платеж
    test_order_id = f"TEST_{int(datetime.now().timestamp())}"
    user_id = update.effective_user.id
    
    subscription_manager = context.bot_data.get('subscription_manager')
    
    # Создаем запись о платеже
    await subscription_manager.create_payment(
        user_id=user_id,
        plan_id='trial_7days',
        amount_kopecks=100
    )
    
    # Симулируем webhook от Tinkoff
    webhook_data = {
        "TerminalKey": config.TINKOFF_TERMINAL_KEY,
        "OrderId": test_order_id,
        "Status": "CONFIRMED",
        "PaymentId": "12345",
        "Token": "test_token"  # В реальности нужен правильный токен
    }
    
    webhook_url = f"http://localhost:8080/webhook"  # Или ваш webhook URL
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=webhook_data) as response:
                result = await response.text()
                status = response.status
        
        await update.message.reply_text(
            f"🧪 Тест webhook:\n"
            f"Status: {status}\n"
            f"Response: {result}\n"
            f"Order ID: {test_order_id}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка теста: {e}")


@admin_only
async def cmd_grant_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдает подписку пользователю вручную. Использование: /grant_subscription <user_id> <plan_id>"""
    # Импортируем здесь, если не импортировано выше
    from .config import SUBSCRIPTION_PLANS, SUBSCRIPTION_MODE
    from datetime import datetime
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /grant_subscription <user_id> <plan_id>\n\n"
            "Доступные планы:\n"
            "• trial_7days - пробный период\n"
            "• package_second_part - пакет 'Вторая часть'\n"
            "• package_full - полный доступ\n"
            "• module_test_part - только тестовая часть\n"
            "• module_task19 - только задание 19\n"
            "• module_task20 - только задание 20\n"
            "• module_task25 - только задание 25\n"
            "• module_task24 - только задание 24"
        )
        return
    
    try:
        user_id = int(context.args[0])
        plan_id = context.args[1]
        
        # Проверяем, существует ли план
        if plan_id not in SUBSCRIPTION_PLANS:
            await update.message.reply_text(f"❌ Неизвестный план: {plan_id}")
            return
        
        subscription_manager = context.bot_data.get('subscription_manager')
        if not subscription_manager:
            # Создаем новый экземпляр если не найден
            from .subscription_manager import SubscriptionManager
            subscription_manager = SubscriptionManager()
        
        # Создаем фиктивный payment_id
        payment_id = f"ADMIN_GRANT_{int(datetime.now().timestamp())}"
        
        # Активируем подписку
        try:
            if SUBSCRIPTION_MODE == 'modular':
                await subscription_manager._activate_modular_subscription(user_id, plan_id, payment_id)
            else:
                await subscription_manager._activate_unified_subscription(user_id, plan_id, payment_id)
        except Exception as e:
            logger.error(f"Error activating subscription: {e}")
            await update.message.reply_text(f"❌ Ошибка при активации: {e}")
            return
        
        # Получаем информацию о подписке
        subscription_info = await subscription_manager.get_subscription_info(user_id)
        
        text = f"✅ Подписка выдана успешно!\n\n"
        text += f"Пользователь: {user_id}\n"
        text += f"План: {SUBSCRIPTION_PLANS[plan_id]['name']}\n"
        
        if subscription_info:
            if SUBSCRIPTION_MODE == 'modular':
                modules = subscription_info.get('modules', [])
                if modules:
                    text += f"Модули: {', '.join(modules)}\n"
            text += f"Действует до: {subscription_info.get('expires_at')}"
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        
        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                user_id,
                f"🎁 Вам выдана подписка!\n\n"
                f"План: {SUBSCRIPTION_PLANS[plan_id]['name']}\n"
                f"Используйте /my_subscriptions для просмотра деталей."
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")
            await update.message.reply_text(
                f"⚠️ Подписка активирована, но не удалось отправить уведомление пользователю"
            )
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат user_id. Используйте числовой ID.")
    except Exception as e:
        logger.exception(f"Error granting subscription: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

@admin_only
async def cmd_check_user_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет подписку конкретного пользователя. Использование: /check_user_subscription <user_id>"""
    if not context.args:
        await update.message.reply_text(
            "Использование: /check_user_subscription <user_id>\n"
            "Например: /check_user_subscription 7390670490"
        )
        return
    
    try:
        user_id = int(context.args[0])
        subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
        
        text = f"🔍 <b>Проверка подписки для пользователя {user_id}</b>\n\n"
        
        # Проверяем общую подписку
        subscription = await subscription_manager.check_active_subscription(user_id)
        if subscription:
            text += "✅ <b>Активная подписка найдена:</b>\n"
            text += f"План: {subscription.get('plan_id')}\n"
            text += f"Истекает: {subscription.get('expires_at')}\n"
            
            if SUBSCRIPTION_MODE == 'modular':
                text += f"Активные модули: {', '.join(subscription.get('active_modules', []))}\n"
        else:
            text += "❌ <b>Активная подписка не найдена</b>\n"
        
        # Проверяем модули (если модульная система)
        if SUBSCRIPTION_MODE == 'modular':
            text += "\n📦 <b>Проверка доступа к модулям:</b>\n"
            modules = await subscription_manager.get_user_modules(user_id)
            
            if modules:
                for module in modules:
                    text += f"• {module['module_code']} до {module['expires_at']}\n"
            else:
                text += "Нет активных модулей\n"
        
        # Проверяем историю платежей
        text += "\n💳 <b>История платежей:</b>\n"
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                cursor = await conn.execute(
                    """
                    SELECT order_id, plan_id, status, amount_kopecks, created_at 
                    FROM payments 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT 5
                    """,
                    (user_id,)
                )
                payments = await cursor.fetchall()
                
                if payments:
                    for payment in payments:
                        order_id, plan_id, status, amount, created_at = payment
                        text += f"• {plan_id} - {status} - {amount/100:.2f}₽ ({created_at})\n"
                else:
                    text += "Нет платежей\n"
        except Exception as e:
            logger.error(f"Error getting payment history: {e}")
            text += f"Ошибка при получении истории: {e}\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат user_id")
    except Exception as e:
        logger.exception(f"Error checking user subscription: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

@admin_only
async def cmd_revoke_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отзывает подписку у пользователя."""
    if not context.args:
        await update.message.reply_text("Использование: /revoke <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        
        subscription_manager = SubscriptionManager()
        success = await subscription_manager.cancel_subscription(user_id)
        
        if success:
            await update.message.reply_text(
                f"✅ Подписка пользователя {user_id} отозвана"
            )
        else:
            await update.message.reply_text("❌ Ошибка при отзыве подписки")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный ID пользователя")
    except Exception as e:
        logger.exception(f"Error revoking subscription: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

@admin_only
async def cmd_activate_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активирует pending платеж вручную. Использование: /activate_payment <order_id>"""
    if not context.args:
        # Показываем список pending платежей
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                cursor = await conn.execute(
                    """
                    SELECT order_id, user_id, plan_id, amount_kopecks, created_at
                    FROM payments 
                    WHERE status = 'pending'
                    ORDER BY created_at DESC
                    LIMIT 10
                    """
                )
                pending_payments = await cursor.fetchall()
                
                if not pending_payments:
                    await update.message.reply_text("✅ Нет неподтвержденных платежей")
                    return
                
                text = "⚠️ <b>Неподтвержденные платежи:</b>\n\n"
                for payment in pending_payments:
                    order_id, user_id, plan_id, amount, created_at = payment
                    text += f"<code>{order_id}</code>\n"
                    text += f"├ User: {user_id}\n"
                    text += f"├ План: {plan_id}\n"
                    text += f"├ Сумма: {amount/100:.2f} руб.\n"
                    text += f"└ Создан: {created_at}\n\n"
                
                text += "Для активации используйте:\n"
                text += "<code>/activate_payment ORDER_ID</code>"
                
                await update.message.reply_text(text, parse_mode=ParseMode.HTML)
                
        except Exception as e:
            logger.error(f"Error listing pending payments: {e}")
            await update.message.reply_text(f"❌ Ошибка: {e}")
        return
    
    order_id = context.args[0]
    
    try:
        subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
        
        # Проверяем, существует ли платеж
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            cursor = await conn.execute(
                "SELECT user_id, plan_id, status FROM payments WHERE order_id = ?",
                (order_id,)
            )
            payment = await cursor.fetchone()
            
            if not payment:
                await update.message.reply_text(f"❌ Платеж {order_id} не найден")
                return
            
            user_id, plan_id, status = payment
            
            if status != 'pending':
                await update.message.reply_text(
                    f"⚠️ Платеж {order_id} уже имеет статус: {status}"
                )
                return
        
        # Активируем подписку
        payment_id = f"ADMIN_ACTIVATE_{datetime.now().timestamp()}"
        success = await subscription_manager.activate_subscription(
            order_id=order_id,
            payment_id=payment_id
        )
        
        if success:
            text = f"✅ Платеж активирован успешно!\n\n"
            text += f"Order ID: <code>{order_id}</code>\n"
            text += f"User ID: {user_id}\n"
            text += f"План: {plan_id}\n\n"
            
            # Получаем информацию о подписке
            subscription_info = await subscription_manager.get_subscription_info(user_id)
            if subscription_info:
                if SUBSCRIPTION_MODE == 'modular':
                    text += f"Модули: {', '.join(subscription_info.get('modules', []))}\n"
                text += f"Действует до: {subscription_info.get('expires_at')}"
            
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
            
            # Уведомляем пользователя
            try:
                await context.bot.send_message(
                    user_id,
                    f"✅ Ваш платеж подтвержден!\n\n"
                    f"План: {SUBSCRIPTION_PLANS[plan_id]['name']}\n"
                    f"Подписка активирована.\n\n"
                    f"Используйте /my_subscriptions для просмотра деталей."
                )
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")
        else:
            await update.message.reply_text(
                f"❌ Ошибка при активации платежа {order_id}\n"
                f"Проверьте логи для деталей."
            )
            
    except Exception as e:
        logger.exception(f"Error activating payment: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


@admin_only
async def cmd_check_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет настройки webhook."""
    from payment.config import WEBHOOK_BASE_URL, WEBHOOK_PATH, TINKOFF_TERMINAL_KEY
    
    text = "🔧 <b>Настройки Webhook:</b>\n\n"
    
    if WEBHOOK_BASE_URL:
        webhook_url = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"
        text += f"✅ URL: <code>{webhook_url}</code>\n"
        text += f"✅ Terminal Key: <code>{TINKOFF_TERMINAL_KEY[:8]}...</code>\n\n"
        text += "⚠️ <b>Убедитесь, что этот URL:</b>\n"
        text += "• Добавлен в настройках Tinkoff\n"
        text += "• Доступен из интернета\n"
        text += "• Использует HTTPS\n\n"
        text += f"<b>Для проверки выполните:</b>\n"
        text += f"<code>curl -X POST {webhook_url}</code>"
    else:
        text += "❌ <b>WEBHOOK_BASE_URL не настроен!</b>\n\n"
        text += "Добавьте в .env:\n"
        text += "<code>WEBHOOK_BASE_URL=https://yourdomain.com</code>\n\n"
        text += "⚠️ Без webhook платежи не будут активироваться автоматически!"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    
@admin_only
async def cmd_payment_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает подробную статистику платежей и подписок."""
    try:
        import aiosqlite
        from payment.config import DATABASE_PATH, SUBSCRIPTION_MODE
        from datetime import datetime, timedelta, timezone
        
        await update.message.reply_text("⏳ Собираю статистику...")
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Общая статистика
            cursor = await db.execute("""
                SELECT 
                    COUNT(DISTINCT user_id) as total_users,
                    COUNT(*) as total_payments,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_payments,
                    SUM(CASE WHEN status = 'completed' THEN amount_kopecks ELSE 0 END) as total_revenue
                FROM payments
            """)
            stats = await cursor.fetchone()
            total_users, total_payments, completed_payments, total_revenue = stats
            
            # Статистика по планам
            cursor = await db.execute("""
                SELECT plan_id, COUNT(*) as count, SUM(amount_kopecks) as revenue
                FROM payments
                WHERE status = 'completed'
                GROUP BY plan_id
                ORDER BY count DESC
            """)
            plan_stats = await cursor.fetchall()
            
            # Активные подписки
            if SUBSCRIPTION_MODE == 'modular':
                # Для модульной системы
                cursor = await db.execute("""
                    SELECT COUNT(DISTINCT user_id) as active_users
                    FROM module_subscriptions
                    WHERE is_active = 1 AND expires_at > datetime('now')
                """)
                active_subs = await cursor.fetchone()
                active_users = active_subs[0]
                
                # Статистика по модулям
                cursor = await db.execute("""
                    SELECT module_code, COUNT(DISTINCT user_id) as users
                    FROM module_subscriptions
                    WHERE is_active = 1 AND expires_at > datetime('now')
                    GROUP BY module_code
                """)
                module_stats = await cursor.fetchall()
            else:
                # Для единой системы
                cursor = await db.execute("""
                    SELECT COUNT(DISTINCT user_id) as active_users
                    FROM user_subscriptions
                    WHERE status = 'active' AND expires_at > datetime('now')
                """)
                active_subs = await cursor.fetchone()
                active_users = active_subs[0]
                module_stats = []
            
            # Платежи за последние 30 дней
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as recent_payments,
                    SUM(CASE WHEN status = 'completed' THEN amount_kopecks ELSE 0 END) as recent_revenue
                FROM payments
                WHERE created_at > datetime('now', '-30 days')
            """)
            recent = await cursor.fetchone()
            recent_payments, recent_revenue = recent
            
            # Формируем сообщение
            text = "📊 <b>Статистика платежей</b>\n\n"
            
            text += "📈 <b>Общая статистика:</b>\n"
            text += f"👥 Всего пользователей: {total_users}\n"
            text += f"💳 Всего платежей: {total_payments}\n"
            text += f"✅ Успешных платежей: {completed_payments}\n"
            text += f"💰 Общий доход: {total_revenue/100:.2f}₽\n\n"
            
            text += "🎯 <b>Активные подписки:</b>\n"
            text += f"👤 Активных пользователей: {active_users}\n"
            
            if module_stats:
                text += "\n<b>По модулям:</b>\n"
                module_names = {
                    'test_part': '📝 Тестовая часть',
                    'task19': '🎯 Задание 19',
                    'task20': '📖 Задание 20',
                    'task24': '💎 Задание 24',
                    'task25': '✍️ Задание 25'
                }
                for module_code, users in module_stats:
                    name = module_names.get(module_code, module_code)
                    text += f"• {name}: {users} польз.\n"
            
            text += f"\n📅 <b>За последние 30 дней:</b>\n"
            text += f"💳 Платежей: {recent_payments}\n"
            text += f"💰 Доход: {recent_revenue/100:.2f}₽\n"
            
            if plan_stats:
                text += "\n💎 <b>Популярные планы:</b>\n"
                plan_names = {
                    'trial_7days': '🎁 Пробный период',
                    'package_second_part': '🎯 Вторая часть',
                    'package_full': '👑 Полный доступ',
                    'module_test_part': '📝 Тестовая часть',
                    'module_task19': '💡 Задание 19',
                    'module_task20': '📖 Задание 20',
                    'module_task24': '💎 Задание 24',
                    'module_task25': '✍️ Задание 25'
                }
                for plan_id, count, revenue in plan_stats[:5]:  # Топ-5 планов
                    name = plan_names.get(plan_id, plan_id)
                    text += f"• {name}: {count} шт. ({revenue/100:.0f}₽)\n"
            
            # Добавляем кнопки для дополнительных действий
            keyboard = [
                [InlineKeyboardButton("📋 Экспорт в CSV", callback_data="admin:export_payments")],
                [InlineKeyboardButton("👥 Список активных", callback_data="admin:list_active_users")],
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin:refresh_stats")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                text, 
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.exception(f"Error getting payment stats: {e}")
        await update.message.reply_text(f"❌ Ошибка получения статистики: {e}")

async def cmd_check_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет админские права пользователя."""
    user_id = update.effective_user.id
    
    # Получаем список админов из конфигурации
    admin_ids = []
    if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
        if isinstance(config.ADMIN_IDS, str):
            admin_ids = [int(id.strip()) for id in config.ADMIN_IDS.split(',') if id.strip()]
        elif isinstance(config.ADMIN_IDS, list):
            admin_ids = config.ADMIN_IDS
    
    # Также проверяем BOT_ADMIN_IDS если есть
    if hasattr(config, 'BOT_ADMIN_IDS') and config.BOT_ADMIN_IDS:
        bot_admin_ids = []
        if isinstance(config.BOT_ADMIN_IDS, str):
            bot_admin_ids = [int(id.strip()) for id in config.BOT_ADMIN_IDS.split(',') if id.strip()]
        elif isinstance(config.BOT_ADMIN_IDS, list):
            bot_admin_ids = config.BOT_ADMIN_IDS
        admin_ids.extend(bot_admin_ids)
    
    # Убираем дубликаты
    admin_ids = list(set(admin_ids))
    
    if user_id in admin_ids:
        await update.message.reply_text(
            f"✅ <b>Вы администратор!</b>\n\n"
            f"📱 Ваш ID: <code>{user_id}</code>\n"
            f"👥 Всего админов: {len(admin_ids)}\n"
            f"📋 Список ID админов: {', '.join(map(str, admin_ids))}\n\n"
            f"Доступные команды:\n"
            f"/grant &lt;user_id&gt; &lt;plan&gt; - выдать подписку\n"
            f"/revoke &lt;user_id&gt; - отозвать подписку\n"
            f"/payment_stats - статистика платежей",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            f"❌ <b>Вы не администратор</b>\n\n"
            f"📱 Ваш ID: <code>{user_id}</code>\n"
            f"💡 Чтобы получить права администратора:\n\n"
            f"1. Добавьте ваш ID в файл <code>.env</code>:\n"
            f"   <code>ADMIN_IDS={user_id}</code>\n\n"
            f"2. Перезапустите бота\n\n"
            f"Текущие админы: {len(admin_ids)}",
            parse_mode=ParseMode.HTML
        )

@admin_only
async def cmd_subscribers_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая проверка количества активных подписчиков."""
    try:
        import aiosqlite
        from payment.config import DATABASE_PATH, SUBSCRIPTION_MODE
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Количество активных подписчиков
            if SUBSCRIPTION_MODE == 'modular':
                cursor = await db.execute("""
                    SELECT COUNT(DISTINCT user_id) 
                    FROM module_subscriptions
                    WHERE is_active = 1 AND expires_at > datetime('now')
                """)
            else:
                cursor = await db.execute("""
                    SELECT COUNT(DISTINCT user_id)
                    FROM user_subscriptions
                    WHERE status = 'active' AND expires_at > datetime('now')
                """)
            
            active_count = (await cursor.fetchone())[0]
            
            # Доход за сегодня
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as today_payments,
                    SUM(CASE WHEN status = 'completed' THEN amount_kopecks ELSE 0 END) as today_revenue
                FROM payments
                WHERE date(created_at) = date('now')
            """)
            today_payments, today_revenue = await cursor.fetchone()
            today_revenue = today_revenue or 0
            
            # Доход за месяц
            cursor = await db.execute("""
                SELECT SUM(amount_kopecks)
                FROM payments
                WHERE status = 'completed' 
                AND created_at > datetime('now', '-30 days')
            """)
            month_revenue = (await cursor.fetchone())[0] or 0
            
            text = f"""📊 <b>Быстрая статистика</b>

👥 Активных подписчиков: <b>{active_count}</b>

💰 <b>Сегодня:</b>
• Платежей: {today_payments}
• Доход: {today_revenue/100:.2f}₽

📅 <b>За 30 дней:</b>
• Доход: {month_revenue/100:.2f}₽
• Средний чек: {month_revenue/100/max(active_count, 1):.2f}₽

Используйте /payment_stats для подробной статистики"""
            
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
            
    except Exception as e:
        logger.exception(f"Error getting quick stats: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

@admin_only
async def cmd_list_active_subscribers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список всех активных подписчиков."""
    try:
        import aiosqlite
        from payment.config import DATABASE_PATH, SUBSCRIPTION_MODE
        from datetime import datetime
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            if SUBSCRIPTION_MODE == 'modular':
                # Для модульной системы
                cursor = await db.execute("""
                    SELECT DISTINCT 
                        ms.user_id,
                        GROUP_CONCAT(ms.module_code) as modules,
                        MIN(ms.expires_at) as earliest_expiry,
                        MAX(ms.expires_at) as latest_expiry
                    FROM module_subscriptions ms
                    WHERE ms.is_active = 1 AND ms.expires_at > datetime('now')
                    GROUP BY ms.user_id
                    ORDER BY ms.user_id
                """)
            else:
                # Для единой системы
                cursor = await db.execute("""
                    SELECT 
                        us.user_id,
                        us.plan_id,
                        us.expires_at
                    FROM user_subscriptions us
                    WHERE us.status = 'active' AND us.expires_at > datetime('now')
                    ORDER BY us.user_id
                """)
            
            subscribers = await cursor.fetchall()
            
            if not subscribers:
                await update.message.reply_text("📭 Нет активных подписчиков")
                return
            
            # Формируем сообщение
            text = f"👥 <b>Активные подписчики ({len(subscribers)} чел.)</b>\n\n"
            
            # Если подписчиков много, показываем первых 20
            for i, sub in enumerate(subscribers[:20]):
                if SUBSCRIPTION_MODE == 'modular':
                    user_id, modules, earliest, latest = sub
                    text += f"{i+1}. User {user_id}\n"
                    text += f"   Модули: {modules}\n"
                    text += f"   До: {latest[:10]}\n\n"
                else:
                    user_id, plan_id, expires_at = sub
                    text += f"{i+1}. User {user_id}\n"
                    text += f"   План: {plan_id}\n"
                    text += f"   До: {expires_at[:10]}\n\n"
            
            if len(subscribers) > 20:
                text += f"... и еще {len(subscribers) - 20} подписчиков\n"
            
            # Кнопка для экспорта полного списка
            keyboard = [[
                InlineKeyboardButton(
                    "📥 Скачать полный список", 
                    callback_data="admin:export_subscribers"
                )
            ]]
            
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    except Exception as e:
        logger.exception(f"Error listing subscribers: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


# Добавьте эту функцию в register_admin_commands:
def register_admin_commands(app: Application):
    """Регистрирует админские команды для управления подписками."""
    app.add_handler(CommandHandler("grant_subscription", cmd_grant_subscription))
    app.add_handler(CommandHandler("activate_payment", cmd_activate_payment))
    app.add_handler(CommandHandler("check_webhook", cmd_check_webhook))
    app.add_handler(CommandHandler("revoke", cmd_revoke_subscription))
    app.add_handler(CommandHandler("payment_stats", cmd_payment_stats))
    app.add_handler(CommandHandler("stats", cmd_subscribers_count))
    app.add_handler(CommandHandler("check_admin", cmd_check_admin))
    app.add_handler(CommandHandler("list_subscribers", cmd_list_active_subscribers))
    
    # Обработчики для callback кнопок
    app.add_handler(CallbackQueryHandler(
        handle_export_payments, pattern="^admin:export_payments$"
    ))
    app.add_handler(CallbackQueryHandler(
        handle_list_active_users, pattern="^admin:list_active_users$"
    ))
    app.add_handler(CallbackQueryHandler(
        handle_refresh_stats, pattern="^admin:refresh_stats$"
    ))
    
    logger.info("Admin payment commands registered")
