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
    """Обработка выбора длительности подписки с правильной обработкой навигации."""
    query = update.callback_query
    await query.answer()
    
    context.user_data['in_payment_process'] = True
    
    # Обрабатываем кнопки "Назад"
    if query.data == "back_to_modules":
        # Возвращаемся к выбору модулей
        return await show_individual_modules(update, context)
    elif query.data == "back_to_plans":
        # Возвращаемся к выбору планов
        return await show_modular_interface(update, context)
    
    # Извлекаем количество месяцев
    try:
        months = int(query.data.replace("duration_", ""))
    except ValueError:
        logger.error(f"Invalid duration callback data: {query.data}")
        await query.answer("❌ Ошибка выбора срока", show_alert=True)
        return CHOOSING_DURATION
    
    # Сохраняем выбранный срок
    context.user_data['duration_months'] = months
    
    # Логируем для отладки
    plan_id = context.user_data.get('selected_plan', 'unknown')
    logger.info(f"User {update.effective_user.id} selected {months} months for plan {plan_id}")
    
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


@safe_handler()
async def handle_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода email с правильным расчетом цен и сроков."""
    # ВАЖНО: Подтверждаем флаг процесса оплаты
    context.user_data['in_payment_process'] = True
    
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

    # Получаем данные заказа
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

    # Сохраняем расчеты для использования в следующих шагах
    if is_trial:
        context.user_data['total_price'] = 1  # 1 рубль за триал
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
        
        # Сохраняем рассчитанную цену
        context.user_data['total_price'] = total_price
        context.user_data['discount_info'] = discount_info
        context.user_data['base_price'] = base_price
        context.user_data['saved_amount'] = (base_price * duration) - total_price if duration > 1 and multiplier < duration else 0

    # Сохраняем данные плана для последующего использования
    context.user_data['plan_name'] = plan['name']
    
    # ============= ИЗМЕНЕНИЕ: Переходим к выбору автопродления =============
    # Вместо показа подтверждения сразу, показываем экран выбора автопродления
    
    await update.message.reply_text(
        f"✅ Email сохранен: {email}\n\n"
        "Теперь выберите тип оплаты..."
    )
    
    # Показываем опции автопродления
    await show_auto_renewal_choice(update, context)
    return AUTO_RENEWAL_CHOICE  # Новое состояние

# payment/handlers.py - Добавить после функции handle_email_input

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
        from .config import MODULE_PLANS, SUBSCRIPTION_PLANS
        plan = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
        monthly_price = plan['price_rub']
        total_price = calculate_subscription_price(plan_id, duration)
    
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

• Списание будет происходить автоматически каждый месяц
• Я получу уведомление за 3 дня до списания
• Я могу отменить автопродление в любой момент
• При отмене возврат осуществляется согласно правилам сервиса
• Мои платежные данные будут сохранены в защищенном виде

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
    await show_final_consent_screen(update, context)
    return FINAL_CONSENT

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

@safe_handler()
async def handle_payment_confirmation_with_recurrent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка подтверждения платежа с опцией включения автопродления."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_payment":
        context.user_data.pop('in_payment_process', None)
        await query.edit_message_text("❌ Оформление подписки отменено.")
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    plan_id = context.user_data['selected_plan']
    duration = context.user_data.get('duration_months', 1)
    email = context.user_data['user_email']
    is_trial = context.user_data.get('is_trial', False)
    enable_auto_renewal = context.user_data.get('enable_auto_renewal', False)  
    
    # Получаем план
    if plan_id.startswith('custom_'):
        plan = context.user_data.get('custom_plan')
        if not plan:
            logger.error(f"Custom plan data not found for {plan_id}")
            await query.edit_message_text("❌ Ошибка: данные плана не найдены. Попробуйте заново.")
            context.user_data.pop('in_payment_process', None)
            return ConversationHandler.END
        modules_to_activate = plan.get('modules', [])
    else:
        # Ищем план сначала в MODULE_PLANS, потом в SUBSCRIPTION_PLANS
        plan = MODULE_PLANS.get(plan_id)
        if not plan:
            plan = SUBSCRIPTION_PLANS.get(plan_id)
        
        if not plan:
            logger.error(f"Plan not found: {plan_id}")
            await query.edit_message_text("❌ Ошибка: план не найден. Обратитесь к администратору.")
            context.user_data.pop('in_payment_process', None)
            return ConversationHandler.END
        
        modules_to_activate = plan.get('modules', [])
    
    # Вычисляем цену с учетом типа плана
    if is_trial:
        # Пробный период - 1 рубль
        amount_kopecks = 100
    else:
        # Рассчитываем цену с учетом скидок
        from payment.config import DURATION_DISCOUNTS
        base_price = plan['price_rub']
        
        if duration in DURATION_DISCOUNTS:
            multiplier = DURATION_DISCOUNTS[duration]['multiplier']
            total_price = int(base_price * multiplier)
        else:
            total_price = base_price * duration
        
        amount_kopecks = total_price * 100
    
    try:
        # Рассчитываем цену
        total_price = calculate_subscription_price(plan_id, duration, plan if plan_id.startswith('custom_') else None)
        
        # Создаем уникальный order_id
        order_id = f"ORD_{user_id}_{int(datetime.now().timestamp())}"
        
        # Подготавливаем метаданные
        payment_metadata = {
            'user_id': user_id,
            'plan_id': plan_id,
            'duration_months': duration,
            'modules': modules_to_activate if plan_id.startswith('custom_') else None,
            'is_trial': is_trial,
            'enable_auto_renewal': enable_auto_renewal  # НОВОЕ
        }
        
        # Сохраняем email
        await subscription_manager.save_user_email(user_id, email)
        
        # Создаем запись о платеже
        payment_info = await subscription_manager.create_payment(
            user_id=user_id,
            plan_id=plan_id,
            amount_kopecks=total_price,
            metadata=json.dumps(payment_metadata)
        )
        
        # НОВОЕ: Используем рекуррентный API если нужно автопродление
        if enable_auto_renewal:
            from .tbank_recurrent import TBankRecurrentPayments
            
            tbank_api = TBankRecurrentPayments()
            
            # Инициализируем первичный платеж с Recurrent=Y
            payment_result = await tbank_api.init_primary_payment(
                order_id=order_id,
                amount_kopecks=total_price,
                customer_key=str(user_id),  # Используем user_id как CustomerKey
                description=f"Подписка {plan['name']} на {duration} мес. с автопродлением",
                user_email=email
            )
        else:
            # Обычный платеж без рекуррентов
            payment_result = await tinkoff_payment.create_payment(
                order_id=order_id,
                amount_kopecks=total_price,
                description=f"Подписка {plan['name']} на {duration} мес.",
                user_email=email
            )
        
        if payment_result.get('success'):
            payment_url = payment_result.get('payment_url')
            
            # Сохраняем payment_id
            await subscription_manager.update_payment_id(order_id, payment_result.get('payment_id'))
            
            text = f"""💳 <b>Переход к оплате</b>

План: {plan['name']}
Срок: {duration} мес.
{'🔄 Автопродление: включено' if enable_auto_renewal else ''}
Сумма: {total_price // 100} ₽

Сейчас вы будете перенаправлены на страницу оплаты Т-Банка.

После успешной оплаты подписка будет активирована автоматически."""
            
            keyboard = [[
                InlineKeyboardButton("💳 Перейти к оплате", url=payment_url)
            ]]
            
            if enable_auto_renewal:
                text += "\n\n✅ После оплаты автопродление будет настроено автоматически."
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Очищаем флаг процесса оплаты
            context.user_data.pop('in_payment_process', None)
            return ConversationHandler.END
            
        else:
            error_msg = payment_result.get('error', 'Неизвестная ошибка')
            await query.edit_message_text(
                f"❌ Ошибка создания платежа: {error_msg}\n\n"
                "Попробуйте позже или обратитесь в поддержку."
            )
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Payment creation error: {e}")
        await query.edit_message_text("❌ Ошибка создания платежа. Попробуйте позже.")
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
    """Спрашивает пользователя о включении автопродления."""
    query = update.callback_query
    await query.answer()
    
    text = """🔄 <b>Настройка автопродления</b>

Хотите включить автоматическое продление подписки?

✅ <b>Преимущества автопродления:</b>
• Не нужно помнить о дате окончания
• Непрерывный доступ к материалам
• Можно отключить в любой момент
• Уведомления за 3 дня до списания

⚠️ Средства будут списываться автоматически каждый месяц с привязанной карты."""
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Включить автопродление", 
                               callback_data="enable_auto_renewal_payment"),
            InlineKeyboardButton("❌ Без автопродления", 
                               callback_data="disable_auto_renewal_payment")
        ]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return CONFIRMING


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
            AUTO_RENEWAL_CHOICE: [  # НОВОЕ состояние
                CallbackQueryHandler(
                    handle_auto_renewal_consent_choice, 
                    pattern="^(consent_auto_renewal|no_auto_renewal|auto_renewal_terms)$"
                ),
                CallbackQueryHandler(
                    show_auto_renewal_options,
                    pattern="^back_to_auto_renewal_choice$"
                )
            ],
            FINAL_CONSENT: [  # НОВОЕ состояние
                CallbackQueryHandler(toggle_consent, pattern="^toggle_consent$"),
                CallbackQueryHandler(confirm_with_auto_renewal, pattern="^confirm_with_auto_renewal$"),
                CallbackQueryHandler(
                    lambda u, c: show_auto_renewal_options(u, c) or AUTO_RENEWAL_CHOICE,
                    pattern="^back_to_auto_renewal_options$"
                ),
                CallbackQueryHandler(
                    lambda u, c: u.callback_query.answer("⚠️ Необходимо отметить согласие", show_alert=True) or FINAL_CONSENT,
                    pattern="^need_consent$"
                )
            ],
            CONFIRMING: [
                CallbackQueryHandler(
                    handle_payment_confirmation_with_recurrent,
                    pattern="^(confirm_payment|final_confirm_payment)$"
                ),
                CallbackQueryHandler(cancel_payment, pattern="^cancel_payment$")
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