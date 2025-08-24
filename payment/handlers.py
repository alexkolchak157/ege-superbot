# payment/handlers.py - адаптированная версия с поддержкой модулей
"""Обработчики команд для работы с платежами (модульная версия)."""
import logging
from datetime import datetime, timedelta, timezone
import uuid
from typing import Optional, Dict, Any, List
import json
from telegram import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Update,
)
from telegram.error import BadRequest
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ContextTypes, 
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from .auto_renewal_consent import (
    AutoRenewalConsent, 
    show_auto_renewal_choice,
    SHOWING_TERMS, 
    CONSENT_CHECKBOX, 
    FINAL_CONFIRMATION
)
from core.db import DATABASE_FILE
import re
import aiosqlite
from core.error_handler import safe_handler
from .config import (
    SUBSCRIPTION_PLANS,
    SUBSCRIPTION_PLANS, 
    SUBSCRIPTION_MODE,
    DURATION_DISCOUNTS,
    MODULE_PLANS,
    PAYMENT_ADMIN_CHAT_ID,
    get_plan_price_kopecks
)
from .subscription_manager import SubscriptionManager
from .tinkoff import TinkoffPayment

# Состояния для ConversationHandler
CHOOSING_PLAN = 1
CHOOSING_MODULES = 2
CHOOSING_DURATION = 3
CONFIRMING = 4
ENTERING_EMAIL = 5
CHOOSING_AUTO_RENEWAL = 6
FINAL_CONFIRMATION = 7

logger = logging.getLogger(__name__)

# Состояния для платежного процесса
CHOOSING_PLAN = "choosing_plan"
CHOOSING_DURATION = "choosing_duration"  
ENTERING_EMAIL = "entering_email"
CONFIRMING = "confirming"
CHOOSING_MODULES = "choosing_modules"  # Новое состояние
AUTO_RENEWAL_CHOICE = "auto_renewal_choice"  # НОВОЕ
FINAL_CONSENT = "final_consent"              # НОВОЕ
PAYMENT_STATES = [CHOOSING_PLAN, CHOOSING_MODULES, CHOOSING_DURATION, ENTERING_EMAIL,FINAL_CONSENT, AUTO_RENEWAL_CHOICE, CONFIRMING]

# Инициализация менеджеров
subscription_manager = SubscriptionManager()
tinkoff_payment = TinkoffPayment()


@safe_handler()
async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /subscribe - показывает планы подписки."""
    # Проверяем источник вызова
    if update.callback_query:
        # Вызов из callback - используем show_modular_interface
        return await show_modular_interface(update, context)
    elif update.message:
        # Вызов из команды - показываем интерфейс
        if SUBSCRIPTION_MODE == 'modular':
            return await show_modular_interface(update, context)
        else:
            return await show_unified_plans(update, context)
    else:
        # Неизвестный источник
        logger.error("cmd_subscribe called without message or callback_query")
        return ConversationHandler.END

@safe_handler()
async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет статус платежа по запросу пользователя."""
    query = update.callback_query
    await query.answer("Проверяю статус платежа...")
    
    user_id = update.effective_user.id
    
    # Получаем менеджер подписок
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    # Проверяем последний платеж пользователя
    try:
        # Получаем последний платеж из БД
        async with aiosqlite.connect('bot_database.db') as conn:
            cursor = await conn.execute("""
                SELECT order_id, status, plan_id, amount
                FROM payments
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id,))
            
            payment = await cursor.fetchone()
            
            if not payment:
                await query.edit_message_text(
                    "❌ Платеж не найден.\n\n"
                    "Возможно, вы еще не создавали платеж или он был отменен."
                )
                return
            
            order_id, status, plan_id, amount = payment
            
            # Проверяем статус платежа в Tinkoff
            from payment.tinkoff import TinkoffPayment
            tinkoff = TinkoffPayment()
            payment_status = await tinkoff.check_payment_status(order_id)
            
            if payment_status == 'CONFIRMED':
                # Платеж подтвержден
                await query.edit_message_text(
                    "✅ <b>Платеж успешно подтвержден!</b>\n\n"
                    "Ваша подписка активирована.\n"
                    "Используйте /my_subscriptions для просмотра деталей.",
                    parse_mode=ParseMode.HTML
                )
                
                # Активируем подписку если еще не активирована
                if status != 'completed':
                    await subscription_manager.activate_subscription_from_payment(order_id)
                    
            elif payment_status in ['NEW', 'FORM_SHOWED', 'DEADLINE_EXPIRED']:
                # Платеж еще не оплачен
                await query.edit_message_text(
                    "⏳ <b>Платеж ожидает оплаты</b>\n\n"
                    f"Статус: {payment_status}\n"
                    f"Сумма: {amount}₽\n\n"
                    "Если вы уже оплатили, подождите несколько минут и проверьте снова.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔄 Проверить еще раз", callback_data="check_payment")
                    ]])
                )
            elif payment_status in ['REJECTED', 'CANCELED', 'REFUNDED']:
                # Платеж отклонен/отменен
                await query.edit_message_text(
                    f"❌ <b>Платеж отклонен</b>\n\n"
                    f"Статус: {payment_status}\n\n"
                    "Попробуйте создать новый платеж.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔄 Создать новый платеж", callback_data="subscribe")
                    ]])
                )
            else:
                # Неизвестный статус
                await query.edit_message_text(
                    f"❓ Неизвестный статус платежа: {payment_status}\n\n"
                    "Обратитесь к администратору для уточнения."
                )
                
    except Exception as e:
        logger.error(f"Error checking payment status: {e}")
        await query.edit_message_text(
            "❌ Ошибка при проверке статуса платежа.\n\n"
            "Попробуйте позже или обратитесь к администратору."
        )

def validate_email(email: str) -> tuple[bool, str]:
    """
    Валидирует email и возвращает (is_valid, error_message).
    """
    if not email:
        return False, "Email не указан"
    
    # Базовая проверка формата
    email = email.strip().lower()
    
    # Регулярное выражение для email
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, email):
        return False, "Неверный формат email"
    
    # Проверка длины
    if len(email) < 6:  # a@b.co минимум
        return False, "Email слишком короткий"
    
    if len(email) > 100:
        return False, "Email слишком длинный"
    
    # Проверка домена
    domain = email.split('@')[1]
    
    # Список распространенных опечаток
    common_typos = {
        'gmail.con': 'gmail.com',
        'gmail.co': 'gmail.com',
        'gmail.ru': 'gmail.com',
        'gmai.com': 'gmail.com',
        'gmial.com': 'gmail.com',
        'gnail.com': 'gmail.com',
        'yamdex.ru': 'yandex.ru',
        'yadex.ru': 'yandex.ru',
        'yandex.com': 'yandex.ru',
        'mail.ri': 'mail.ru',
        'mail.tu': 'mail.ru',
        'maio.ru': 'mail.ru',
        'maol.ru': 'mail.ru',
        'mali.ru': 'mail.ru',
        'outlok.com': 'outlook.com',
        'outlok.ru': 'outlook.com',
        'hotmial.com': 'hotmail.com',
        'hotmai.com': 'hotmail.com'
    }
    
    if domain in common_typos:
        return False, f"Возможна опечатка. Вы имели в виду @{common_typos[domain]}?"
    
    # Проверка на невалидные домены
    invalid_domains = ['gmail.con', 'gmail.co', 'test.com', 'example.com']
    if domain in invalid_domains:
        return False, f"Домен {domain} недействителен"
    
    # Проверка точек в домене
    if '..' in domain:
        return False, "Двойные точки в домене недопустимы"
    
    # Минимальная длина домена
    if len(domain) < 4:  # x.co минимум
        return False, "Домен слишком короткий"
    
    return True, ""

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
    """Показывает модульный интерфейс подписок."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        
        # Функция для безопасного редактирования
        async def safe_edit_message(text, reply_markup, parse_mode=None):  # ✅ Добавлен параметр parse_mode
            try:
                await query.edit_message_text(
                    text,
                    parse_mode=parse_mode or ParseMode.HTML,  # Используем переданный или HTML по умолчанию
                    reply_markup=reply_markup
                )
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise
                
        edit_func = safe_edit_message
    else:
        # Вызов из команды /subscribe
        edit_func = lambda text, reply_markup, parse_mode=ParseMode.HTML: update.message.reply_text(
            text, 
            parse_mode=parse_mode, 
            reply_markup=reply_markup
        )
    
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    # ВАЖНО: Устанавливаем флаг, что пользователь в процессе оплаты
    context.user_data['in_payment_process'] = True
    
    # Проверяем пробный период
    has_trial = await subscription_manager.has_used_trial(user_id)
    
    # ИСПРАВЛЕНИЕ: Используем правильный метод get_user_modules
    modules_data = await subscription_manager.get_user_modules(user_id)
    # Извлекаем только коды модулей для обратной совместимости
    active_modules = [module['module_code'] for module in modules_data] if modules_data else []
    
    text = "💎 <b>Модульная система подписок</b>\n\n"
    
    if modules_data:  # Используем modules_data для проверки наличия модулей
        text += "✅ <b>Ваши активные модули:</b>\n"
        module_names = {
            'test_part': '📝 Тестовая часть',
            'task19': '🎯 Задание 19',
            'task20': '📖 Задание 20',
            'task24': '💎 Задание 24',
            'task25': '✍️ Задание 25'
        }
        for module in modules_data:
            name = module_names.get(module['module_code'], module['module_code'])
            expires = module['expires_at'].strftime('%d.%m.%Y')
            text += f"• {name} (до {expires})\n"
        text += "\n"
    
    text += "<b>Доступные тарифы:</b>\n\n"
    
    # Пробный период
    if not has_trial:
        text += "🎁 <b>Пробный период</b> — 1₽\n"
        text += "   • Полный доступ на 7 дней\n"
        text += "   • Все модули включены\n\n"
    
    # Пакет "Вторая часть"
    text += "🎯 <b>Пакет «Вторая часть»</b> — 499₽/мес\n"
    text += "   • Задание 19 (Примеры)\n"
    text += "   • Задание 20 (Суждения)\n"
    text += "   • Задание 25 (Развёрнутый ответ)\n"
    text += "   <i>Экономия 98₽ по сравнению с покупкой по отдельности</i>\n\n"
    
    text += "👑 <b>Полный доступ</b> — 999₽/мес\n"
    text += "   • Все модули тестовой части\n"
    text += "   • Все задания второй части (19, 20, 24, 25)\n"
    text += "   • Приоритетная поддержка\n"
    text += "   <i>Экономия 346₽ по сравнению с покупкой по отдельности</i>\n\n"
    
    text += "📚 Или выберите отдельные модули\n"
    
    keyboard = []
    
    # Кнопки
    if not has_trial:
        keyboard.append([
            InlineKeyboardButton(
                "🎁 Пробный период - 1₽ (7 дней)",
                callback_data="pay_trial"
            )
        ])
    
    keyboard.extend([
        [InlineKeyboardButton(
            "👑 Полный доступ - 999₽/мес",
            callback_data="pay_package_full"
        )],
        [InlineKeyboardButton(
            "🎯 Пакет «Вторая часть» - 499₽/мес",
            callback_data="pay_package_second"
        )],
        [InlineKeyboardButton(
            "📚 Выбрать отдельные модули",
            callback_data="pay_individual_modules"
        )]
    ])
    
    if active_modules:  # Используем active_modules для проверки
        keyboard.append([
            InlineKeyboardButton("📋 Мои подписки", callback_data="my_subscriptions")
        ])
    
    keyboard.append([
        InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
    ])
    
    await edit_func(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    # ИСПРАВЛЕНО: Проверяем источник вызова
    # Возвращаем CHOOSING_PLAN только если мы в ConversationHandler
    if update.message:
        # Вызов через команду /subscribe - мы в ConversationHandler
        return CHOOSING_PLAN
    elif update.callback_query:
        # Проверяем callback_data
        if update.callback_query.data in ["subscribe", "subscribe_start"]:
            # Эти callbacks являются entry_points в ConversationHandler
            return CHOOSING_PLAN
        else:
            # Для других callbacks (например, my_subscriptions) не возвращаем состояние
            return
    
    # По умолчанию не возвращаем состояние
    return


@safe_handler()
async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор плана подписки."""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем план из callback_data
    plan_id = query.data.replace("pay_", "")
    
    logger.info(f"Plan selected: {plan_id}")
    
    # Проверяем, какой это план
    if plan_id == "trial":
        # ВАЖНО: Для пробной подписки устанавливаем правильные значения
        plan_id = "trial_7days"
        context.user_data['is_trial'] = True
        context.user_data['selected_plan'] = plan_id
        context.user_data['duration_months'] = 1
        context.user_data['total_price'] = 1  # КРИТИЧНО: 1 рубль для триала
        context.user_data['base_price'] = 1
        context.user_data['plan_name'] = "🎁 Пробный период 7 дней"
        
        logger.info("Trial selected: price set to 1₽")
        
        # Сразу запрашиваем email для триала
        return await request_email_for_trial(update, context)
        
    elif plan_id == "package_full":
        plan_id = "package_full"
        context.user_data['is_trial'] = False
    elif plan_id == "package_second":
        plan_id = "package_second"
        context.user_data['is_trial'] = False
    elif plan_id == "individual_modules":
        return await show_individual_modules(update, context)
    
    # Сохраняем выбранный план
    context.user_data['selected_plan'] = plan_id
    
    # Получаем информацию о плане
    from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
    plan = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
    
    if not plan:
        logger.error(f"Plan {plan_id} not found in configs!")
        await query.edit_message_text("❌ Ошибка: выбранный план не найден")
        return ConversationHandler.END
    
    # Сохраняем информацию о плане
    context.user_data['plan_info'] = plan
    context.user_data['plan_name'] = plan['name']
    context.user_data['base_price'] = plan['price_rub']
    
    logger.info(f"Plan info loaded: {plan['name']}, base price: {plan['price_rub']}₽")
    
    # Показываем варианты длительности
    return await show_duration_options(update, context)


# Также исправим request_email_for_trial:
@safe_handler()
async def request_email_for_trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает email для пробной подписки."""
    query = update.callback_query
    
    # ВАЖНО: Убеждаемся, что цена установлена правильно
    context.user_data['total_price'] = 1
    context.user_data['duration_months'] = 1
    context.user_data['plan_name'] = "🎁 Пробный период 7 дней"
    
    text = """🎁 <b>Оформление пробного периода</b>

Вы получите:
✅ Полный доступ ко всем материалам
✅ 7 дней бесплатного использования
✅ Возможность оценить все функции

💰 Стоимость: <b>1 ₽</b>

📧 Введите ваш email для отправки чека:"""
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_payment")]]
    
    try:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.debug("Message already showing trial email request")
            await query.answer("Введите ваш email в чат", show_alert=False)
        else:
            logger.error(f"Error in request_email_for_trial: {e}")
            await query.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    return ENTERING_EMAIL

@safe_handler()
async def request_email_for_trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает email для пробной подписки."""
    query = update.callback_query
    
    text = """🎁 <b>Оформление пробного периода</b>

Вы получите:
✅ Полный доступ ко всем материалам
✅ 7 дней бесплатного использования
✅ Возможность оценить все функции

💰 Стоимость: <b>1 ₽</b>

📧 Введите ваш email для отправки чека:"""
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_payment")]]
    
    try:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.debug("Message already showing trial email request")
            await query.answer("Введите ваш email в чат", show_alert=False)
        else:
            logger.error(f"Error in request_email_for_trial: {e}")
            # Отправляем новое сообщение
            await query.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    return ENTERING_EMAIL

@safe_handler()
async def cmd_debug_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для отладки подписки пользователя."""
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    text = f"🔍 <b>Отладочная информация для пользователя {user_id}</b>\n\n"
    text += f"SUBSCRIPTION_MODE: {SUBSCRIPTION_MODE}\n\n"
    
    # Проверяем общую подписку
    subscription = await subscription_manager.check_active_subscription(user_id)
    if subscription:
        text += "✅ <b>Активная подписка найдена:</b>\n"
        text += f"План: {subscription.get('plan_id')}\n"
        text += f"Истекает: {subscription.get('expires_at')}\n"
        text += f"Активные модули: {subscription.get('active_modules', [])}\n\n"
    else:
        text += "❌ <b>Активная подписка не найдена</b>\n\n"
    
    # Проверяем модули
    if SUBSCRIPTION_MODE == 'modular':
        modules = await subscription_manager.get_user_modules(user_id)
        if modules:
            text += "📦 <b>Активные модули:</b>\n"
            for module in modules:
                text += f"• {module['module_code']} до {module['expires_at']}\n"
        else:
            text += "📦 <b>Нет активных модулей</b>\n"
        
        text += "\n<b>Проверка доступа к модулям:</b>\n"
        for module_code in ['test_part', 'task19', 'task20', 'task24', 'task25']:
            has_access = await subscription_manager.check_module_access(user_id, module_code)
            text += f"• {module_code}: {'✅' if has_access else '❌'}\n"
    
    # Проверяем последние платежи
    try:
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            cursor = await conn.execute(
                """
                SELECT order_id, plan_id, status, created_at 
                FROM payments 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT 5
                """,
                (user_id,)
            )
            payments = await cursor.fetchall()
            
            if payments:
                text += "\n💳 <b>Последние платежи:</b>\n"
                for payment in payments:
                    text += f"• {payment[1]} - {payment[2]} ({payment[3]})\n"
    except Exception as e:
        logger.error(f"Error getting payments: {e}")
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

@safe_handler()
async def show_individual_modules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список отдельных модулей для выбора."""
    query = update.callback_query
    
    # Сразу отвечаем на callback чтобы убрать "часики"
    if query:
        await query.answer()
    
    # Инициализируем список выбранных модулей если его нет
    if 'selected_modules' not in context.user_data:
        context.user_data['selected_modules'] = []
    
    selected = context.user_data['selected_modules']
    
    text = "📚 <b>Выберите модули для подписки</b>\n\n"
    text += "Нажмите на модуль чтобы добавить/убрать его из корзины:\n\n"
    
    keyboard = []
    total_price = 0
    
    # Группируем модули по типам
    individual_modules = {
        k: v for k, v in MODULE_PLANS.items() 
        if v.get('type') == 'individual'
    }
    
    # ИСПРАВЛЕНИЕ: Проверяем, что модули существуют
    if not individual_modules:
        logger.error("No individual modules found in MODULE_PLANS")
        logger.error(f"MODULE_PLANS keys: {list(MODULE_PLANS.keys())}")
        error_text = "❌ Модули временно недоступны. Обратитесь к администратору."
        error_keyboard = [[
            InlineKeyboardButton("⬅️ Назад", callback_data="subscribe")
        ]]
        
        if query:
            try:
                await query.edit_message_text(
                    error_text,
                    reply_markup=InlineKeyboardMarkup(error_keyboard)
                )
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error editing message: {e}")
                    raise
        else:
            await update.message.reply_text(
                error_text,
                reply_markup=InlineKeyboardMarkup(error_keyboard)
            )
        return CHOOSING_MODULES
    
    # Добавляем модули в клавиатуру
    for module_id, module in individual_modules.items():
        icon = "✅" if module_id in selected else "⬜"
        button_text = f"{icon} {module['name']} - {module['price_rub']}₽"
        
        keyboard.append([
            InlineKeyboardButton(button_text, callback_data=f"toggle_{module_id}")
        ])
        
        # Добавляем кнопку информации рядом
        keyboard[-1].append(
            InlineKeyboardButton("ℹ️", callback_data=f"info_{module_id}")
        )
        
        if module_id in selected:
            total_price += module['price_rub']
    
    # Показываем итоговую цену если есть выбранные модули
    if selected:
        text += f"\n💰 <b>Итого: {total_price}₽/месяц</b>\n"
        text += f"📋 Выбрано модулей: {len(selected)}\n"
        
        # Кнопка продолжить
        keyboard.append([
            InlineKeyboardButton(
                f"✅ Продолжить с выбранными ({len(selected)})",
                callback_data="proceed_with_modules"
            )
        ])
    else:
        text += "\n💡 <i>Выберите хотя бы один модуль для продолжения</i>"
    
    # Кнопка назад
    keyboard.append([
        InlineKeyboardButton("⬅️ Назад к планам", callback_data="back_to_main")
    ])
    
    # Редактируем сообщение или отправляем новое
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        try:
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except BadRequest as e:
            # Если сообщение не изменилось, просто игнорируем ошибку
            if "Message is not modified" in str(e):
                logger.debug("Message content unchanged in show_individual_modules")
                # Можно отправить alert пользователю
                await query.answer("Список модулей уже отображается", show_alert=False)
            else:
                # Если другая ошибка - логируем и пробуем отправить новое сообщение
                logger.error(f"Error editing message in show_individual_modules: {e}")
                try:
                    await query.message.reply_text(
                        text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as send_error:
                    logger.error(f"Failed to send new message: {send_error}")
                    raise
    else:
        # Если нет query (вызов через команду), отправляем новое сообщение
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    
    return CHOOSING_MODULES

@safe_handler()
async def toggle_module_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает выбор модуля (добавляет/удаляет из корзины)."""
    query = update.callback_query
    await query.answer()
    
    module_id = query.data.replace("toggle_", "")
    
    # Инициализируем список если его нет
    if 'selected_modules' not in context.user_data:
        context.user_data['selected_modules'] = []
    
    selected = context.user_data['selected_modules']
    
    # Переключаем состояние модуля
    if module_id in selected:
        selected.remove(module_id)
        await query.answer(f"❌ Модуль удален из корзины", show_alert=False)
    else:
        selected.append(module_id)
        module_name = MODULE_PLANS.get(module_id, {}).get('name', 'Модуль')
        await query.answer(f"✅ {module_name} добавлен в корзину", show_alert=False)
    
    # Обновляем список
    return await show_individual_modules(update, context)

@safe_handler()
async def show_module_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает подробную информацию о модуле."""
    query = update.callback_query
    
    # Сразу отвечаем на callback чтобы убрать "часики"
    await query.answer()
    
    # Получаем module_id из callback_data
    module_id = query.data.replace("info_", "")
    
    # Ищем модуль в MODULE_PLANS
    module = MODULE_PLANS.get(module_id)
    
    if not module:
        await query.answer("❌ Модуль не найден", show_alert=True)
        return CHOOSING_MODULES
    
    # Формируем подробное описание
    info_lines = []
    info_lines.append(f"📚 <b>{module['name']}</b>\n")
    info_lines.append(f"<i>{module.get('description', '')}</i>\n")
    
    # Добавляем детальное описание если есть
    if 'detailed_description' in module:
        info_lines.append("\n<b>Что включено:</b>")
        for item in module.get('detailed_description', []):
            info_lines.append(f"  • {item}")
    elif 'features' in module:
        info_lines.append("\n<b>Что включено:</b>")
        for feature in module.get('features', []):
            info_lines.append(f"  • {feature}")
    
    info_lines.append(f"\n💰 <b>Стоимость:</b> {module['price_rub']}₽/месяц")
    
    # Добавляем информацию о скидках при длительной подписке
    if DURATION_DISCOUNTS:
        info_lines.append("\n<b>Скидки при оплате на несколько месяцев:</b>")
        for months, discount_info in DURATION_DISCOUNTS.items():
            if months > 1:
                total = int(module['price_rub'] * discount_info['multiplier'])
                saved = (module['price_rub'] * months) - total
                info_lines.append(f"  • {discount_info['label']}: {total}₽ (экономия {saved}₽)")
    
    # Собираем текст
    full_text = "\n".join(info_lines)
    
    # Создаем клавиатуру с кнопкой возврата
    keyboard = [[
        InlineKeyboardButton("⬅️ Назад к выбору", callback_data="back_to_module_selection")
    ]]
    
    # Редактируем сообщение с обработкой ошибок
    try:
        await query.edit_message_text(
            full_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            # Если контент не изменился, показываем alert с информацией
            alert_text = (
                f"{module['name']}\n"
                f"Стоимость: {module['price_rub']}₽/мес\n"
                f"{module.get('description', '')[:100]}"
            )
            await query.answer(alert_text, show_alert=True)
        else:
            logger.error(f"Error editing message in show_module_info: {e}")
            # Пробуем отправить новое сообщение
            try:
                await query.message.reply_text(
                    full_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception as send_error:
                logger.error(f"Failed to send new message: {send_error}")
                # В крайнем случае показываем alert
                await query.answer(
                    "Не удалось показать информацию о модуле. Попробуйте еще раз.",
                    show_alert=True
                )
    
    return CHOOSING_MODULES

@safe_handler()
async def back_to_module_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору модулей из информации о модуле."""
    query = update.callback_query
    
    # Отвечаем на callback
    if query:
        await query.answer()
    
    # Вызываем show_individual_modules для возврата к списку
    return await show_individual_modules(update, context)
    
# Добавьте обработчик для продолжения с выбранными модулями:

@safe_handler()
async def proceed_with_selected_modules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продолжает оформление с выбранными модулями."""
    query = update.callback_query
    await query.answer()
    
    selected = context.user_data.get('selected_modules', [])
    
    if not selected:
        await query.answer("Выберите хотя бы один модуль", show_alert=True)
        return CHOOSING_MODULES
    
    # Проверяем что все выбранные модули существуют
    valid_modules = []
    for module_id in selected:
        if module_id in MODULE_PLANS:
            valid_modules.append(module_id)
        else:
            logger.warning(f"Invalid module_id in selection: {module_id}")
    
    if not valid_modules:
        await query.answer("❌ Ошибка: выбранные модули не найдены", show_alert=True)
        context.user_data['selected_modules'] = []
        return await show_individual_modules(update, context)
    
    # Используем только валидные модули
    selected = valid_modules
    context.user_data['selected_modules'] = selected
    
    # Создаем комбинированный план из выбранных модулей
    total_price = sum(MODULE_PLANS[m]['price_rub'] for m in selected)
    module_names = [MODULE_PLANS[m]['name'] for m in selected]
    
    # Сохраняем как custom план
    # Упрощаем ID для избежания слишком длинных имен
    modules_short = [m.replace('module_', '').replace('_', '') for m in selected]
    custom_plan_id = f"custom_{'_'.join(modules_short[:3])}"  # Берем только первые 3 для краткости
    if len(modules_short) > 3:
        custom_plan_id += f"_{len(modules_short)}m"  # Добавляем счетчик модулей
    
    context.user_data['selected_plan'] = custom_plan_id
    context.user_data['custom_plan'] = {
        'name': f"Комплект: {', '.join(module_names[:2])}" + (f" и еще {len(module_names)-2}" if len(module_names) > 2 else ""),
        'price_rub': total_price,
        'modules': [m.replace('module_', '') for m in selected],
        'type': 'custom',
        'duration_days': 30
    }
    
    # Логируем для отладки
    logger.info(f"Created custom plan: {custom_plan_id} with modules: {selected}")
    
    # Переходим к выбору длительности
    return await show_duration_options(update, context)

@safe_handler()
async def show_duration_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает варианты длительности подписки с обработкой ошибок редактирования."""
    query = update.callback_query
    await query.answer()
    
    context.user_data['in_payment_process'] = True
    
    plan_id = context.user_data['selected_plan']
    
    # Проверяем план
    if plan_id.startswith('custom_'):
        plan = context.user_data.get('custom_plan')
        if not plan:
            logger.error(f"Custom plan data not found for {plan_id}")
            await query.edit_message_text("❌ Ошибка: данные плана не найдены")
            return ConversationHandler.END
    else:
        # Для обычных планов ищем в обоих словарях
        plan = MODULE_PLANS.get(plan_id)
        if not plan:
            plan = SUBSCRIPTION_PLANS.get(plan_id)
        
        if not plan:
            logger.error(f"Plan not found in show_duration_options: {plan_id}")
            logger.error(f"Available MODULE_PLANS: {list(MODULE_PLANS.keys())}")
            logger.error(f"Available SUBSCRIPTION_PLANS: {list(SUBSCRIPTION_PLANS.keys())}")
            await query.edit_message_text("❌ Ошибка: план не найден")
            return ConversationHandler.END
    
    # Формируем текст и клавиатуру
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
            InlineKeyboardButton(button_text, callback_data=f"duration_{months}")
        ])
    
    # Кнопка назад в зависимости от типа плана
    if plan_id.startswith('custom_'):
        keyboard.append([
            InlineKeyboardButton("⬅️ Назад к выбору модулей", callback_data="back_to_modules")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_plans")
        ])
    
    # Пытаемся отредактировать сообщение с обработкой ошибки
    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    except BadRequest as e:
        # Если сообщение не изменилось - просто игнорируем
        if "Message is not modified" in str(e):
            logger.debug(f"Message already showing duration options for plan {plan_id}")
            # Можем показать небольшое уведомление пользователю
            await query.answer("Выберите срок подписки", show_alert=False)
        else:
            # Если другая ошибка - логируем и пробуем отправить новое сообщение
            logger.error(f"Error editing message in show_duration_options: {e}")
            try:
                await query.message.reply_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            except Exception as send_error:
                logger.error(f"Failed to send new message: {send_error}")
                raise
    
    return CHOOSING_DURATION


@safe_handler()
async def handle_duration_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор длительности подписки."""
    query = update.callback_query
    await query.answer()
    
    logger.info(f"handle_duration_selection called with data: {query.data}")
    
    try:
        # Извлекаем длительность из callback_data
        duration = int(query.data.split('_')[1])
        context.user_data['selected_duration'] = duration
        
        # Получаем план из контекста
        plan_id = context.user_data.get('selected_plan')
        
        if not plan_id:
            await query.edit_message_text(
                "❌ Ошибка: не выбран план подписки.\n"
                "Пожалуйста, начните заново с /subscribe"
            )
            return ConversationHandler.END
        
        # Рассчитываем правильную цену
        total_price = calculate_subscription_price(plan_id, duration)
        
        # ВАЖНО: Сохраняем правильную цену в контекст
        context.user_data['total_price'] = total_price
        
        logger.info(f"Selected duration: {duration} months, calculated price: {total_price}₽")
        
        # Получаем информацию о плане
        from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS, DURATION_DISCOUNTS
        
        if plan_id in MODULE_PLANS:
            plan_info = MODULE_PLANS[plan_id]
            plan_name = plan_info['name']
        elif plan_id in SUBSCRIPTION_PLANS:
            plan_info = SUBSCRIPTION_PLANS[plan_id]
            plan_name = plan_info['name']
        else:
            plan_name = plan_id
            plan_info = {}
        
        # Получаем label для длительности
        duration_label = DURATION_DISCOUNTS.get(duration, {}).get('label', f'{duration} мес.')
        
        # Формируем текст подтверждения
        text = f"""📋 <b>Подтверждение заказа</b>

🎯 <b>Выбранный план:</b> {plan_name}
📅 <b>Период:</b> {duration_label}
💰 <b>Стоимость:</b> {total_price} ₽

"""
        
        # Добавляем информацию о скидке если есть
        if duration in DURATION_DISCOUNTS and duration > 1:
            base_price = plan_info.get('price_rub', 999)
            full_price = base_price * duration
            discount = full_price - total_price
            if discount > 0:
                discount_percent = round((discount / full_price) * 100)
                text += f"💡 <b>Ваша экономия:</b> {discount} ₽ ({discount_percent}%)\n\n"
        
        text += "Хотите включить автоматическое продление подписки?"
        
        # Кнопки для выбора автопродления
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, включить автопродление", callback_data="enable_auto_renewal_payment"),
                InlineKeyboardButton("❌ Нет, спасибо", callback_data="disable_auto_renewal_payment")
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_duration_selection")],
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_payment")]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CONFIRMING
        
    except ValueError:
        logger.error(f"Invalid duration in callback_data: {query.data}")
        await query.edit_message_text(
            "❌ Ошибка при выборе длительности.\n"
            "Пожалуйста, попробуйте снова."
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in handle_duration_selection: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка.\n"
            "Пожалуйста, попробуйте позже."
        )
        return ConversationHandler.END


def calculate_custom_base_price(modules):
    """Рассчитывает базовую месячную цену для кастомного набора модулей."""
    # Цены на модули (месячная стоимость)
    module_prices = {
        'test_part': 298,      # Тестовая часть
        'task19': 197,         # Задание 19
        'task20': 197,         # Задание 20
        'task24': 347,         # Задание 24 (премиум)
        'task25': 197,         # Задание 25
        # Добавьте другие модули если есть
    }
    
    total = 0
    for module in modules:
        total += module_prices.get(module, 100)  # По умолчанию 100₽ если модуль не найден
    
    return total


@safe_handler()
async def request_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает email пользователя."""
    
    # Определяем источник вызова
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        message = query.message
        is_callback = True
    else:
        message = update.message
        is_callback = False
    
    # Получаем данные о выбранном плане
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    total_price = context.user_data.get('total_price')
    plan_name = context.user_data.get('plan_name', 'Подписка')
    
    # Если цена не сохранена, рассчитываем заново
    if not total_price:
        from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
        plan = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
        if plan:
            total_price = calculate_subscription_price(plan_id, duration, plan)
            context.user_data['total_price'] = total_price
        else:
            total_price = 490 * duration  # Fallback
    
    text = f"""📧 <b>Введите email для отправки чека</b>

📦 План: <b>{plan_name}</b>
⏱ Срок: <b>{duration} мес.</b>
💰 К оплате: <b>{total_price} ₽</b>

✉️ На указанный email будет отправлен чек об оплате.

Введите ваш email:"""
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_payment")]]
    
    # Используем try/except для обработки ошибки "Message is not modified"
    try:
        if is_callback:
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Если вызов не из callback, отправляем новое сообщение
            await message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            # Если сообщение не изменилось, просто логируем и продолжаем
            logger.debug("Message already showing email request")
            # Можно показать небольшое уведомление
            if is_callback:
                await query.answer("Введите ваш email в чат", show_alert=False)
        else:
            # Если другая ошибка, пробуем отправить новое сообщение
            logger.error(f"Error in request_email: {e}")
            await message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    return ENTERING_EMAIL

# payment/handlers.py - Исправленная версия handle_email_input
@safe_handler()
async def handle_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод email с улучшенной валидацией."""
    email = update.message.text.strip().lower()
    user_id = update.effective_user.id
    
    # Валидация email
    is_valid, error_message = validate_email(email)
    
    if not is_valid:
        # Показываем ошибку и просим ввести заново
        keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_payment")]]
        
        await update.message.reply_text(
            f"❌ {error_message}\n\n"
            f"Вы ввели: <code>{email}</code>\n\n"
            "Пожалуйста, введите корректный email.\n"
            "Например: ivanov@gmail.com",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ENTERING_EMAIL  # Остаемся в том же состоянии
    
    # Исправляем распространенные опечатки автоматически
    domain = email.split('@')[1]
    auto_corrections = {
        'gmail.comm': 'gmail.com',
        'gmai.com': 'gmail.com',
        'gmil.com': 'gmail.com',
        'yamdex.ru': 'yandex.ru',
        'yadex.ru': 'yandex.ru',
        'maio.ru': 'mail.ru'
    }
    
    if domain in auto_corrections:
        corrected_email = email.replace(domain, auto_corrections[domain])
        
        # Спрашиваем подтверждение
        keyboard = [
            [InlineKeyboardButton(f"✅ Да, использовать {corrected_email}", 
                                callback_data=f"use_email_{corrected_email}")],
            [InlineKeyboardButton(f"❌ Нет, оставить {email}", 
                                callback_data=f"use_email_{email}")],
            [InlineKeyboardButton("🔄 Ввести заново", callback_data="retry_email")]
        ]
        
        await update.message.reply_text(
            f"🔍 Обнаружена возможная опечатка.\n\n"
            f"Вы ввели: <code>{email}</code>\n"
            f"Возможно, вы имели в виду: <code>{corrected_email}</code>?",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # Сохраняем оба варианта
        context.user_data['original_email'] = email
        context.user_data['corrected_email'] = corrected_email
        
        return ENTERING_EMAIL
    
    # Email валидный, сохраняем
    context.user_data['email'] = email
    
    # Сохраняем в БД
    try:
        from payment.subscription_manager import SubscriptionManager
        subscription_manager = SubscriptionManager()
        
        # Сохраняем email в БД
        import aiosqlite
        async with aiosqlite.connect(subscription_manager.database_file) as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO user_emails (user_id, email, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (user_id, email)
            )
            await conn.commit()
            
        logger.info(f"Email saved for user {user_id}: {email}")
        
    except Exception as e:
        logger.error(f"Error saving email: {e}")
    
    # Получаем данные о плане
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    is_trial = context.user_data.get('is_trial', False)

    # Получаем план
    if plan_id.startswith('custom_'):
        plan = context.user_data.get('custom_plan')
        if not plan:
            logger.error(f"Custom plan data not found in handle_email_input for {plan_id}")
            await update.message.reply_text("❌ Ошибка: данные плана не найдены")
            return ConversationHandler.END
    else:
        plan = MODULE_PLANS.get(plan_id)
        if not plan:
            plan = SUBSCRIPTION_PLANS.get(plan_id)
        
        if not plan:
            logger.error(f"Plan not found in handle_email_input: {plan_id}")
            await update.message.reply_text("❌ Ошибка: план не найден")
            return ConversationHandler.END

    # Сохраняем данные плана для последующего использования
    context.user_data['plan_name'] = plan['name']
    
    # Рассчитываем цены и сохраняем в контекст для использования в следующих шагах
    if is_trial:
        # Пробный период - 1 рубль
        context.user_data['total_price'] = 1
        context.user_data['base_price'] = plan['price_rub']  # Цена после триала
        context.user_data['discount_info'] = {'label': '7 дней (пробный период)'}
        context.user_data['saved_amount'] = 0
    else:
        # Рассчитываем цену с учетом скидок
        base_price = plan['price_rub']
        
        # Импортируем конфиг для скидок
        from payment.config import DURATION_DISCOUNTS
        
        # Получаем информацию о скидке для выбранного срока
        discount_info = DURATION_DISCOUNTS.get(duration, {
            'multiplier': duration, 
            'label': f'{duration} мес.'
        })
        
        # Рассчитываем итоговую цену
        multiplier = discount_info.get('multiplier', duration)
        total_price = int(base_price * multiplier)
        
        # Сохраняем все рассчитанные данные
        context.user_data['total_price'] = total_price
        context.user_data['base_price'] = base_price
        context.user_data['discount_info'] = discount_info
        context.user_data['saved_amount'] = (base_price * duration) - total_price if duration > 1 and multiplier < duration else 0

    # Сохраняем месячную цену для автопродления
    context.user_data['monthly_price'] = plan['price_rub']
    
    # ============= ИЗМЕНЕНИЕ: Переход к выбору автопродления =============
    # Вместо показа подтверждения сразу, показываем экран выбора автопродления
    
    # Уведомляем что email сохранен
    await update.message.reply_text(
        f"✅ Email сохранен: {email}\n\n"
        "Настройка способа оплаты..."
    )
    
    # Проверяем, импортирована ли функция show_auto_renewal_choice
    try:
        # Пробуем использовать новую функцию из модуля consent
        from .auto_renewal_consent import show_auto_renewal_choice
        return await show_auto_renewal_choice(update, context)
    except ImportError:
        # Если модуль еще не создан, используем временную заглушку
        logger.warning("auto_renewal_consent module not found, using fallback")
        
        # Временный fallback - показываем простое подтверждение
        if is_trial:
            text = f"""📋 <b>Подтверждение заказа</b>

✅ План: {plan['name']}
📧 Email: {email}
📅 Срок: 7 дней (пробный период)
💰 К оплате: 1 ₽

Все верно?"""
        else:
            # Получаем сохраненные данные
            total_price = context.user_data.get('total_price')
            discount_info = context.user_data.get('discount_info')
            saved_amount = context.user_data.get('saved_amount', 0)
            
            text = f"""📋 <b>Подтверждение заказа</b>

✅ План: {plan['name']}
📧 Email: {email}
📅 Срок: {discount_info.get('label', f'{duration} мес.')}"""
            
            # Добавляем информацию об экономии если есть скидка
            if saved_amount > 0:
                text += f" (экономия {saved_amount}₽)"
            
            text += f"\n💰 К оплате: {total_price} ₽\n\nВсе верно?"

        # Создаем клавиатуру
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить и оплатить", callback_data="confirm_payment")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_payment")]
        ]

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return CONFIRMING

@safe_handler()
async def handle_email_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает подтверждение исправленного email."""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("use_email_"):
        # Извлекаем email из callback_data
        email = query.data.replace("use_email_", "")
        context.user_data['email'] = email
        
        # Сохраняем в БД
        user_id = update.effective_user.id
        try:
            from payment.subscription_manager import SubscriptionManager
            subscription_manager = SubscriptionManager()
            
            import aiosqlite
            async with aiosqlite.connect(subscription_manager.database_file) as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO user_emails (user_id, email, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    """,
                    (user_id, email)
                )
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error saving email: {e}")
        
        await query.edit_message_text(
            f"✅ Email сохранен: {email}\n\n"
            "Настройка способа оплаты..."
        )
        
        # Переход к выбору автопродления
        from .auto_renewal_consent import show_auto_renewal_choice
        return await show_auto_renewal_choice(update, context)
    
    elif query.data == "retry_email":
        await query.edit_message_text(
            "📧 Введите ваш email для отправки чека:"
        )
        return ENTERING_EMAIL

@safe_handler()
async def show_auto_renewal_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает опции автопродления после ввода email."""
    query = update.callback_query
    if query:
        await query.answer()
    
    # Получаем информацию о выбранном плане
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    
    # Определяем цену для ежемесячного продления
    if plan_id.startswith('custom_'):
        modules = context.user_data.get('selected_modules', [])
        monthly_price = calculate_custom_price(modules, 1)
        plan_name = f"Пакет из {len(modules)} модулей"
    else:
        from .config import MODULE_PLANS, SUBSCRIPTION_PLANS
        plan = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
        monthly_price = plan['price_rub']
        plan_name = plan['name']
    
    # Текст с полным описанием автопродления (по требованиям Т-Банка)
    text = f"""🔄 <b>Настройка автоматического продления</b>

<b>Ваша подписка:</b>
📦 {plan_name}
⏱ Первый период: {duration} мес.
💰 Далее: {monthly_price} ₽/месяц

<b>Выберите вариант оплаты:</b>

✅ <b>С автопродлением (рекомендуется)</b>
• Автоматическое списание {monthly_price} ₽ каждый месяц
• Непрерывный доступ к материалам
• Уведомление за 3 дня до списания
• Отмена в любой момент через /my_subscriptions
• Первое автосписание: {(datetime.now() + timedelta(days=30*duration)).strftime('%d.%m.%Y')}

❌ <b>Без автопродления</b>
• Разовая оплата на {duration} мес.
• Нужно будет продлевать вручную
• Риск потерять доступ при забывчивости

⚠️ <b>Важно:</b> Выбирая автопродление, вы соглашаетесь на ежемесячные списания до момента отмены подписки."""
    
    keyboard = [
        [InlineKeyboardButton(
            "✅ Включить автопродление", 
            callback_data="consent_auto_renewal"
        )],
        [InlineKeyboardButton(
            "❌ Оплатить без автопродления", 
            callback_data="no_auto_renewal"
        )],
        [InlineKeyboardButton(
            "ℹ️ Подробнее об условиях", 
            callback_data="auto_renewal_terms"
        )]
    ]
    
    if query:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return AUTO_RENEWAL_CHOICE  # Новое состояние

@safe_handler()
async def handle_auto_renewal_consent_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор пользователя по автопродлению."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "consent_auto_renewal":
        # Показываем финальное подтверждение с чек-боксом
        await show_final_consent_screen(update, context)
        return FINAL_CONSENT
        
    elif query.data == "no_auto_renewal":
        context.user_data['enable_auto_renewal'] = False
        # Переходим к оплате без автопродления
        return await handle_payment_confirmation_with_recurrent(update, context)
        
    elif query.data == "auto_renewal_terms":
        await show_auto_renewal_terms(update, context)
        return AUTO_RENEWAL_CHOICE

@safe_handler()
async def show_final_consent_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает финальный экран согласия с имитацией чек-бокса."""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    
    # Определяем цену
    if plan_id.startswith('custom_'):
        modules = context.user_data.get('selected_modules', [])
        monthly_price = calculate_custom_price(modules, 1)
        total_price = calculate_custom_price(modules, duration)
    else:
        plan_info = SUBSCRIPTION_PLANS.get(plan_id, {})
        monthly_price = plan_info.get('price_rub', 490)
        total_price = calculate_subscription_price(plan_id, duration, plan_info)
    
    # Проверяем состояние согласия
    consent_given = context.user_data.get('auto_renewal_consent_confirmed', False)
    checkbox = "☑️" if consent_given else "⬜"
    
    text = f"""📋 <b>Подтверждение автоматического продления</b>

<b>Условия подписки:</b>
💳 Первый платеж: {total_price} ₽ (за {duration} мес.)
🔄 Далее: {monthly_price} ₽ ежемесячно
📅 Дата первого автосписания: {(datetime.now() + timedelta(days=30*duration)).strftime('%d.%m.%Y')}

<b>Согласие на автопродление:</b>
{checkbox} Я соглашаюсь на автоматическое ежемесячное списание {monthly_price} ₽ с моей карты для продления подписки. Я понимаю, что:

- Списание будет происходить автоматически каждый месяц
- Я получу уведомление за 3 дня до списания
- Я могу отменить автопродление в любой момент
- При отмене возврат осуществляется согласно правилам сервиса
- Мои платежные данные будут сохранены в защищенном виде

<b>Нажмите на чек-бокс выше, чтобы дать согласие</b>"""
    
    keyboard = []
    
    # Кнопка-чекбокс
    keyboard.append([InlineKeyboardButton(
        f"{checkbox} Согласие на автопродление",
        callback_data="toggle_consent"
    )])
    
    # Кнопки действий
    if consent_given:
        keyboard.append([InlineKeyboardButton(
            "✅ Подтвердить и перейти к оплате",
            callback_data="confirm_with_auto_renewal"
        )])
    else:
        keyboard.append([InlineKeyboardButton(
            "⚠️ Отметьте согласие для продолжения",
            callback_data="need_consent"
        )])
    
    keyboard.append([InlineKeyboardButton(
        "◀️ Назад",
        callback_data="back_to_auto_renewal_options"
    )])
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return FINAL_CONSENT

def calculate_subscription_price(plan_id: str, duration_months: int = 1) -> int:
    """Рассчитывает стоимость подписки с учетом скидок.
    
    Args:
        plan_id: ID плана подписки
        duration_months: Длительность в месяцах
        
    Returns:
        Итоговая стоимость в рублях
    """
    from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS, DURATION_DISCOUNTS
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Определяем источник цен в зависимости от режима и плана
    if plan_id in MODULE_PLANS:
        base_price = MODULE_PLANS[plan_id].get('price_rub', 999)
        logger.info(f"Using MODULE_PLANS price for {plan_id}: {base_price}₽")
    elif plan_id in SUBSCRIPTION_PLANS:
        base_price = SUBSCRIPTION_PLANS[plan_id].get('price_rub', 999)
        logger.info(f"Using SUBSCRIPTION_PLANS price for {plan_id}: {base_price}₽")
    else:
        # Fallback для неизвестных планов
        base_price = 999
        logger.warning(f"Unknown plan {plan_id}, using default price: {base_price}₽")
    
    # Специальная обработка для пробного периода
    if plan_id == 'trial_7days':
        logger.info(f"Trial period detected, returning 1₽")
        return 1
    
    # Применяем множитель для длительности
    if duration_months in DURATION_DISCOUNTS:
        multiplier = DURATION_DISCOUNTS[duration_months].get('multiplier', duration_months)
        total_price = int(base_price * multiplier)
        logger.info(f"Applied discount for {duration_months} months: {base_price}₽ × {multiplier} = {total_price}₽")
    else:
        # Если нет скидки для этой длительности - просто умножаем
        total_price = base_price * duration_months
        logger.info(f"No discount for {duration_months} months, total={total_price}₽")
    
    logger.info(f"Final calculation: plan={plan_id}, base={base_price}₽, duration={duration_months}m, total={total_price}₽")
    
    return total_price

@safe_handler()
async def toggle_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает состояние согласия."""
    query = update.callback_query
    
    # Переключаем состояние
    current = context.user_data.get('auto_renewal_consent_confirmed', False)
    context.user_data['auto_renewal_consent_confirmed'] = not current
    
    if not current:
        # Сохраняем время и данные согласия
        context.user_data['consent_timestamp'] = datetime.now().isoformat()
        context.user_data['consent_user_id'] = update.effective_user.id
        await query.answer("✅ Согласие получено", show_alert=False)
    else:
        await query.answer("Согласие отменено", show_alert=False)
    
    # Обновляем экран
    return await show_final_consent_screen(update, context)

@safe_handler()
async def confirm_with_auto_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждает оплату с автопродлением после получения явного согласия."""
    query = update.callback_query
    
    if not context.user_data.get('auto_renewal_consent_confirmed', False):
        await query.answer(
            "⚠️ Необходимо дать согласие на автопродление",
            show_alert=True
        )
        return FINAL_CONSENT
    
    await query.answer("✅ Переход к оплате...")
    
    # Устанавливаем флаг автопродления
    context.user_data['enable_auto_renewal'] = True
    
    # Переходим к оплате
    return await handle_payment_confirmation_with_recurrent(update, context)

@safe_handler()
async def show_auto_renewal_terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает подробные условия автопродления."""
    query = update.callback_query
    await query.answer()
    
    text = """📜 <b>Условия автоматического продления подписки</b>

<b>1. Общие положения</b>
• Автопродление активируется после первой успешной оплаты
• Списания происходят ежемесячно в день окончания текущего периода
• Услуга предоставляется ИП "Фролов Роман Антонович" (ИНН: 772459778593)

<b>2. Стоимость и списания</b>
• Стоимость указывается при оформлении подписки
• Списание происходит с карты, использованной при первой оплате
• При недостатке средств делается 3 попытки списания

<b>3. Уведомления</b>
• За 3 дня до списания - напоминание на email и в Telegram
• После успешного списания - подтверждение продления
• При проблемах - уведомление с инструкциями

<b>4. Отмена и возврат</b>
• Отмена доступна в любой момент через /my_subscriptions
• Отмена вступает в силу немедленно
• Доступ сохраняется до конца оплаченного периода
• Возврат возможен в течение 14 дней согласно ЗоЗПП

<b>5. Безопасность</b>
• Платежи обрабатывает Т-Банк (лицензия ЦБ РФ №2673)
• Данные карты хранятся в токенизированном виде
• Соответствие стандарту PCI DSS
• Защита 3D-Secure

<b>6. Поддержка</b>
📱 Telegram: @obshestvonapalcahsupport

<b>Нажимая "Согласен", вы принимаете данные условия</b>"""
    
    keyboard = [
        [InlineKeyboardButton("✅ Понятно", callback_data="back_to_auto_renewal_choice")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_auto_renewal_choice")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_payment_confirmation_with_recurrent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает платеж с учетом выбора автопродления."""
    query = update.callback_query
    await query.answer()
    
    try:
        # Получаем данные из контекста
        user_id = update.effective_user.id
        plan_id = context.user_data.get('selected_plan')
        duration = context.user_data.get('selected_duration', 1)
        email = context.user_data.get('user_email', '')
        enable_auto_renewal = context.user_data.get('enable_auto_renewal', False)
        
        # ВАЖНО: Используем сохраненную правильную цену из контекста
        # Если её нет - пересчитываем
        if 'total_price' in context.user_data:
            amount = context.user_data['total_price']
            logger.info(f"Using saved price from context: {amount}₽")
        else:
            amount = calculate_subscription_price(plan_id, duration)
            logger.info(f"Calculated price: {amount}₽")
        
        # Получаем название плана
        from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
        
        if plan_id in MODULE_PLANS:
            plan_name = MODULE_PLANS[plan_id]['name']
        elif plan_id in SUBSCRIPTION_PLANS:
            plan_name = SUBSCRIPTION_PLANS[plan_id]['name']
        else:
            plan_name = plan_id
        
        # Создаем уникальный order_id
        import uuid
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        order_id = f"ORDER_{user_id}_{timestamp}_{uuid.uuid4().hex[:8]}"
        
        # Формируем описание
        description = f"{plan_name} - {duration} мес."
        
        logger.info(f"Creating payment: order_id={order_id}, amount={amount}₽, plan={plan_id}, duration={duration}")
        
        # ИСПРАВЛЕНИЕ: Сохраняем данные заказа напрямую в БД вместо несуществующего метода
        try:
            import aiosqlite
            import json
            from core.db import DATABASE_FILE
            
            metadata = json.dumps({
                'plan_id': plan_id,
                'duration_months': duration,
                'email': email,
                'enable_auto_renewal': enable_auto_renewal
            })
            
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                await conn.execute("""
                    INSERT OR REPLACE INTO payments 
                    (order_id, user_id, plan_id, amount_kopecks, status, metadata, created_at)
                    VALUES (?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
                """, (order_id, user_id, plan_id, amount * 100, metadata))
                await conn.commit()
                logger.info(f"Payment saved to database: {order_id}")
                
        except Exception as e:
            logger.error(f"Error saving payment to database: {e}")
            # Продолжаем даже если не удалось сохранить
        
        # Создаем платеж через Tinkoff
        from payment.tinkoff import TinkoffPayment
        tinkoff = TinkoffPayment()
        
        payment_result = await tinkoff.create_payment(
            order_id=order_id,
            amount_rubles=amount,  # Уже в рублях
            description=description,
            user_id=user_id,
            email=email,
            recurrent=enable_auto_renewal  # Включаем рекуррентные платежи если нужно
        )
        
        if payment_result['success']:
            payment_url = payment_result['payment_url']
            payment_id = payment_result['payment_id']
            
            # ИСПРАВЛЕНИЕ: Обновляем payment_id напрямую в БД
            try:
                async with aiosqlite.connect(DATABASE_FILE) as conn:
                    await conn.execute("""
                        UPDATE payments 
                        SET payment_id = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE order_id = ?
                    """, (payment_id, order_id))
                    await conn.commit()
                    logger.info(f"Updated payment_id for order {order_id}")
            except Exception as e:
                logger.error(f"Error updating payment_id: {e}")
            
            # Показываем кнопку оплаты
            text = f"""💳 <b>Переход к оплате</b>

📋 <b>Ваш заказ:</b>
• План: {plan_name}
• Срок: {duration} мес.
• Сумма: {amount} ₽
{"• Автопродление: ✅ Включено" if enable_auto_renewal else "• Автопродление: ❌ Выключено"}

Нажмите кнопку ниже для перехода на страницу оплаты Т-Банка.

После успешной оплаты вы автоматически получите доступ к материалам."""
            
            keyboard = [
                [InlineKeyboardButton(f"💳 Оплатить {amount} ₽", url=payment_url)],
                [InlineKeyboardButton("🔄 Проверить оплату", callback_data="check_payment")],
                [InlineKeyboardButton("❌ Отменить", callback_data="cancel_payment")]
            ]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Отправляем уведомление админу
            from payment.config import PAYMENT_ADMIN_CHAT_ID
            if PAYMENT_ADMIN_CHAT_ID:
                admin_text = f"""🆕 Новый платеж:
                
User: {update.effective_user.username or update.effective_user.first_name} ({user_id})
План: {plan_name}
Срок: {duration} мес.
Сумма: {amount} ₽
Order ID: {order_id}
Автопродление: {"✅" if enable_auto_renewal else "❌"}"""
                
                try:
                    await context.bot.send_message(
                        chat_id=PAYMENT_ADMIN_CHAT_ID,
                        text=admin_text
                    )
                except Exception as e:
                    logger.error(f"Error sending admin notification: {e}")
            
            return ConversationHandler.END
            
        else:
            error = payment_result.get('error', 'Неизвестная ошибка')
            await query.edit_message_text(
                f"❌ Ошибка создания платежа:\n{error}\n\n"
                "Попробуйте позже или обратитесь в поддержку."
            )
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Error in payment confirmation: {e}")
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
async def ask_auto_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Спрашивает о включении автопродления."""
    query = update.callback_query
    await query.answer()
    
    # Получаем сохраненные данные из контекста
    plan_id = context.user_data.get('selected_plan')
    plan_name = context.user_data.get('plan_name', 'Подписка')
    duration = context.user_data.get('duration_months', 1)
    
    # ВАЖНО: Используем сохраненную цену из контекста
    total_price = context.user_data.get('total_price')
    
    if not total_price:
        # Если цена не сохранена, пересчитываем
        logger.warning(f"Total price not found in ask_auto_renewal for user {update.effective_user.id}")
        
        if plan_id == 'trial_7days':
            total_price = 1
        else:
            from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
            plan_info = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
            if plan_info:
                total_price = calculate_subscription_price(plan_id, duration, plan_info)
            else:
                total_price = 490 * duration  # Fallback
        
        # Сохраняем для следующих шагов
        context.user_data['total_price'] = total_price
    
    text = f"""💳 <b>Выберите тип оплаты</b>

📋 <b>Ваш заказ:</b>
• Тариф: {plan_name}
• Срок: {duration} мес.
• Стоимость: <b>{total_price} ₽</b>

<b>Доступные варианты:</b>

🔄 <b>С автопродлением</b>
После окончания срока подписка продлевается автоматически.
Вы можете отменить автопродление в любой момент.

💳 <b>Разовая оплата</b>
Подписка действует только выбранный срок.
После окончания нужно продлить вручную."""
    
    keyboard = [
        [InlineKeyboardButton("🔄 С автопродлением", callback_data="consent_auto_renewal")],
        [InlineKeyboardButton("💳 Разовая оплата", callback_data="no_auto_renewal")],
        [InlineKeyboardButton("❓ Подробнее", callback_data="auto_renewal_terms")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return AUTO_RENEWAL_CHOICE


@safe_handler()
async def handle_auto_renewal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор автопродления при оплате."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "enable_auto_renewal_payment":
        context.user_data['enable_auto_renewal'] = True
        await query.answer("✅ Автопродление будет включено после оплаты")
    else:
        context.user_data['enable_auto_renewal'] = False
        await query.answer("Автопродление не будет включено")
    
    # Переходим к подтверждению платежа
    return await handle_payment_confirmation_with_recurrent(update, context)

@safe_handler()
async def cmd_my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /my_subscriptions - показывает активные подписки."""
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    if SUBSCRIPTION_MODE == 'modular':
        modules = await subscription_manager.get_user_modules(user_id)
        
        if not modules:
            text = "📋 <b>Мои подписки</b>\n\nУ вас нет активных подписок.\n\nИспользуйте /subscribe для оформления."
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
    
    # ДОБАВЛЕНО: кнопка главного меню
    keyboard = [
        [InlineKeyboardButton("🔄 Оформить/Продлить", callback_data="subscribe")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ]
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@safe_handler()
async def handle_my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback my_subscriptions - показывает активные подписки."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    if SUBSCRIPTION_MODE == 'modular':
        modules = await subscription_manager.get_user_modules(user_id)
        
        if not modules:
            # Для пользователей без подписки показываем интерфейс подписки
            text = "📋 <b>Мои подписки</b>\n\nУ вас нет активных подписок.\n\n"
            text += "💡 С модульной системой вы платите только за те задания, которые вам нужны!"
            
            keyboard = [
                [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
            ]
            
            try:
                await query.edit_message_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error in handle_my_subscriptions: {e}")
                    raise
        else:
            # Для пользователей с подпиской показываем их модули
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
                text += f"✅ {name}\n   └ Действует до: {expires}\n\n"
            
            # Детали доступа
            text += "📊 <b>Детали доступа:</b>\n"
            all_modules = ['test_part', 'task19', 'task20', 'task24', 'task25']
            inactive_modules = []
            
            for module_code in all_modules:
                has_access = await subscription_manager.check_module_access(user_id, module_code)
                if not has_access:
                    inactive_modules.append(module_names.get(module_code, module_code))
            
            if inactive_modules:
                text += f"❌ Неактивные: {', '.join(inactive_modules)}\n\n"
            else:
                text += "✅ У вас есть доступ ко всем модулям!\n\n"
            
            text += "Используйте /subscribe для продления или добавления модулей."
            
            keyboard = [
                [InlineKeyboardButton("🔄 Продлить/Добавить", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
            ]
            
            try:
                await query.edit_message_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error editing message: {e}")
                    # Если не можем отредактировать, отправляем новое сообщение
                    await query.message.reply_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
    else:
        # Режим обычных подписок
        subscription = await subscription_manager.check_active_subscription(user_id)
        if subscription:
            plan = SUBSCRIPTION_PLANS.get(subscription['plan_id'], {})
            expires = subscription['expires_at'].strftime('%d.%m.%Y')
            text = f"""✅ <b>Активная подписка</b>

План: {plan.get('name', 'Подписка')}
Действует до: {expires}

Используйте /subscribe для продления."""
        else:
            text = "📋 <b>Мои подписки</b>\n\nУ вас нет активной подписки.\n\nИспользуйте /subscribe для оформления."
        
        keyboard = [
            [InlineKeyboardButton("🔄 Оформить/Продлить", callback_data="subscribe")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ]
        
        try:
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Error editing message: {e}")
                await query.message.reply_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
    
    # ВАЖНО: НЕ возвращаем состояние ConversationHandler
    # чтобы обработчик работал как standalone
    return None
    
@safe_handler()
async def handle_back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик для возврата в главное меню."""
    query = update.callback_query
    await query.answer()
    
    # Очищаем флаг процесса оплаты если он был
    context.user_data.pop('in_payment_process', None)
    
    # Используем глобальный обработчик из core
    from core.menu_handlers import handle_to_main_menu
    return await handle_to_main_menu(update, context)

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
            'name': '💎 Задание 24',
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

# Добавьте эту функцию ПЕРЕД функцией register_payment_handlers в файле payment/handlers.py

async def standalone_pay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Автономный обработчик для кнопок оплаты вне ConversationHandler."""
    query = update.callback_query
    await query.answer()
    
    # Устанавливаем флаг процесса оплаты
    context.user_data['in_payment_process'] = True
    
    # Переходим в ConversationHandler через точку входа
    if query.data in ["pay_trial", "pay_package_full", "pay_package_second"]:
        # Вызываем handle_plan_selection и входим в ConversationHandler
        context.user_data['entry_from_standalone'] = True
        return await handle_plan_selection(update, context)
    elif query.data == "pay_individual_modules":
        # Показываем выбор модулей
        context.user_data['entry_from_standalone'] = True
        return await show_individual_modules(update, context)
    else:
        # Неизвестная кнопка
        context.user_data.pop('in_payment_process', None)
        await query.answer("Неизвестное действие", show_alert=True)
    
    # Возвращаем состояние для входа в ConversationHandler
    return CHOOSING_PLAN


# Замените функцию register_payment_handlers на эту версию:
def register_payment_handlers(app):
    """Регистрирует обработчики платежей."""
    logger.info("Registering payment handlers...")
    
    # Инициализируем обработчик согласия
    subscription_manager = app.bot_data.get('subscription_manager', SubscriptionManager())
    consent_handler = AutoRenewalConsent(subscription_manager)
    
    # Создаем ConversationHandler для процесса оплаты
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
                CallbackQueryHandler(show_modular_interface, pattern="^back_to_main$"),
                CallbackQueryHandler(handle_my_subscriptions, pattern="^my_subscriptions$")
            ],
            
            CHOOSING_MODULES: [
                CallbackQueryHandler(toggle_module_selection, pattern="^toggle_"),
                CallbackQueryHandler(show_module_info, pattern="^info_"),
                CallbackQueryHandler(back_to_module_selection, pattern="^back_to_module_selection$"),
                CallbackQueryHandler(proceed_with_selected_modules, pattern="^proceed_with_modules$"),
                CallbackQueryHandler(handle_plan_selection, pattern="^pay_package_"),
                CallbackQueryHandler(show_modular_interface, pattern="^back_to_main$")
            ],
            
            CHOOSING_DURATION: [
                CallbackQueryHandler(handle_duration_selection, pattern="^duration_"),
                CallbackQueryHandler(show_individual_modules, pattern="^back_to_modules$"),
                CallbackQueryHandler(show_modular_interface, pattern="^back_to_plans$")
            ],
            
            ENTERING_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_input)
            ],
            
            # НОВОЕ: Состояние выбора типа оплаты
            SHOWING_TERMS: [
                CallbackQueryHandler(
                    consent_handler.handle_choice_selection,
                    pattern="^(choose_auto_renewal|choose_no_auto_renewal|show_auto_renewal_terms)$"
                ),
                CallbackQueryHandler(
                    consent_handler.handle_back_navigation,
                    pattern="^back_to_payment_choice$"
                )
            ],
            
            # НОВОЕ: Состояние согласия с чек-боксом
            CONSENT_CHECKBOX: [
                CallbackQueryHandler(
                    consent_handler.toggle_consent,
                    pattern="^toggle_consent_checkbox$"
                ),
                CallbackQueryHandler(
                    consent_handler.confirm_with_auto_renewal,
                    pattern="^confirm_with_auto_renewal$"
                ),
                CallbackQueryHandler(
                    lambda u, c: u.callback_query.answer("⚠️ Сначала отметьте согласие", show_alert=True) or CONSENT_CHECKBOX,
                    pattern="^need_consent_reminder$"
                ),
                CallbackQueryHandler(
                    consent_handler.show_detailed_terms,
                    pattern="^show_user_agreement$"
                ),
                CallbackQueryHandler(
                    consent_handler.handle_back_navigation,
                    pattern="^back_to_payment_choice$"
                )  # ✅ Добавлена закрывающая скобка
            ],  # ✅ Закрывающая квадратная скобка для списка
                        
            # НОВОЕ: Финальное подтверждение
            FINAL_CONFIRMATION: [
                CallbackQueryHandler(
                    handle_payment_confirmation_with_recurrent,
                    pattern="^proceed_to_payment$"
                ),
                CallbackQueryHandler(
                    consent_handler.handle_back_navigation,
                    pattern="^back_to_payment_choice$"
                ),
                CallbackQueryHandler(
                    cancel_payment,
                    pattern="^cancel_payment$"
                )
            ],
            
            # Существующее состояние CONFIRMING (для обратной совместимости)
            CONFIRMING: [
                CallbackQueryHandler(ask_auto_renewal, pattern="^confirm_payment$"),
                CallbackQueryHandler(
                    handle_auto_renewal_choice, 
                    pattern="^(enable|disable)_auto_renewal_payment$"
                ),
                CallbackQueryHandler(
                    handle_payment_confirmation_with_recurrent, 
                    pattern="^final_confirm_payment$"
                ),
                CallbackQueryHandler(cancel_payment, pattern="^cancel_payment$"),
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_payment),
            CallbackQueryHandler(cancel_payment, pattern="^pay_cancel$"),
            CallbackQueryHandler(handle_my_subscriptions, pattern="^my_subscriptions$")
        ],
        allow_reentry=True,
        per_message=False
    )
    
    app.add_handler(payment_conv, group=-50)
    app.add_handler(
        CallbackQueryHandler(
            check_payment_status,
            pattern="^check_payment$"
        ),
        group=-45
    )
    # 2. Регистрируем ConversationHandler с высоким приоритетом
    app.add_handler(payment_conv, group=-50)
    
    # 3. Обработчик для my_subscriptions вне ConversationHandler
    app.add_handler(
        CallbackQueryHandler(
            handle_my_subscriptions, 
            pattern="^my_subscriptions$"
        ), 
        group=-45
    )
    
    # 4. Обработчики для автономных кнопок оплаты
    app.add_handler(
        CallbackQueryHandler(
            standalone_pay_handler, 
            pattern="^pay_trial$"
        ), 
        group=-48
    )
    app.add_handler(
        CallbackQueryHandler(
            standalone_pay_handler, 
            pattern="^pay_package_full$"
        ), 
        group=-48
    )
    app.add_handler(
        CallbackQueryHandler(
            standalone_pay_handler, 
            pattern="^pay_package_second$"
        ), 
        group=-48
    )
    app.add_handler(
        CallbackQueryHandler(
            standalone_pay_handler, 
            pattern="^pay_individual_modules$"
        ), 
        group=-48
    )
    
    # 5. Обработчик для subscribe вне ConversationHandler
    async def subscribe_redirect(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Перенаправляет в интерфейс подписки."""
        context.user_data['in_payment_process'] = True
        return await show_modular_interface(update, context)
    
    app.add_handler(
        CallbackQueryHandler(
            subscribe_redirect,
            pattern="^subscribe$"
        ),
        group=-48
    )
    
    # 6. Команда /my_subscriptions
    app.add_handler(
        CommandHandler("my_subscriptions", cmd_my_subscriptions), 
        group=-45
    )
    
    # 7. Обработчик для возврата в главное меню
    async def payment_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Переход в главное меню из payment."""
        from core.menu_handlers import handle_to_main_menu
        context.user_data.pop('in_payment_process', None)
        await handle_to_main_menu(update, context)
        return ConversationHandler.END
    
    app.add_handler(
        CallbackQueryHandler(
            payment_to_main_menu,
            pattern="^(main_menu|to_main_menu)$"
        ),
        group=-45
    )
    
    # 8. Обработчик для back_to_main
    app.add_handler(
        CallbackQueryHandler(
            handle_back_to_main_menu, 
            pattern="^back_to_main$"
        ), 
        group=-49
    )
    
    # 9. Обработчик информации о модулях
    app.add_handler(
        CallbackQueryHandler(
            handle_module_info, 
            pattern="^module_info_"
        ), 
        group=-45
    )
    
    # 10. Debug команда (проверяем существование)
    try:
        app.add_handler(
            CommandHandler("debug_subscription", cmd_debug_subscription), 
            group=-50
        )
    except NameError:
        logger.info("cmd_debug_subscription not defined, skipping")
    
    logger.info("Payment handlers registered with priority")
    logger.info("Total handlers registered: 10+")
    logger.info("Priority groups: -50 (ConversationHandler), -48 (redirects), -45 (standalone)")
