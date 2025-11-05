"""
Обработчики для учеников (подключение к учителю, выполнение ДЗ).
"""

import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from ..states import StudentStates
from ..services import teacher_service, assignment_service

logger = logging.getLogger(__name__)


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
    user_id = update.effective_user.id

    # Проверяем формат кода
    if not code.startswith("TEACH-") or len(code) != 12:
        text = (
            "❌ Неверный формат кода.\n\n"
            "Код должен выглядеть так: <code>TEACH-ABC123</code>\n"
            "Попробуйте еще раз."
        )
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return StudentStates.ENTER_TEACHER_CODE

    # Ищем учителя по коду
    teacher = await teacher_service.get_teacher_by_code(code)

    if not teacher:
        text = (
            "❌ Учитель с таким кодом не найден.\n\n"
            "Проверьте правильность кода и попробуйте снова."
        )
        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return StudentStates.ENTER_TEACHER_CODE

    # Проверяем активность подписки учителя
    if not teacher.has_active_subscription:
        text = (
            "⚠️ Подписка этого учителя неактивна.\n\n"
            "Попросите учителя продлить подписку."
        )
        keyboard = [[InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return ConversationHandler.END

    # Проверяем, не подключен ли уже
    is_connected = await teacher_service.is_student_connected(teacher.user_id, user_id)
    if is_connected:
        text = (
            f"ℹ️ Вы уже подключены к учителю <b>{teacher.display_name}</b>."
        )
        keyboard = [[InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return ConversationHandler.END

    # Сохраняем код в контексте для подтверждения
    context.user_data['pending_teacher_code'] = code
    context.user_data['pending_teacher_name'] = teacher.display_name

    text = (
        f"✅ Найден учитель: <b>{teacher.display_name}</b>\n\n"
        "Подтвердите подключение к этому учителю."
    )

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_teacher_connection")],
        [InlineKeyboardButton("❌ Отмена", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return StudentStates.CONFIRM_TEACHER


async def confirm_teacher_connection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение подключения к учителю"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    teacher_code = context.user_data.get('pending_teacher_code')
    teacher_name = context.user_data.get('pending_teacher_name')

    if not teacher_code:
        await query.message.edit_text(
            "❌ Произошла ошибка. Попробуйте еще раз.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Получаем учителя по коду
    teacher = await teacher_service.get_teacher_by_code(teacher_code)
    if not teacher:
        await query.message.edit_text(
            "❌ Учитель не найден.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Проверяем лимит учеников
    can_add, reason = await teacher_service.can_add_student(teacher.user_id)
    if not can_add:
        text = f"❌ Не удалось подключиться к учителю.\n\n{reason}"
        keyboard = [[InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return ConversationHandler.END

    # Добавляем ученика к учителю
    try:
        await teacher_service.add_student_to_teacher(teacher.user_id, user_id)

        text = (
            f"✅ Вы успешно подключились к учителю <b>{teacher_name}</b>!\n\n"
            "Теперь вы будете получать домашние задания от этого учителя."
        )

        keyboard = [
            [InlineKeyboardButton("📚 Мои задания", callback_data="student_homework_list")],
            [InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

        # Очищаем временные данные
        context.user_data.pop('pending_teacher_code', None)
        context.user_data.pop('pending_teacher_name', None)

        logger.info(f"Student {user_id} connected to teacher {teacher.user_id}")

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error connecting student to teacher: {e}")
        text = "❌ Произошла ошибка при подключении. Попробуйте позже."
        keyboard = [[InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return ConversationHandler.END


async def cancel_connection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена подключения к учителю"""
    query = update.callback_query
    await query.answer()

    # Очищаем временные данные
    context.user_data.pop('pending_teacher_code', None)
    context.user_data.pop('pending_teacher_name', None)

    text = "❌ Подключение к учителю отменено."
    keyboard = [[InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return ConversationHandler.END


async def homework_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Список домашних заданий ученика"""
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    user_id = update.effective_user.id

    # Получаем список домашних заданий из БД
    homeworks = await assignment_service.get_student_homeworks(user_id)

    if not homeworks:
        text = (
            "📚 <b>Мои домашние задания</b>\n\n"
            "У вас пока нет активных заданий."
        )
        keyboard = [[InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
    else:
        text = (
            "📚 <b>Мои домашние задания</b>\n\n"
            f"Всего заданий: {len(homeworks)}\n"
            "Выберите задание для выполнения:"
        )

        keyboard = []
        for hw in homeworks:
            # Формируем статус для кнопки
            status_emoji = {
                'assigned': '📝',
                'in_progress': '⏳',
                'completed': '✅',
                'checked': '📊'
            }.get(hw.status, '📝')

            button_text = f"{status_emoji} {hw.title}"
            if hw.deadline:
                deadline_str = hw.deadline.strftime("%d.%m")
                button_text += f" (до {deadline_str})"

            keyboard.append([
                InlineKeyboardButton(button_text, callback_data=f"homework_{hw.id}")
            ])

        keyboard.append([InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return ConversationHandler.END
