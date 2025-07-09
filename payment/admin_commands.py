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
    """Выдает подписку пользователю вручную. Использование: /grant_subscription <user_id> <plan_id>"""
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
        
        subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
        
        # Создаем фиктивный payment_id
        payment_id = f"ADMIN_GRANT_{datetime.now().timestamp()}"
        
        # Активируем подписку
        if SUBSCRIPTION_MODE == 'modular':
            await subscription_manager._activate_modular_subscription(user_id, plan_id, payment_id)
        else:
            await subscription_manager._activate_unified_subscription(user_id, plan_id, payment_id)
        
        # Получаем информацию о подписке
        subscription_info = await subscription_manager.get_subscription_info(user_id)
        
        text = f"✅ Подписка выдана успешно!\n\n"
        text += f"Пользователь: {user_id}\n"
        text += f"План: {SUBSCRIPTION_PLANS[plan_id]['name']}\n"
        
        if subscription_info:
            if SUBSCRIPTION_MODE == 'modular':
                text += f"Модули: {', '.join(subscription_info.get('modules', []))}\n"
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
            logger.error(f"Failed to notify user: {e}")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный ID пользователя")
    except Exception as e:
        logger.error(f"Error granting subscription: {e}")
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
    app.add_handler(CommandHandler("grant_subscription", cmd_grant_subscription))
    app.add_handler(CommandHandler("revoke", cmd_revoke_subscription))
    app.add_handler(CommandHandler("payment_stats", cmd_payment_stats))
    app.add_handler(CommandHandler("check_admin", cmd_check_admin))
    logger.info("Admin commands registered")