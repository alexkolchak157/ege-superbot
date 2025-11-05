"""
Обработчики для статистики и аналитики.
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from ..states import TeacherStates


async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать общую статистику"""
    query = update.callback_query
    await query.answer()

    # TODO: Получить данные из БД
    # Заглушка
    text = (
        "📊 <b>Статистика</b>\n\n"
        "👥 <b>Всего учеников:</b> 5\n"
        "📝 <b>Активных заданий:</b> 3\n"
        "✅ <b>Выполнено заданий:</b> 12\n"
        "⏰ <b>Просрочено:</b> 1\n"
    )

    keyboard = [
        [InlineKeyboardButton("👥 Детальная статистика по ученикам", callback_data="teacher_students")],
        [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.VIEW_STATISTICS


async def show_student_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать список учеников"""
    query = update.callback_query
    await query.answer()

    # TODO: Получить список учеников из БД
    # Заглушка
    text = (
        "👥 <b>Мои ученики</b>\n\n"
        "У вас пока нет учеников.\n"
        "Отправьте им ваш код учителя для подключения."
    )

    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.STUDENT_LIST
