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


async def view_homework(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Просмотр деталей конкретного задания"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Извлекаем ID задания из callback_data
    homework_id = int(query.data.replace("homework_", ""))

    # Получаем задание из БД
    homework = await assignment_service.get_homework_by_id(homework_id)

    if not homework:
        await query.message.edit_text(
            "❌ Задание не найдено.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="student_homework_list")
            ]]),
            parse_mode='HTML'
        )
        return

    # Формируем текст с деталями задания
    task_type_names = {
        'task19': '💡 Задание 19 (Примеры с обществознанием)',
        'task20': '⚙️ Задание 20 (Логические задачи)',
        'task24': '📊 Задание 24 (Развернутый план)',
        'task25': '💻 Задание 25 (Эссе)'
    }

    task_module = homework.assignment_data.get('task_module', 'unknown')
    task_type_name = task_type_names.get(task_module, task_module)
    questions_count = homework.assignment_data.get('questions_count', 0)
    selection_mode = homework.assignment_data.get('selection_mode', 'all')

    mode_names = {
        'all': '🎲 Случайный выбор',
        'topics': '📚 По темам',
        'numbers': '🔢 Конкретные номера'
    }
    mode_name = mode_names.get(selection_mode, selection_mode)

    text = (
        f"📝 <b>{homework.title}</b>\n\n"
        f"📌 <b>Тип:</b> {task_type_name}\n"
        f"📊 <b>Количество заданий:</b> {questions_count}\n"
        f"🎯 <b>Режим отбора:</b> {mode_name}\n"
    )

    if homework.description:
        text += f"\n📄 <b>Описание:</b>\n{homework.description}\n"

    if homework.deadline:
        deadline_str = homework.deadline.strftime("%d.%m.%Y %H:%M")
        text += f"\n⏰ <b>Срок:</b> {deadline_str}\n"

    text += "\n🚀 Нажмите \"Начать выполнение\" для старта работы над заданием."

    keyboard = [
        [InlineKeyboardButton("🚀 Начать выполнение", callback_data=f"start_homework_{homework_id}")],
        [InlineKeyboardButton("◀️ К списку заданий", callback_data="student_homework_list")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')


async def start_homework(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начало выполнения задания"""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID задания из callback_data
    homework_id = int(query.data.replace("start_homework_", ""))

    # Получаем задание из БД
    homework = await assignment_service.get_homework_by_id(homework_id)

    if not homework:
        await query.message.edit_text(
            "❌ Задание не найдено.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="student_homework_list")
            ]]),
            parse_mode='HTML'
        )
        return

    task_module = homework.assignment_data.get('task_module', 'unknown')

    # Формируем инструкцию для пользователя
    module_instructions = {
        'task19': ('💡 Задание 19', 'choose_task19'),
        'task20': ('⚙️ Задание 20', 'choose_task20'),
        'task24': ('📊 Задание 24', 'choose_task24'),
        'task25': ('💻 Задание 25', 'choose_task25')
    }

    if task_module not in module_instructions:
        await query.message.edit_text(
            "❌ Неизвестный тип задания.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="student_homework_list")
            ]]),
            parse_mode='HTML'
        )
        return

    task_name, module_callback = module_instructions[task_module]

    text = (
        f"🚀 <b>Запуск задания: {homework.title}</b>\n\n"
        f"Для выполнения этого задания перейдите в модуль <b>{task_name}</b>.\n\n"
        "Нажмите кнопку ниже для перехода в модуль:"
    )

    keyboard = [
        [InlineKeyboardButton(f"➡️ {task_name}", callback_data=module_callback)],
        [InlineKeyboardButton("◀️ К списку заданий", callback_data="student_homework_list")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
