"""
Обработчики для создания и управления домашними заданиями.
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from ..states import TeacherStates


async def create_assignment_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало создания домашнего задания"""
    query = update.callback_query
    await query.answer()

    text = (
        "➕ <b>Создание домашнего задания</b>\n\n"
        "Выберите тип задания:"
    )

    keyboard = [
        [InlineKeyboardButton("📝 Из существующих тем", callback_data="assign_existing")],
        [InlineKeyboardButton("📋 Тестовая часть", callback_data="assign_test_part")],
        [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.SELECT_ASSIGNMENT_TYPE


async def select_module(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор модуля (task19, task20, task21, task22, task23, task24, task25)"""
    query = update.callback_query
    await query.answer()

    text = (
        "📝 <b>Выберите модуль</b>\n\n"
        "Из какого модуля создать задание?"
    )

    keyboard = [
        [InlineKeyboardButton("💡 Задание 19 (Примеры)", callback_data="module_task19")],
        [InlineKeyboardButton("🔤 Задание 20 (Слова)", callback_data="module_task20")],
        [InlineKeyboardButton("📊 Задание 21 (Графики)", callback_data="module_task21")],
        [InlineKeyboardButton("📝 Задание 22 (Анализ ситуаций)", callback_data="module_task22")],
        [InlineKeyboardButton("📜 Задание 23 (Конституция РФ)", callback_data="module_task23")],
        [InlineKeyboardButton("📄 Задание 24 (Пропуски)", callback_data="module_task24")],
        [InlineKeyboardButton("✍️ Задание 25 (Сочинение)", callback_data="module_task25")],
        [InlineKeyboardButton("◀️ Назад", callback_data="create_assignment")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.SELECT_MODULE
