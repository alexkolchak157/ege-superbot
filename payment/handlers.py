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
CHOOSING_DURATION = "choosing_duration"  
ENTERING_EMAIL = "entering_email"
CONFIRMING = "confirming"

# Экспортируем состояния для использования в middleware
PAYMENT_STATES = [CHOOSING_PLAN, CHOOSING_DURATION, ENTERING_EMAIL, CONFIRMING]

# Инициализация менеджеров
subscription_manager = SubscriptionManager()
tinkoff_payment = TinkoffPayment()


@safe_handler()
async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /subscribe - показывает планы подписки."""
    # Проверяем, что у нас есть message (команда была вызвана через /subscribe)
    if not update.message:
        logger.warning("cmd_subscribe called without message")
        return ConversationHandler.END
    
    if SUBSCRIPTION_MODE == 'modular':
        return await show_modular_interface(update, context)
    else:
        return await show_unified_plans(update, context)


async def show_unified_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает старые единые планы подписки."""
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    # Проверяем текущую подписку
    subscription = await subscription_manager.check_active_subscription(user_id)
    
    if subscription:
        expires = subscription['expires_at'].strftime('%d.%m.%Y')
        text = f"""✅ <b>У вас есть активная подписка!</b>

План: {SUBSCRIPTION_PLANS[subscription['plan_id']]['name']}
Действует до: {expires}

Используйте /status для просмотра детальной информации."""
        
        # Отправляем сообщение правильным способом
        if update.message:
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(text, parse_mode=ParseMode.HTML)
        
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
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отправляем сообщение правильным способом
    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await query.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
    
    return CHOOSING_PLAN


async def show_modular_interface(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает модульную систему подписок."""
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    # ВАЖНО: Устанавливаем флаг, что пользователь в процессе оплаты
    context.user_data['in_payment_process'] = True
    
    # Проверяем пробный период
    has_trial = await subscription_manager.has_used_trial(user_id)
    
    # Проверяем активные модули
    active_modules = await subscription_manager.get_user_modules(user_id)
    
    text = "💎 <b>Модульная система подписок</b>\n\n"
    
    if active_modules:
        text += "✅ <b>Ваши активные модули:</b>\n"
        module_names = {
            'test_part': '📝 Тестовая часть',
            'task19': '🎯 Задание 19',
            'task20': '📖 Задание 20',
            'task24': '💎 Задание 24',
            'task25': '✍️ Задание 25'
        }
        for module in active_modules:
            name = module_names.get(module['module_code'], module['module_code'])
            expires = module['expires_at'].strftime('%d.%m.%Y')
            text += f"• {name} (до {expires})\n"
        text += "\n"
    
    text += "Выберите тариф или модуль:\n\n"
    
    keyboard = []
    
    # Пробный период
    if not has_trial:
        keyboard.append([
            InlineKeyboardButton(
                "🎁 Пробный период - 1₽ (7 дней)",
                callback_data="pay_trial"
            )
        ])
    
    # Пакетные предложения
    keyboard.extend([
        [InlineKeyboardButton(
            "👑 Полный доступ - 999₽/мес",
            callback_data="pay_package_full"
        )],
        [InlineKeyboardButton(
            "🎯 Пакет 'Вторая часть' - 499₽/мес",
            callback_data="pay_package_second_part"
        )],
        [InlineKeyboardButton(
            "📚 Выбрать отдельные модули",
            callback_data="pay_individual_modules"
        )]
    ])
    
    # Кнопка отмены
    keyboard.append([
        InlineKeyboardButton("❌ Отмена", callback_data="pay_cancel")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Проверяем, откуда пришел вызов - из команды или из callback
    if update.message:
        # Вызов через команду /subscribe
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    elif update.callback_query:
        # Вызов через callback кнопки
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            # Если не удалось отредактировать, отправляем новое сообщение
            await query.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
    
    return CHOOSING_PLAN


@safe_handler()
async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора плана подписки."""
    query = update.callback_query
    await query.answer()
    
    # ВАЖНО: Устанавливаем флаг, что пользователь в процессе оплаты
    context.user_data['in_payment_process'] = True
    
    if query.data == "pay_cancel":
        # Очищаем флаг при отмене
        context.user_data.pop('in_payment_process', None)
        await query.edit_message_text("❌ Оформление подписки отменено.")
        return ConversationHandler.END
    
    if SUBSCRIPTION_MODE == 'modular':
        # Обработка модульных планов
        if query.data == "pay_individual_modules":
            return await show_individual_modules(update, context)
        elif query.data == "pay_trial":
            # ВАЖНО: Сохраняем все данные для пробного периода
            context.user_data['selected_plan'] = 'trial_7days'
            context.user_data['duration_months'] = 0
            context.user_data['is_trial'] = True  # Дополнительный флаг
            return await request_email(update, context)
        elif query.data.startswith("pay_package_"):
            # Исправляем обработку package_second -> package_second_part
            package_name = query.data.replace("pay_package_", "")
            if package_name == "second":
                package = "package_second_part"
            else:
                package = f"package_{package_name}"
            context.user_data['selected_plan'] = package
            return await show_duration_options(update, context)
        elif query.data.startswith("pay_module_"):
            module = query.data.replace("pay_", "")
            context.user_data['selected_plan'] = module
            return await show_duration_options(update, context)
    
    # Старая логика для единых планов
    plan_id = query.data.replace("pay_plan_", "")
    
    if plan_id not in SUBSCRIPTION_PLANS:
        # Очищаем флаг при ошибке
        context.user_data.pop('in_payment_process', None)
        await query.edit_message_text("❌ Неверный план подписки.")
        return ConversationHandler.END
    
    context.user_data['selected_plan'] = plan_id
    
    # Запрашиваем email
    return await request_email(update, context)


async def show_individual_modules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список отдельных модулей."""
    query = update.callback_query
    
    # ВАЖНО: Устанавливаем флаг процесса оплаты
    context.user_data['in_payment_process'] = True
    
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
    
    # ВАЖНО: Устанавливаем флаг процесса оплаты
    context.user_data['in_payment_process'] = True
    
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
    
    # ВАЖНО: Подтверждаем флаг процесса оплаты
    context.user_data['in_payment_process'] = True
    
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
    
    # ВАЖНО: Устанавливаем/подтверждаем флаг процесса оплаты
    context.user_data['in_payment_process'] = True
    
    text = """📧 <b>Введите ваш email для чека:</b>

Email нужен для отправки электронного чека согласно 54-ФЗ.
Мы не будем использовать его для рассылок."""
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    return ENTERING_EMAIL

@safe_handler()
async def handle_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода email."""
    # ВАЖНО: Подтверждаем флаг процесса оплаты
    context.user_data['in_payment_process'] = True
    
    # Добавляем отладочный вывод
    logger.info(f"handle_email_input called for user {update.effective_user.id}")
    logger.info(f"Context data: {list(context.user_data.keys())}")
    
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
        # Очищаем флаг при ошибке
        context.user_data.pop('in_payment_process', None)
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
        # Очищаем флаг при отмене
        context.user_data.pop('in_payment_process', None)
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
        # Очищаем флаг при ошибке
        context.user_data.pop('in_payment_process', None)
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
            
            # Очищаем флаг после успешного создания платежа
            context.user_data.pop('in_payment_process', None)
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Очищаем флаг при ошибке
            context.user_data.pop('in_payment_process', None)
            
            error = result.get('error', 'Неизвестная ошибка')
            await query.edit_message_text(
                f"❌ Ошибка создания платежа:\n{error}\n\n"
                "Попробуйте позже или обратитесь в поддержку."
            )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error creating payment: {e}")
        
        # Очищаем флаг при ошибке
        context.user_data.pop('in_payment_process', None)
        
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

@safe_handler()
async def handle_module_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о модуле."""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем код модуля из callback_data
    module_code = query.data.replace("module_info_", "")
    
    module_info = {
        'test_part': {
            'name': '📝 Тестовая часть ЕГЭ',
            'description': 'Полный доступ к банку заданий тестовой части',
            'features': [
                '✅ Все задания 1-16',
                '✅ Подробные объяснения',
                '✅ Статистика прогресса',
                '✅ Работа над ошибками'
            ],
            'price': '149₽/мес'
        },
        'task19': {
            'name': '🎯 Задание 19',
            'description': 'Примеры социальных объектов и явлений',
            'features': [
                '✅ База примеров по всем темам',
                '✅ Интерактивные тренажеры',
                '✅ Проверка ответов'
            ],
            'price': '199₽/мес'
        },
        'task20': {
            'name': '📖 Задание 20',
            'description': 'Текст с пропущенными словами',
            'features': [
                '✅ Тексты по всем разделам',
                '✅ Подробные пояснения',
                '✅ Тренировка навыков'
            ],
            'price': '199₽/мес'
        },
        'task24': {
            'name': '💎 Задание 24 (Премиум)',
            'description': 'Составление сложного плана',
            'features': [
                '✅ База готовых планов',
                '✅ Экспертная проверка',
                '✅ Персональные рекомендации',
                '✅ VIP поддержка'
            ],
            'price': '399₽/мес'
        },
        'task25': {
            'name': '✍️ Задание 25',
            'description': 'Понятия и термины',
            'features': [
                '✅ Полная база понятий',
                '✅ Интерактивная проверка',
                '✅ Адаптивная сложность'
            ],
            'price': '199₽/мес'
        }
    }
    
    info = module_info.get(module_code)
    if not info:
        await query.edit_message_text(
            "❌ Информация о модуле не найдена",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="subscribe")
            ]])
        )
        return
    
    text = f"<b>{info['name']}</b>\n\n"
    text += f"{info['description']}\n\n"
    text += "<b>Что входит:</b>\n"
    for feature in info['features']:
        text += f"{feature}\n"
    text += f"\n💰 <b>Стоимость:</b> {info['price']}"
    
    keyboard = [
        [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="subscribe")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def register_payment_handlers(app):
    """Регистрирует обработчики платежей."""
    
    # ConversationHandler для процесса оплаты
    payment_conv = ConversationHandler(
        entry_points=[
            CommandHandler("subscribe", cmd_subscribe),
            CallbackQueryHandler(show_modular_interface, pattern="^subscribe$"),
            CallbackQueryHandler(show_modular_interface, pattern="^subscribe_start$")
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
    
    # ВАЖНО: Регистрируем с приоритетом -50, чтобы обработчик срабатывал ДО middleware (-100)
    app.add_handler(payment_conv, group=-50)
    
    # Дополнительные команды тоже с приоритетом
    app.add_handler(CommandHandler("my_subscriptions", cmd_my_subscriptions), group=-50)
    app.add_handler(CallbackQueryHandler(handle_my_subscriptions, pattern="^my_subscriptions$"), group=-50)
    
    # Обработчик информации о модулях
    app.add_handler(CallbackQueryHandler(handle_module_info, pattern="^module_info_"), group=-50)
    
    logger.info("Payment handlers registered with priority")