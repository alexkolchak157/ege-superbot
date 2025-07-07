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
async def cmd_grant_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдает подписку пользователю."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /grant <user_id> <plan_id>\n"
            "Планы: basic_month, pro_month, pro_ege"
        )
        return
    
    try:
        user_id = int(context.args[0])
        plan_id = context.args[1]
        
        subscription_manager = SubscriptionManager()
        
        # Создаем фиктивный платеж
        from datetime import datetime, timedelta, timezone
        payment = await subscription_manager.create_payment(
            user_id=user_id,
            plan_id=plan_id,
            amount_kopecks=0  # Бесплатная выдача
        )
        
        # Активируем подписку
        success = await subscription_manager.activate_subscription(
            order_id=payment['order_id'],
            payment_id=f'ADMIN_GRANT_{datetime.now().timestamp()}'
        )
        
        if success:
            await update.message.reply_text(
                f"✅ Подписка {plan_id} выдана пользователю {user_id}"
            )
        else:
            await update.message.reply_text("❌ Ошибка при выдаче подписки")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный ID пользователя")
    except Exception as e:
        logger.exception(f"Error granting subscription: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


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
async def cmd_payment_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику платежей."""
    try:
        await update.message.reply_text(
            "📊 <b>Статистика платежей</b>\n\n"
            "🚧 Функция в разработке...\n\n"
            "Используйте:\n"
            "/grant <user_id> <plan> - выдать подписку\n"
            "/revoke <user_id> - отозвать подписку",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.exception(f"Error getting payment stats: {e}")
        await update.message.reply_text("❌ Ошибка получения статистики")

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

def register_admin_commands(app: Application):
    """Регистрирует админские команды."""
    app.add_handler(CommandHandler("grant", cmd_grant_subscription))
    app.add_handler(CommandHandler("revoke", cmd_revoke_subscription))
    app.add_handler(CommandHandler("payment_stats", cmd_payment_stats))
    app.add_handler(CommandHandler("check_admin", cmd_check_admin))
    logger.info("Admin commands registered")