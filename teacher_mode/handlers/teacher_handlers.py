"""
Обработчики для учителей.
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from ..states import TeacherStates


async def teacher_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Главное меню учителя"""
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

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
    # TODO: Реализовать получение данных из БД
    query = update.callback_query
    await query.answer()

    # Заглушка
    teacher_code = "TEACH-ABC123"
    student_count = 5
    max_students = 10

    text = (
        "👤 <b>Ваш профиль учителя</b>\n\n"
        f"🔑 <b>Ваш код для учеников:</b> <code>{teacher_code}</code>\n"
        f"👥 <b>Учеников:</b> {student_count}/{max_students}\n\n"
        "Отправьте этот код своим ученикам для подключения."
    )

    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU
