# payment/handlers.py
"""Обработчики команд для работы с платежами."""
import logging
from datetime import datetime
from typing import Optional

from telegram import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Update,
    WebAppInfo
)
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes, 
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler
)

from core import db, states
from core.error_handler import safe_handler
from core.utils import safe_edit_message

from .config import SUBSCRIPTION_PLANS, PAYMENT_ADMIN_CHAT_ID
from .subscription_manager import SubscriptionManager
from .tinkoff import TinkoffPayment

logger = logging.getLogger(__name__)

# Состояния для платежного процесса
PAYMENT_CHOOSING_PLAN = "payment_choosing_plan"
PAYMENT_ENTERING_EMAIL = "payment_entering_email"
PAYMENT_CONFIRMING = "payment_confirming"

# Инициализация менеджеров
subscription_manager = SubscriptionManager()
tinkoff_payment = TinkoffPayment()


@safe_handler()
async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /subscribe - показывает планы подписки."""
    user_id = update.effective_user.id
    
    # Проверяем текущую подписку
    subscription = await subscription_manager.check_active_subscription(user_id)
    
    if subscription:
        expires = subscription['expires_at'].strftime('%d.%m.%Y')
        text = f"""✅ <b>У вас есть активная подписка!</b>

План: {SUBSCRIPTION_PLANS[subscription['plan_id']]['name']}
Действует до: {expires}

Используйте /status для просмотра детальной информации."""
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    
    # Показываем доступные планы
    text = "💎 <b>Выберите план подписки:</b>\n\n"
    
    keyboard = []
    for plan_id, plan in SUBSCRIPTION_PLANS.items():
        text += f"<b>{plan['name']}</b>\n"
        text += f"💰 {plan['price_rub']} ₽\n"
        text += f"📝 {plan['description']}\n"
        for feature in plan['features']:
            text += f"  {feature}\n"
        text += "\n"
        
        keyboard.append([
            InlineKeyboardButton(
                f"{plan['name']} - {plan['price_rub']} ₽",
                callback_data=f"pay_plan_{plan_id}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("❌ Отмена", callback_data="pay_cancel")
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    
    return PAYMENT_CHOOSING_PLAN


@safe_handler()
async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора плана подписки."""
    query = update.callback_query
    
    if query.data == "pay_cancel":
        await query.edit_message_text("❌ Оформление подписки отменено.")
        return ConversationHandler.END
    
    plan_id = query.data.replace("pay_plan_", "")
    if plan_id not in SUBSCRIPTION_PLANS:
        await query.answer("❌ Неверный план подписки", show_alert=True)
        return PAYMENT_CHOOSING_PLAN
    
    # Сохраняем выбранный план
    context.user_data['selected_plan'] = plan_id
    
    # Запрашиваем email для чека
    plan = SUBSCRIPTION_PLANS[plan_id]
    text = f"""Вы выбрали: <b>{plan['name']}</b>
Стоимость: {plan['price_rub']} ₽

📧 <b>Введите ваш email для отправки чека:</b>
(Например: example@mail.ru)"""
    
    keyboard = [[
        InlineKeyboardButton("❌ Отмена", callback_data="pay_cancel")
    ]]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    
    return PAYMENT_ENTERING_EMAIL


@safe_handler()
async def handle_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода email."""
    if update.callback_query and update.callback_query.data == "pay_cancel":
        await update.callback_query.edit_message_text("❌ Оформление подписки отменено.")
        return ConversationHandler.END
    
    email = update.message.text.strip()
    
    # Простая проверка email
    if "@" not in email or "." not in email:
        await update.message.reply_text(
            "❌ Некорректный email. Попробуйте еще раз.\n"
            "Пример: example@mail.ru"
        )
        return PAYMENT_ENTERING_EMAIL
    
    # Сохраняем email
    context.user_data['user_email'] = email
    
    # Показываем подтверждение
    plan_id = context.user_data['selected_plan']
    plan = SUBSCRIPTION_PLANS[plan_id]
    
    text = f"""<b>Подтверждение заказа:</b>

📦 Товар: {plan['name']}
💰 Стоимость: {plan['price_rub']} ₽
📧 Email: {email}

После оплаты подписка будет активирована автоматически."""
    
    keyboard = [
        [InlineKeyboardButton("✅ Перейти к оплате", callback_data="pay_confirm")],
        [InlineKeyboardButton("❌ Отмена", callback_data="pay_cancel")]
    ]
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    
    return PAYMENT_CONFIRMING


@safe_handler()
async def handle_payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подтверждения и создание платежа."""
    query = update.callback_query
    
    if query.data == "pay_cancel":
        await query.edit_message_text("❌ Оформление подписки отменено.")
        return ConversationHandler.END
    
    # Показываем анимацию загрузки
    await query.edit_message_text("⏳ Создаю платеж...")
    
    user_id = query.from_user.id
    plan_id = context.user_data['selected_plan']
    email = context.user_data['user_email']
    plan = SUBSCRIPTION_PLANS[plan_id]
    
    try:
        # 1. Создаем запись о платеже в БД
        from .config import get_plan_price_kopecks
        amount_kopecks = get_plan_price_kopecks(plan_id)
        
        payment_data = await subscription_manager.create_payment(
            user_id=user_id,
            plan_id=plan_id,
            amount_kopecks=amount_kopecks
        )
        
        # 2. Создаем чек
        receipt_items = [
            tinkoff_payment.build_receipt_item(
                name=plan['description'],
                price_kopecks=amount_kopecks
            )
        ]
        
        # 3. Инициируем платеж в Tinkoff
        result = await tinkoff_payment.init_payment(
            order_id=payment_data['order_id'],
            amount_kopecks=amount_kopecks,
            description=plan['description'],
            user_email=email,
            receipt_items=receipt_items,
            user_data={
                "user_id": str(user_id),
                "plan_id": plan_id
            }
        )
        
        if result['success']:
            # Успешно создан платеж
            text = f"""✅ <b>Платеж создан!</b>

Нажмите кнопку ниже для перехода к оплате.
После успешной оплаты подписка будет активирована автоматически.

💡 Если кнопка не работает, используйте эту ссылку:
{result['payment_url']}"""
            
            keyboard = [[
                InlineKeyboardButton(
                    "💳 Оплатить",
                    url=result['payment_url']
                )
            ]]
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            
            # Уведомляем админа
            if PAYMENT_ADMIN_CHAT_ID:
                admin_text = f"""💰 Новый платеж:
                
User: {query.from_user.id} (@{query.from_user.username or 'no_username'})
План: {plan['name']}
Сумма: {plan['price_rub']} ₽
Order ID: {payment_data['order_id']}"""
                
                try:
                    await context.bot.send_message(
                        PAYMENT_ADMIN_CHAT_ID,
                        admin_text
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin: {e}")
            
        else:
            # Ошибка создания платежа
            error_text = f"""❌ <b>Ошибка создания платежа</b>

{result.get('error', 'Неизвестная ошибка')}

Попробуйте позже или обратитесь в поддержку."""
            
            await query.edit_message_text(
                error_text,
                parse_mode=ParseMode.HTML
            )
        
    except Exception as e:
        logger.exception(f"Error creating payment: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка при создании платежа. Попробуйте позже.",
            parse_mode=ParseMode.HTML
        )
    
    return ConversationHandler.END


@safe_handler()
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status - показывает статус подписки."""
    user_id = update.effective_user.id
    
    # Получаем данные из БД
    user_status = await db.get_or_create_user_status(user_id)
    subscription = await subscription_manager.check_active_subscription(user_id)
    
    if subscription:
        plan = SUBSCRIPTION_PLANS[subscription['plan_id']]
        expires = subscription['expires_at'].strftime('%d.%m.%Y %H:%M')
        days_left = (subscription['expires_at'] - datetime.now(subscription['expires_at'].tzinfo)).days
        
        text = f"""✅ <b>Статус подписки</b>

📋 План: {plan['name']}
📅 Активна до: {expires}
⏳ Осталось дней: {days_left}

📊 <b>Статистика использования:</b>
Вопросов в этом месяце: {user_status['monthly_usage_count']}"""
        
    else:
        text = f"""❌ <b>Подписка не активна</b>

📊 <b>Статистика использования:</b>
Вопросов в этом месяце: {user_status['monthly_usage_count']} / 50

Для получения полного доступа используйте /subscribe"""
    
    # Добавляем историю платежей
    payments = await subscription_manager.get_user_payment_history(user_id)
    if payments:
        text += "\n\n💸 <b>История платежей:</b>\n"
        for p in payments[:3]:  # Показываем последние 3
            status_emoji = "✅" if p['status'] == 'confirmed' else "⏳"
            date = datetime.fromisoformat(p['created_at']).strftime('%d.%m.%Y')
            text += f"{status_emoji} {date} - {p['amount_kopecks'] // 100} ₽\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


def register_payment_handlers(app):
    """Регистрирует обработчики платежей в приложении."""
    
    # ConversationHandler для процесса оплаты
    payment_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("subscribe", cmd_subscribe),
            CallbackQueryHandler(cmd_subscribe, pattern="^to_subscription$")
        ],
        states={
            PAYMENT_CHOOSING_PLAN: [
                CallbackQueryHandler(handle_plan_selection, pattern="^pay_")
            ],
            PAYMENT_ENTERING_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_input),
                CallbackQueryHandler(handle_email_input, pattern="^pay_cancel$")
            ],
            PAYMENT_CONFIRMING: [
                CallbackQueryHandler(handle_payment_confirmation, pattern="^pay_")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CallbackQueryHandler(
                lambda u, c: ConversationHandler.END, 
                pattern="^pay_cancel$"
            )
        ],
        name="payment_conversation",
        persistent=True
    )
    
    app.add_handler(payment_conv_handler)
    app.add_handler(CommandHandler("status", cmd_status))
    
    # Обработчик для возврата к подписке из других мест
    app.add_handler(
        CallbackQueryHandler(cmd_subscribe, pattern="^to_subscription$"),
        group=1
    )