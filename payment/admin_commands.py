# payment/admin_commands.py
"""Админские команды для управления подписками."""
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, CommandHandler

from core.admin_tools import admin_only
from .subscription_manager import SubscriptionManager
from .config import SUBSCRIPTION_PLANS

logger = logging.getLogger(__name__)

subscription_manager = SubscriptionManager()


@admin_only
async def cmd_grant_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдает подписку пользователю. Использование: /grant <user_id> <plan_id> [days]"""
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /grant <user_id> <plan_id> [days]\n\n"
            f"Доступные планы: {', '.join(SUBSCRIPTION_PLANS.keys())}"
        )
        return
    
    try:
        user_id = int(context.args[0])
        plan_id = context.args[1]
        days = int(context.args[2]) if len(context.args) > 2 else None
        
        if plan_id not in SUBSCRIPTION_PLANS:
            await update.message.reply_text(f"❌ Неизвестный план: {plan_id}")
            return
        
        success = await subscription_manager.grant_subscription(
            user_id=user_id,
            plan_id=plan_id,
            days=days,
            reason=f"admin_grant_by_{update.effective_user.id}"
        )
        
        if success:
            # Уведомляем пользователя
            try:
                plan = SUBSCRIPTION_PLANS[plan_id]
                await context.bot.send_message(
                    user_id,
                    f"🎁 Вам выдана подписка \"{plan['name']}\"!\n"
                    f"Используйте /status для просмотра деталей."
                )
            except:
                pass
            
            await update.message.reply_text(
                f"✅ Подписка {plan_id} выдана пользователю {user_id}"
            )
        else:
            await update.message.reply_text("❌ Ошибка при выдаче подписки")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат команды")
    except Exception as e:
        logger.exception(f"Error granting subscription: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


@admin_only
async def cmd_revoke_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отзывает подписку. Использование: /revoke <user_id>"""
    
    if not context.args:
        await update.message.reply_text("Использование: /revoke <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        
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
        # Здесь можно добавить подробную статистику из БД
        text = """📊 <b>Статистика платежей</b>

🚧 Функция в разработке...

Используйте:
/grant - выдать подписку
/revoke - отозвать подписку"""
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.exception(f"Error getting payment stats: {e}")
        await update.message.reply_text("❌ Ошибка получения статистики")


def register_admin_commands(app):
    """Регистрирует админские команды."""
    app.add_handler(CommandHandler("grant", cmd_grant_subscription))
    app.add_handler(CommandHandler("revoke", cmd_revoke_subscription))
    app.add_handler(CommandHandler("payment_stats", cmd_payment_stats))