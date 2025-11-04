"""
Обработчики для учеников (подключение к учителю, выполнение ДЗ).
"""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from ..states import StudentStates


async def enter_teacher_code_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало процесса ввода кода учителя"""
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    text = (
        "🔑 <b>Подключение к учителю</b>\n\n"
        "Введите код учителя, который он вам дал.\n"
        "Код выглядит примерно так: <code>TEACH-ABC123</code>"
    )

    keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return StudentStates.ENTER_TEACHER_CODE


async def process_teacher_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка введенного кода учителя"""
    code = update.message.text.strip().upper()

    # TODO: Проверить код в БД
    # Заглушка
    teacher_name = "Иван Иванович"

    text = (
        f"✅ Найден учитель: <b>{teacher_name}</b>\n\n"
        "Подтвердите подключение к этому учителю."
    )

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_teacher_{code}")],
        [InlineKeyboardButton("❌ Отмена", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return StudentStates.CONFIRM_TEACHER


async def homework_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Список домашних заданий ученика"""
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    # TODO: Получить список ДЗ из БД
    # Заглушка
    text = (
        "📚 <b>Мои домашние задания</b>\n\n"
        "У вас пока нет активных заданий."
    )

    keyboard = [[InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return ConversationHandler.END
