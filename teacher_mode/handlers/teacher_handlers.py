"""
Обработчики для учителей.
"""

import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from ..states import TeacherStates
from ..services import teacher_service
from payment.config import get_all_teacher_plans, is_teacher_plan

logger = logging.getLogger(__name__)


async def is_teacher(user_id: int) -> bool:
    """Проверяет, является ли пользователь учителем"""
    profile = await teacher_service.get_teacher_profile(user_id)
    return profile is not None


async def has_active_teacher_subscription(user_id: int) -> bool:
    """Проверяет, есть ли у учителя активная подписка"""
    profile = await teacher_service.get_teacher_profile(user_id)
    if not profile:
        return False
    return profile.has_active_subscription


async def teacher_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Главное меню учителя"""
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    user_id = update.effective_user.id

    # Проверяем, является ли пользователь учителем
    if not await is_teacher(user_id):
        text = (
            "👨‍🏫 <b>Режим учителя</b>\n\n"
            "У вас еще нет профиля учителя.\n\n"
            "Чтобы стать учителем, оформите подписку для учителей."
        )

        keyboard = [
            [InlineKeyboardButton("💳 Подписки для учителей", callback_data="teacher_subscriptions")],
            [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return ConversationHandler.END

    # Проверяем активность подписки
    if not await has_active_teacher_subscription(user_id):
        text = (
            "👨‍🏫 <b>Режим учителя</b>\n\n"
            "⚠️ Ваша подписка учителя неактивна.\n\n"
            "Продлите подписку, чтобы продолжить работу с учениками."
        )

        keyboard = [
            [InlineKeyboardButton("💳 Продлить подписку", callback_data="teacher_subscriptions")],
            [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return ConversationHandler.END

    # Все проверки пройдены - показываем меню
    keyboard = [
        [InlineKeyboardButton("👥 Мои ученики", callback_data="teacher_students")],
        [InlineKeyboardButton("➕ Создать задание", callback_data="teacher_create_assignment")],
        [InlineKeyboardButton("📊 Статистика", callback_data="teacher_statistics")],
        [InlineKeyboardButton("🎁 Подарить подписку", callback_data="teacher_gift_subscription")],
        [InlineKeyboardButton("🔑 Промокоды", callback_data="teacher_promo_codes")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="teacher_profile")],
        [InlineKeyboardButton("◀️ Назад в главное меню", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "👨‍🏫 <b>Режим учителя</b>\n\nВыберите действие:"

    if query:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


async def teacher_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Профиль учителя с кодом для учеников"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем профиль учителя
    profile = await teacher_service.get_teacher_profile(user_id)
    if not profile:
        await query.message.edit_text(
            "❌ Профиль учителя не найден.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Получаем список учеников
    student_ids = await teacher_service.get_teacher_students(user_id)
    student_count = len(student_ids)
    max_students = profile.max_students
    max_students_text = "∞" if max_students == -1 else str(max_students)

    # Формируем текст с информацией о подписке
    tier_names = {
        'teacher_basic': '👨‍🏫 Basic',
        'teacher_standard': '👨‍🏫 Standard',
        'teacher_premium': '👨‍🏫 Premium'
    }
    tier_name = tier_names.get(profile.subscription_tier, profile.subscription_tier)

    subscription_status = "✅ Активна" if profile.has_active_subscription else "❌ Неактивна"
    if profile.subscription_expires and profile.has_active_subscription:
        expires_date = profile.subscription_expires.strftime("%d.%m.%Y")
        subscription_status += f" до {expires_date}"

    text = (
        "👤 <b>Ваш профиль учителя</b>\n\n"
        f"🔑 <b>Ваш код для учеников:</b> <code>{profile.teacher_code}</code>\n"
        f"📋 <b>Тариф:</b> {tier_name}\n"
        f"💳 <b>Подписка:</b> {subscription_status}\n"
        f"👥 <b>Учеников:</b> {student_count}/{max_students_text}\n\n"
        "📤 Отправьте код <code>{}</code> своим ученикам, "
        "чтобы они могли подключиться к вам.".format(profile.teacher_code)
    )

    keyboard = [
        [InlineKeyboardButton("📋 Список учеников", callback_data="teacher_students")],
        [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


async def show_teacher_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать доступные подписки для учителей"""
    query = update.callback_query
    await query.answer()

    teacher_plans = get_all_teacher_plans()

    text = (
        "💳 <b>Подписки для учителей</b>\n\n"
        "Выберите подходящий тариф:\n"
    )

    keyboard = []
    for plan in teacher_plans:
        plan_id = plan['plan_id']
        name = plan['name']
        price = plan['price_rub']
        max_students = plan.get('max_students', 0)

        if max_students == -1:
            students_text = "∞ учеников"
        else:
            students_text = f"до {max_students} учеников"

        button_text = f"{name} — {price}₽/мес ({students_text})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"buy_teacher_{plan_id}")])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


async def show_teacher_plan_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать детали конкретного плана учителя"""
    query = update.callback_query
    await query.answer()

    # Извлекаем plan_id из callback_data
    plan_id = query.data.replace("buy_teacher_", "")

    from payment.config import get_plan_info

    plan = get_plan_info(plan_id)
    if not plan:
        await query.message.edit_text("❌ План не найден")
        return ConversationHandler.END

    # Формируем описание плана
    text = f"💳 <b>{plan['name']}</b>\n\n"
    text += f"💰 <b>Цена:</b> {plan['price_rub']}₽/месяц\n\n"

    if 'detailed_description' in plan:
        text += "<b>Что входит:</b>\n"
        for feature in plan['detailed_description']:
            text += f"{feature}\n"
    else:
        text += "<b>Возможности:</b>\n"
        for feature in plan.get('features', []):
            text += f"{feature}\n"

    keyboard = [
        [InlineKeyboardButton("💳 Оформить подписку", callback_data=f"confirm_buy_{plan_id}")],
        [InlineKeyboardButton("◀️ Назад к тарифам", callback_data="teacher_subscriptions")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU
