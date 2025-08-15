# payment/handlers.py - адаптированная версия с поддержкой модулей
"""Обработчики команд для работы с платежами (модульная версия)."""
import logging
from datetime import datetime
from typing import Optional
import json
from telegram import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Update,
)
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
import aiosqlite
from core.error_handler import safe_handler
from .config import (
    SUBSCRIPTION_PLANS, 
    SUBSCRIPTION_MODE,
    DURATION_DISCOUNTS,
    MODULE_PLANS,
    PAYMENT_ADMIN_CHAT_ID,
    get_plan_price_kopecks
)
from .subscription_manager import SubscriptionManager
from .tinkoff import TinkoffPayment

logger = logging.getLogger(__name__)

# Состояния для платежного процесса
CHOOSING_PLAN = "choosing_plan"
CHOOSING_DURATION = "choosing_duration"  
ENTERING_EMAIL = "entering_email"
CONFIRMING = "confirming"
CHOOSING_MODULES = "choosing_modules"  # Новое состояние
PAYMENT_STATES = [CHOOSING_PLAN, CHOOSING_MODULES, CHOOSING_DURATION, ENTERING_EMAIL, CONFIRMING]

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
    """Показывает модульный интерфейс выбора подписки."""
    # Определяем источник вызова
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        edit_func = query.edit_message_text
    else:
        # Вызов из команды /subscribe
        edit_func = update.message.reply_text
    
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
        InlineKeyboardButton("❌ Отмена", callback_data="pay_cancel")
    ])
    
    await edit_func(
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
            context.user_data['duration_months'] = 1  # ИЗМЕНЕНО с 0 на 1
            context.user_data['is_trial'] = True
            context.user_data['trial_price'] = 100  # Цена в копейках (1 рубль)
            return await request_email(update, context)
        elif query.data.startswith("pay_package_"):
            # Обработка пакетов
            package_name = query.data.replace("pay_package_", "")
            if package_name == "second":
                package = "package_second_part"
            elif package_name == "full":
                package = "package_full"
            else:
                package = f"package_{package_name}"
            
            # Проверяем, что пакет существует
            if package not in MODULE_PLANS:
                logger.error(f"Package not found: {package}")
                await query.edit_message_text("❌ Пакет не найден.")
                context.user_data.pop('in_payment_process', None)
                return ConversationHandler.END
                
            context.user_data['selected_plan'] = package
            return await show_duration_options(update, context)
            
        elif query.data.startswith("pay_module_"):
            # Обработка отдельных модулей
            module = query.data.replace("pay_", "")
            
            # Проверяем, что модуль существует
            if module not in MODULE_PLANS:
                logger.error(f"Module not found: {module}")
                logger.error(f"Available modules: {list(MODULE_PLANS.keys())}")
                await query.edit_message_text("❌ Модуль не найден.")
                context.user_data.pop('in_payment_process', None)
                return ConversationHandler.END
                
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
        await query.edit_message_text(
            "❌ Модули временно недоступны. Обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")
            ]])
        )
        return CHOOSING_PLAN
    
    # Порядок отображения модулей
    module_order = [
        'module_test_part',
        'module_task19', 
        'module_task20',
        'module_task25',
        'module_task24'
    ]
    
    # Добавляем модули в клавиатуру
    modules_added = 0
    for module_id in module_order:
        if module_id not in individual_modules:
            logger.warning(f"Module {module_id} not found in individual_modules")
            continue
            
        module = individual_modules[module_id]
        is_selected = module_id in selected
        
        # Показываем статус выбора
        if is_selected:
            status = "✅"
            total_price += module['price_rub']
        else:
            status = "⬜"
        
        # Краткое описание для кнопки
        button_text = f"{status} {module['name']} - {module['price_rub']}₽"
        
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"toggle_{module_id}"
            ),
            InlineKeyboardButton(
                "ℹ️",
                callback_data=f"info_{module_id}"
            )
        ])
        modules_added += 1
    
    # Проверяем, что добавили хотя бы один модуль
    if modules_added == 0:
        logger.error("No modules were added to keyboard")
        await query.edit_message_text(
            "❌ Модули временно недоступны. Обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")
            ]])
        )
        return CHOOSING_PLAN
    
    # Показываем выбранные модули и общую стоимость
    if selected:
        text += "<b>Выбрано:</b>\n"
        for module_id in selected:
            if module_id in MODULE_PLANS:
                module = MODULE_PLANS[module_id]
                text += f"• {module['name']} - {module['price_rub']}₽\n"
            else:
                logger.warning(f"Selected module {module_id} not found in MODULE_PLANS")
        
        text += f"\n💰 <b>Итого: {total_price}₽/мес</b>\n"
        
        # Проверяем, не выгоднее ли взять пакет
        if len(selected) >= 3:
            if total_price > 499 and len(selected) == 3:
                text += "\n💡 <i>Совет: Пакет «Вторая часть» за 499₽ включает задания 19, 20, 25!</i>"
            elif total_price > 999:
                text += "\n💡 <i>Совет: «Полный доступ» за 999₽ включает все модули!</i>"
    else:
        text += "<i>Выберите хотя бы один модуль</i>\n"
    
    # Кнопки навигации
    nav_buttons = []
    
    if selected:
        nav_buttons.append(
            InlineKeyboardButton(
                f"✅ Далее (выбрано: {len(selected)})",
                callback_data="proceed_with_modules"
            )
        )
    
    keyboard.append(nav_buttons)
    keyboard.append([
        InlineKeyboardButton("🎯 Пакет «Вторая часть» - 499₽", callback_data="pay_package_second")
    ])
    keyboard.append([
        InlineKeyboardButton("👑 Полный доступ - 999₽", callback_data="pay_package_full")
    ])
    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    
    return CHOOSING_MODULES

@safe_handler()
async def toggle_module_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает выбор модуля."""
    query = update.callback_query
    
    module_id = query.data.replace("toggle_", "")
    
    if 'selected_modules' not in context.user_data:
        context.user_data['selected_modules'] = []
    
    selected = context.user_data['selected_modules']
    
    if module_id in selected:
        selected.remove(module_id)
        await query.answer(f"❌ Модуль удален из корзины")
    else:
        selected.append(module_id)
        module = MODULE_PLANS[module_id]
        await query.answer(f"✅ {module['name']} добавлен в корзину")
    
    # Обновляем интерфейс
    return await show_individual_modules(update, context)

@safe_handler()
async def show_module_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную информацию о модуле."""
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
            info_lines.append(f"{item}")
    
    info_lines.append(f"\n💰 <b>Стоимость:</b> {module['price_rub']}₽/месяц")
    
    # Собираем текст
    full_text = "\n".join(info_lines)
    
    # Создаем клавиатуру с кнопкой возврата
    keyboard = [[
        InlineKeyboardButton("⬅️ Назад к выбору", callback_data="back_to_module_selection")
    ]]
    
    # Отправляем как новое сообщение или редактируем существующее
    try:
        await query.edit_message_text(
            full_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        # Если не удалось отредактировать, отправляем alert
        alert_text = full_text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
        await query.answer(alert_text[:200], show_alert=True)
    
    return CHOOSING_MODULES

@safe_handler()
async def back_to_module_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору модулей из информации о модуле."""
    # Вызываем show_individual_modules для возврата к списку
    return await show_individual_modules(update, context)
    
# Добавьте обработчик для продолжения с выбранными модулями:

@safe_handler()
async def proceed_with_selected_modules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продолжает оформление с выбранными модулями."""
    query = update.callback_query
    
    selected = context.user_data.get('selected_modules', [])
    
    if not selected:
        await query.answer("Выберите хотя бы один модуль", show_alert=True)
        return CHOOSING_MODULES
    
    # Создаем комбинированный план из выбранных модулей
    total_price = sum(MODULE_PLANS[m]['price_rub'] for m in selected)
    module_names = [MODULE_PLANS[m]['name'] for m in selected]
    
    # Сохраняем как custom план
    custom_plan_id = f"custom_{'_'.join([m.replace('module_', '') for m in selected])}"
    
    context.user_data['selected_plan'] = custom_plan_id
    context.user_data['custom_plan'] = {
        'name': f"Комплект: {', '.join(module_names)}",
        'price_rub': total_price,
        'modules': [m.replace('module_', '') for m in selected],
        'type': 'custom',
        'duration_days': 30
    }
    
    # Переходим к выбору длительности
    return await show_duration_options(update, context)

@safe_handler()
async def show_duration_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает варианты длительности подписки."""
    query = update.callback_query
    await query.answer()
    
    context.user_data['in_payment_process'] = True
    
    plan_id = context.user_data['selected_plan']
    
    # ИСПРАВЛЕНИЕ: Сначала проверяем custom план
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
    
    context.user_data['in_payment_process'] = True
    
    if query.data == "back_to_modules":
        # Возвращаемся к выбору модулей
        return await show_individual_modules(update, context)
    elif query.data == "back_to_plans":
        # Возвращаемся к выбору планов
        return await show_modular_interface(update, context)
    
    months = int(query.data.replace("duration_", ""))
    context.user_data['duration_months'] = months
    
    # Запрашиваем email
    return await request_email(update, context)


@safe_handler()
async def request_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает email пользователя."""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    
    # ИСПРАВЛЕНИЕ: Правильная обработка custom планов
    if plan_id.startswith('custom_'):
        plan = context.user_data.get('custom_plan')
        if not plan:
            logger.error(f"Custom plan data not found in request_email for {plan_id}")
            await query.edit_message_text("❌ Ошибка: данные плана не найдены")
            return ConversationHandler.END
    else:
        plan = MODULE_PLANS.get(plan_id)
        if not plan:
            plan = SUBSCRIPTION_PLANS.get(plan_id)
        
        if not plan:
            logger.error(f"Plan not found in request_email: {plan_id}")
            await query.edit_message_text("❌ Ошибка: план не найден")
            return ConversationHandler.END
    
    # Специальное отображение для пробного периода
    if context.user_data.get('is_trial'):
        text = f"""📝 <b>Оформление пробного периода</b>

План: {plan['name']}
Срок: 7 дней
Стоимость: 1 ₽

Для оформления подписки введите ваш email:"""
    else:
        # Обычное отображение для других планов
        text = f"""📝 <b>Оформление подписки</b>

План: {plan['name']}"""
        
        if SUBSCRIPTION_MODE == 'modular' and duration > 1:
            discount_info = DURATION_DISCOUNTS.get(duration, {})
            text += f"\nСрок: {discount_info.get('label', f'{duration} мес.')}"
        else:
            text += f"\nСрок: {duration} мес."
        
        text += f"\n\nДля оформления подписки введите ваш email:"
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    return ENTERING_EMAIL

# Исправленные функции для payment/handlers.py

# 1. Исправление функции request_email
@safe_handler()
async def request_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает email пользователя."""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    
    # ИСПРАВЛЕНИЕ: Правильная обработка custom планов
    if plan_id.startswith('custom_'):
        plan = context.user_data.get('custom_plan')
        if not plan:
            logger.error(f"Custom plan data not found in request_email for {plan_id}")
            await query.edit_message_text("❌ Ошибка: данные плана не найдены")
            return ConversationHandler.END
    else:
        plan = MODULE_PLANS.get(plan_id)
        if not plan:
            plan = SUBSCRIPTION_PLANS.get(plan_id)
        
        if not plan:
            logger.error(f"Plan not found in request_email: {plan_id}")
            await query.edit_message_text("❌ Ошибка: план не найден")
            return ConversationHandler.END
    
    # Специальное отображение для пробного периода
    if context.user_data.get('is_trial'):
        text = f"""📝 <b>Оформление пробного периода</b>

План: {plan['name']}
Срок: 7 дней
Стоимость: 1 ₽

Для оформления подписки введите ваш email:"""
    else:
        # Обычное отображение для других планов
        text = f"""📝 <b>Оформление подписки</b>

План: {plan['name']}"""
        
        if SUBSCRIPTION_MODE == 'modular' and duration > 1:
            discount_info = DURATION_DISCOUNTS.get(duration, {})
            text += f"\nСрок: {discount_info.get('label', f'{duration} мес.')}"
        else:
            text += f"\nСрок: {duration} мес."
        
        text += f"\n\nДля оформления подписки введите ваш email:"
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    return ENTERING_EMAIL


# 2. Исправление функции handle_email_input
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
    
    # После сохранения email
    context.user_data['user_email'] = email

    # Показываем подтверждение заказа
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    is_trial = context.user_data.get('is_trial', False)

    # ИСПРАВЛЕНИЕ: Правильная обработка custom планов
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

    # Специальное отображение для пробного периода
    if is_trial:
        text = f"""📋 <b>Подтверждение заказа</b>

✅ План: {plan['name']}
📧 Email: {email}
📅 Срок: 7 дней
💰 К оплате: 1 ₽

Все верно?"""
    else:
        # Обычное отображение с учетом скидок
        if SUBSCRIPTION_MODE == 'modular' and duration > 1:
            from .config import DURATION_DISCOUNTS
            discount_info = DURATION_DISCOUNTS.get(duration, {})
            
            # Для custom планов считаем цену на основе базовой стоимости
            base_price = plan['price_rub']
            multiplier = discount_info.get('multiplier', duration)
            total_price = int(base_price * multiplier)
            
            text = f"""📋 <b>Подтверждение заказа</b>

✅ План: {plan['name']}
📧 Email: {email}
📅 Срок: {discount_info.get('label', f'{duration} мес.')}
💰 К оплате: {total_price} ₽

Все верно?"""
        else:
            total_price = plan['price_rub'] * duration
            text = f"""📋 <b>Подтверждение заказа</b>

✅ План: {plan['name']}
📧 Email: {email}
📅 Срок: {duration} мес.
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
    """Обработка подтверждения платежа с поддержкой custom планов."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "pay_cancel":
        context.user_data.pop('in_payment_process', None)
        await query.edit_message_text("❌ Оформление подписки отменено.")
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    plan_id = context.user_data['selected_plan']
    duration = context.user_data.get('duration_months', 1)
    email = context.user_data['user_email']
    
    # ИСПРАВЛЕНИЕ: Правильная обработка всех типов планов
    if plan_id.startswith('custom_'):
        plan = context.user_data.get('custom_plan')
        if not plan:
            logger.error(f"Custom plan data not found for {plan_id}")
            await query.edit_message_text("❌ Ошибка: данные плана не найдены. Попробуйте заново.")
            context.user_data.pop('in_payment_process', None)
            return ConversationHandler.END
        # Для custom плана нужно будет создать несколько подписок
        modules_to_activate = plan.get('modules', [])
    else:
        # Ищем план сначала в MODULE_PLANS, потом в SUBSCRIPTION_PLANS
        plan = MODULE_PLANS.get(plan_id)
        if not plan:
            plan = SUBSCRIPTION_PLANS.get(plan_id)
        
        if not plan:
            logger.error(f"Plan not found: {plan_id}")
            logger.error(f"Available MODULE_PLANS: {list(MODULE_PLANS.keys())}")
            logger.error(f"Available SUBSCRIPTION_PLANS: {list(SUBSCRIPTION_PLANS.keys())}")
            await query.edit_message_text("❌ Ошибка: план не найден. Обратитесь к администратору.")
            context.user_data.pop('in_payment_process', None)
            return ConversationHandler.END
        
        modules_to_activate = plan.get('modules', [])
    
    # Вычисляем цену с учетом типа плана
    if context.user_data.get('is_trial'):
        # Пробный период - 1 рубль
        amount_kopecks = 100
    elif plan_id.startswith('custom_'):
        # Custom план - используем базовую цену с учетом скидок
        from .config import DURATION_DISCOUNTS
        base_price = plan['price_rub']
        if duration in DURATION_DISCOUNTS:
            multiplier = DURATION_DISCOUNTS[duration]['multiplier']
            total_price = int(base_price * multiplier)
        else:
            total_price = base_price * duration
        amount_kopecks = total_price * 100
    else:
        # Обычный план
        from .config import get_plan_price_kopecks
        amount_kopecks = get_plan_price_kopecks(plan_id, duration)
    
    # Создаем платеж
    try:
        tinkoff_payment = TinkoffPayment()
        # ИСПРАВЛЕНИЕ: Создаем order_id с префиксом sub_ сразу
        order_id = f"sub_{user_id}_{plan_id}_{int(datetime.now().timestamp())}"
        
        # ИСПРАВЛЕНИЕ: Правильный вызов create_payment с amount_kopecks
        # create_payment возвращает кортеж (payment_url, order_id)
        try:
            if context.user_data.get('is_trial'):
                payment_url, returned_order_id = await tinkoff_payment.create_payment(
                    amount_kopecks=amount_kopecks,  # ИСПРАВЛЕНО: amount -> amount_kopecks
                    order_id=order_id,  # Передаем полный order_id с префиксом sub_
                    description=f"Пробный период 7 дней",
                    customer_email=email,
                    user_id=user_id,
                    bot_username=context.bot.username  # Передаем username бота
                )
            else:
                payment_url, returned_order_id = await tinkoff_payment.create_payment(
                    amount_kopecks=amount_kopecks,  # ИСПРАВЛЕНО: amount -> amount_kopecks
                    order_id=order_id,  # Передаем полный order_id с префиксом sub_
                    description=f"Подписка: {plan['name']} на {duration} мес.",
                    customer_email=email,
                    user_id=user_id,
                    bot_username=context.bot.username  # Передаем username бота
                )
            
            # Используем возвращенный order_id (должен быть тот же)
            if returned_order_id != order_id:
                logger.warning(f"Order ID mismatch: sent {order_id}, received {returned_order_id}")
                order_id = returned_order_id  # Используем то, что вернул API
            
            payment_id = order_id  # Используем order_id как payment_id для сохранения
            
            # Сохраняем информацию о платеже
            subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
            
            # ИСПРАВЛЕНИЕ: Используем правильное имя метода save_payment_info вместо save_payment
            await subscription_manager.save_payment_info(
                user_id=user_id,
                order_id=order_id,
                plan_id=plan_id,
                amount=amount_kopecks // 100,  # Конвертируем обратно в рубли
                email=email,
                modules=modules_to_activate if plan_id.startswith('custom_') else None
            )
            
            # Для custom планов модули будут активированы через webhook после подтверждения оплаты
            # metadata уже сохранена в save_payment_info
            
            # Отправляем ссылку на оплату
            text = f"""✅ <b>Платеж создан!</b>

Нажмите кнопку ниже для перехода к оплате.

После успешной оплаты подписка будет активирована автоматически."""
            
            keyboard = [
                [InlineKeyboardButton("💳 Оплатить", url=payment_url)],
                [InlineKeyboardButton("✅ Я оплатил", callback_data="check_payment")],
                [InlineKeyboardButton("❌ Отмена", callback_data="pay_cancel")]
            ]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Уведомляем админа
            if PAYMENT_ADMIN_CHAT_ID:
                admin_text = f"""🆕 Новый платеж:
                
Пользователь: {update.effective_user.mention_html()}
План: {plan['name']}
Сумма: {amount_kopecks // 100}₽
Email: {email}"""
                
                try:
                    await context.bot.send_message(
                        PAYMENT_ADMIN_CHAT_ID,
                        admin_text,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin: {e}")
                    
        except Exception as payment_error:
            # Обработка ошибки создания платежа
            logger.error(f"Payment creation failed: {payment_error}")
            error_msg = str(payment_error)
            
            await query.edit_message_text(
                f"❌ Ошибка создания платежа:\n{error_msg}\n\nПопробуйте позже или обратитесь к администратору.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Попробовать снова", callback_data="subscribe")
                ]])
            )
    
    except Exception as e:
        logger.error(f"Payment creation error: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка при создании платежа.\n\nПопробуйте позже."
        )
    
    context.user_data.pop('in_payment_process', None)
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

def register_payment_handlers(app: Application):
    """Регистрирует обработчики платежей."""
    
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
            CHOOSING_MODULES: [  # НОВОЕ СОСТОЯНИЕ
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
    
    app.add_handler(payment_conv, group=-50)
    
    # Дополнительные команды тоже с приоритетом
    app.add_handler(CommandHandler("my_subscriptions", cmd_my_subscriptions), group=-50)
    app.add_handler(CallbackQueryHandler(handle_my_subscriptions, pattern="^my_subscriptions$"), group=-50)
    
    # Обработчик информации о модулях
    app.add_handler(CommandHandler("debug_subscription", cmd_debug_subscription), group=-50)
    
    logger.info("Payment handlers registered with priority")