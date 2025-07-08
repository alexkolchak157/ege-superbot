# payment/handlers.py - адаптированная версия с поддержкой модулей
"""Обработчики команд для работы с платежами (модульная версия)."""
import logging
from datetime import datetime
from typing import Optional

from telegram import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes, 
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

from core.error_handler import safe_handler
from .config import (
    SUBSCRIPTION_PLANS, 
    SUBSCRIPTION_MODE,
    DURATION_DISCOUNTS,
    MODULE_PLANS,
    PAYMENT_ADMIN_CHAT_ID
)
from .subscription_manager import SubscriptionManager
from .tinkoff import TinkoffPayment

logger = logging.getLogger(__name__)

# Состояния для платежного процесса
CHOOSING_PLAN = "choosing_plan"
CHOOSING_DURATION = "choosing_duration"  # Для модульной системы
ENTERING_EMAIL = "entering_email"
CONFIRMING = "confirming"

# Инициализация менеджеров
subscription_manager = SubscriptionManager()
tinkoff_payment = TinkoffPayment()


@safe_handler()
async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /subscribe - показывает планы подписки."""
    if SUBSCRIPTION_MODE == 'modular':
        return await show_modular_interface(update, context)
    else:
        return await show_unified_plans(update, context)


async def show_unified_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает старые единые планы подписки."""
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
        for feature in plan.get('features', []):
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
    
    return CHOOSING_PLAN


async def show_modular_interface(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает модульную систему подписок."""
    user_id = update.effective_user.id
    
    # Проверяем пробный период
    has_trial = await subscription_manager.has_used_trial(user_id)
    
    # Получаем активные модули
    user_modules = await subscription_manager.get_user_modules(user_id)
    active_module_codes = [m['module_code'] for m in user_modules]
    
    text = "🎓 <b>Выберите подписку для подготовки к ЕГЭ</b>\n\n"
    
    if user_modules:
        text += "📋 <b>Ваши активные модули:</b>\n"
        for module in user_modules:
            text += f"• {module['module_code']} (до {module['expires_at'].strftime('%d.%m.%Y')})\n"
        text += "\n"
    
    keyboard = []
    
    # Пробный период (если не использован)
    if not has_trial:
        trial_plan = MODULE_PLANS.get('trial_7days')
        if trial_plan:
            keyboard.append([
                InlineKeyboardButton(
                    f"🎁 {trial_plan['name']} - {trial_plan['price_rub']}₽",
                    callback_data="pay_trial"
                )
            ])
    
    # Пакетные предложения
    keyboard.append([
        InlineKeyboardButton(
            "👑 Полный доступ - 999₽/мес",
            callback_data="pay_package_full"
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            "🎯 Пакет 'Вторая часть' - 499₽/мес",
            callback_data="pay_package_second"
        )
    ])
    
    # Кнопка для выбора отдельных модулей
    keyboard.append([
        InlineKeyboardButton(
            "📚 Выбрать отдельные модули",
            callback_data="pay_individual_modules"
        )
    ])
    
    # Управление подписками (если есть активные)
    if user_modules:
        keyboard.append([
            InlineKeyboardButton(
                "📋 Мои подписки",
                callback_data="my_subscriptions"
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
    
    return CHOOSING_PLAN


@safe_handler()
async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора плана подписки."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "pay_cancel":
        await query.edit_message_text("❌ Оформление подписки отменено.")
        return ConversationHandler.END
    
    if SUBSCRIPTION_MODE == 'modular':
        # Обработка модульных планов
        if query.data == "pay_individual_modules":
            return await show_individual_modules(update, context)
        elif query.data == "pay_trial":
            context.user_data['selected_plan'] = 'trial_7days'
            context.user_data['duration_months'] = 0
            return await request_email(update, context)
        elif query.data.startswith("pay_package_"):
            package = query.data.replace("pay_package_", "package_")
            context.user_data['selected_plan'] = package
            return await show_duration_options(update, context)
        elif query.data.startswith("pay_module_"):
            module = query.data.replace("pay_", "")
            context.user_data['selected_plan'] = module
            return await show_duration_options(update, context)
    
    # Старая логика для единых планов
    plan_id = query.data.replace("pay_plan_", "")
    
    if plan_id not in SUBSCRIPTION_PLANS:
        await query.edit_message_text("❌ Неверный план подписки.")
        return ConversationHandler.END
    
    context.user_data['selected_plan'] = plan_id
    
    # Запрашиваем email
    return await request_email(update, context)


async def show_individual_modules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список отдельных модулей."""
    query = update.callback_query
    
    text = "📚 <b>Выберите модуль:</b>\n\n"
    
    keyboard = []
    
    # Группируем модули по типам
    individual_modules = {
        k: v for k, v in MODULE_PLANS.items() 
        if v.get('type') == 'individual'
    }
    
    for module_id, module in individual_modules.items():
        text += f"<b>{module['name']}</b>\n"
        text += f"💰 {module['price_rub']}₽/месяц\n"
        text += f"📝 {module['description']}\n\n"
        
        keyboard.append([
            InlineKeyboardButton(
                f"{module['name']} - {module['price_rub']}₽",
                callback_data=f"pay_{module_id}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    
    return CHOOSING_PLAN


async def show_duration_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает варианты длительности подписки."""
    query = update.callback_query
    
    plan_id = context.user_data['selected_plan']
    plan = MODULE_PLANS.get(plan_id, SUBSCRIPTION_PLANS.get(plan_id))
    
    text = f"<b>{plan['name']}</b>\n\n"
    text += "⏱ <b>Выберите срок подписки:</b>\n\n"
    
    keyboard = []
    base_price = plan['price_rub']
    
    for months, discount_info in DURATION_DISCOUNTS.items():
        multiplier = discount_info['multiplier']
        label = discount_info['label']
        total_price = int(base_price * multiplier)
        
        if months > 1:
            saved = (base_price * months) - total_price
            button_text = f"{label} - {total_price}₽ (экономия {saved}₽)"
        else:
            button_text = f"{label} - {total_price}₽"
        
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"duration_{months}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="back_to_plans")
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    
    return CHOOSING_DURATION


@safe_handler()
async def handle_duration_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора длительности подписки."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_plans":
        # Возвращаемся к выбору планов
        return await show_modular_interface(update, context)
    
    months = int(query.data.replace("duration_", ""))
    context.user_data['duration_months'] = months
    
    # Запрашиваем email
    return await request_email(update, context)


async def request_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает email пользователя."""
    query = update.callback_query
    
    text = """📧 <b>Введите ваш email для чека:</b>

Email нужен для отправки электронного чека согласно 54-ФЗ.
Мы не будем использовать его для рассылок."""
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    return ENTERING_EMAIL

@safe_handler()
async def handle_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода email."""
    email = update.message.text.strip()
    
    # Простая проверка email
    import re
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, email):
        await update.message.reply_text(
            "❌ Неверный формат email.\n"
            "Пожалуйста, введите корректный email адрес."
        )
        return ENTERING_EMAIL
    
    # Сохраняем email
    context.user_data['user_email'] = email
    
    # Показываем подтверждение
    plan_id = context.user_data.get('selected_plan')
    plan = MODULE_PLANS.get(plan_id, SUBSCRIPTION_PLANS.get(plan_id))
    
    if not plan:
        await update.message.reply_text("❌ Ошибка: план не найден")
        return ConversationHandler.END
    
    # Рассчитываем финальную цену
    duration = context.user_data.get('duration_months', 1)
    
    if SUBSCRIPTION_MODE == 'modular' and duration > 1:
        from .config import DURATION_DISCOUNTS
        multiplier = DURATION_DISCOUNTS.get(duration, {}).get('multiplier', duration)
        total_price = int(plan['price_rub'] * multiplier)
    else:
        total_price = plan['price_rub'] * duration
    
    text = f"""📋 <b>Подтверждение заказа</b>

📦 План: {plan['name']}
📧 Email: {email}
⏱ Срок: {duration} мес.
💰 К оплате: {total_price} ₽

Все верно?"""
    
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить и оплатить", callback_data="confirm_payment")],
        [InlineKeyboardButton("❌ Отмена", callback_data="pay_cancel")]
    ]
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return CONFIRMING


@safe_handler()
async def handle_payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подтверждения платежа."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "pay_cancel":
        await query.edit_message_text("❌ Оформление подписки отменено.")
        return ConversationHandler.END
    
    # Показываем анимацию загрузки
    await query.edit_message_text("⏳ Создаю платеж...")
    
    user_id = query.from_user.id
    plan_id = context.user_data.get('selected_plan')
    email = context.user_data.get('user_email', f"user{user_id}@example.com")
    duration = context.user_data.get('duration_months', 1)
    
    plan = MODULE_PLANS.get(plan_id, SUBSCRIPTION_PLANS.get(plan_id))
    if not plan:
        await query.edit_message_text("❌ Ошибка: план не найден")
        return ConversationHandler.END
    
    try:
        # Рассчитываем финальную цену в копейках
        if SUBSCRIPTION_MODE == 'modular' and duration > 1:
            from .config import DURATION_DISCOUNTS, get_plan_price_kopecks
            amount_kopecks = get_plan_price_kopecks(plan_id, duration)
        else:
            amount_kopecks = plan['price_rub'] * duration * 100
        
        # Создаем запись о платеже
        payment_data = await subscription_manager.create_payment(
            user_id=user_id,
            plan_id=plan_id,
            amount_kopecks=amount_kopecks
        )
        
        # Создаем чек для Tinkoff
        receipt_items = [{
            "Name": plan['description'],
            "Price": amount_kopecks,
            "Quantity": 1,
            "Amount": amount_kopecks,
            "Tax": "none",
            "PaymentMethod": "advance",
            "PaymentObject": "service"
        }]
        
        # Инициируем платеж в Tinkoff
        result = await tinkoff_payment.init_payment(
            order_id=payment_data['order_id'],
            amount_kopecks=amount_kopecks,
            description=plan['description'],
            user_email=email,
            receipt_items=receipt_items,
            user_data={
                "user_id": str(user_id),
                "plan_id": plan_id,
                "duration_months": str(duration)
            }
        )
        
        if result['success']:
            # Успешно создан платеж
            text = f"""✅ <b>Платеж создан!</b>

Нажмите кнопку ниже для перехода к оплате.
После успешной оплаты подписка будет активирована автоматически.

Сумма: {amount_kopecks // 100} ₽"""
            
            keyboard = [[
                InlineKeyboardButton(
                    "💳 Перейти к оплате",
                    url=result['payment_url']
                )
            ]]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            error = result.get('error', 'Неизвестная ошибка')
            await query.edit_message_text(
                f"❌ Ошибка создания платежа:\n{error}\n\n"
                "Попробуйте позже или обратитесь в поддержку."
            )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error creating payment: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка при создании платежа.\n"
            "Попробуйте позже или обратитесь в поддержку."
        )
        return ConversationHandler.END


async def cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена процесса оплаты."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Оформление подписки отменено.")
    else:
        await update.message.reply_text("❌ Оформление подписки отменено.")
    
    # Очищаем данные
    context.user_data.clear()
    
    return ConversationHandler.END


@safe_handler()
async def cmd_my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /my_subscriptions - показывает активные подписки."""
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    if SUBSCRIPTION_MODE == 'modular':
        modules = await subscription_manager.get_user_modules(user_id)
        
        if not modules:
            text = "У вас нет активных подписок.\n\nИспользуйте /subscribe для оформления."
        else:
            text = "📋 <b>Ваши активные модули:</b>\n\n"
            module_names = {
                'test_part': '📝 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '📖 Задание 20',
                'task25': '✍️ Задание 25',
                'task24': '💎 Задание 24 (Премиум)'
            }
            for module in modules:
                name = module_names.get(module['module_code'], module['module_code'])
                expires = module['expires_at'].strftime('%d.%m.%Y')
                text += f"{name}\n└ Действует до: {expires}\n\n"
            
            text += "Используйте /subscribe для продления или добавления модулей."
    else:
        subscription = await subscription_manager.check_active_subscription(user_id)
        if subscription:
            plan = SUBSCRIPTION_PLANS.get(subscription['plan_id'], {})
            expires = subscription['expires_at'].strftime('%d.%m.%Y')
            text = f"""✅ <b>Активная подписка</b>

План: {plan.get('name', 'Подписка')}
Действует до: {expires}

Используйте /subscribe для продления."""
        else:
            text = "У вас нет активной подписки.\n\nИспользуйте /subscribe для оформления."
    
    keyboard = [[InlineKeyboardButton("🔄 Оформить/Продлить", callback_data="subscribe")]]
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@safe_handler()
async def handle_my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback my_subscriptions."""
    query = update.callback_query
    await query.answer()
    
    # Показываем подписки как в команде
    user_id = query.from_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    if SUBSCRIPTION_MODE == 'modular':
        modules = await subscription_manager.get_user_modules(user_id)
        
        if not modules:
            text = "У вас нет активных подписок.\n\nВыберите подходящий план:"
        else:
            text = "📋 <b>Ваши активные модули:</b>\n\n"
            module_names = {
                'test_part': '📝 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '📖 Задание 20',
                'task24': '💎 Задание 24',
                'task25': '✍️ Задание 25'
            }
            for module in modules:
                name = module_names.get(module['module_code'], module['module_code'])
                expires = module['expires_at'].strftime('%d.%m.%Y')
                text += f"{name}\n└ Действует до: {expires}\n\n"
    else:
        subscription = await subscription_manager.check_active_subscription(user_id)
        if subscription:
            plan = SUBSCRIPTION_PLANS.get(subscription['plan_id'], {})
            expires = subscription['expires_at'].strftime('%d.%m.%Y')
            text = f"""✅ <b>Активная подписка</b>

План: {plan.get('name', 'Подписка')}
Действует до: {expires}"""
        else:
            text = "У вас нет активной подписки."
    
    keyboard = [
        [InlineKeyboardButton("🔄 Оформить/Продлить", callback_data="subscribe")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Экспорт обработчиков для регистрации
def register_payment_handlers(app):
    """Регистрирует обработчики платежей."""
    
    # ConversationHandler для процесса оплаты
    payment_conv = ConversationHandler(
        entry_points=[
            CommandHandler("subscribe", cmd_subscribe),
            CallbackQueryHandler(show_modular_interface, pattern="^subscribe$")
        ],
        states={
            CHOOSING_PLAN: [
                CallbackQueryHandler(handle_plan_selection, pattern="^pay_"),
                CallbackQueryHandler(show_individual_modules, pattern="^pay_individual_modules$"),
                CallbackQueryHandler(show_modular_interface, pattern="^back_to_main$")
            ],
            CHOOSING_DURATION: [
                CallbackQueryHandler(handle_duration_selection, pattern="^duration_"),
                CallbackQueryHandler(show_modular_interface, pattern="^back_to_plans$")
            ],
            ENTERING_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_input)
            ],
            CONFIRMING: [
                CallbackQueryHandler(handle_payment_confirmation, pattern="^confirm_payment$"),
                CallbackQueryHandler(cmd_subscribe, pattern="^pay_cancel$")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_payment),
            CallbackQueryHandler(cancel_payment, pattern="^pay_cancel$")
        ],
        allow_reentry=True
    )
    
    app.add_handler(payment_conv)
    
    # Дополнительные команды
    app.add_handler(CommandHandler("my_subscriptions", cmd_my_subscriptions))
    app.add_handler(CallbackQueryHandler(handle_my_subscriptions, pattern="^my_subscriptions$"))
    
    logger.info("Payment handlers registered")