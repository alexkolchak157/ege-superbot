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
        "Код выглядит примерно так: <code>TEACH-ABC123</code>\n\n"
        "💰 <b>Выгода подключения:</b>\n"
        "• Скидка 100₽ на подписку (149₽ вместо 249₽)\n"
        "• Домашние задания от вашего репетитора\n"
        "• Отслеживание прогресса учителем"
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
        "Подтвердите подключение к этому учителю.\n\n"
        "💰 После подключения вы получите:\n"
        "• Скидку 100₽ на подписку (экономия 1200₽/год)\n"
        "• Домашние задания от учителя\n"
        "• Персональный фидбек по прогрессу"
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
        # Если лимит превышен - показываем специальное сообщение
        if "Достигнут лимит учеников" in reason:
            text = (
                f"❌ <b>Не удалось подключиться к учителю {teacher_name}</b>\n\n"
                f"📊 {reason}\n\n"
                "💡 Попросите вашего учителя обновить тариф подписки, "
                "чтобы подключить больше учеников.\n\n"
                "Учитель сможет выбрать тариф в разделе <i>«Режим учителя» → «Мой профиль»</i>."
            )
        else:
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

    text = "👌 Подключение к учителю отменено."
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
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_cabinet")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
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

        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_cabinet")])
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
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
        'test_part': '📝 Тестовая часть (1-16)',
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
    """Начало выполнения задания - показывает список конкретных вопросов"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

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

    # Получаем список конкретных вопросов из assignment_data
    assignment_data = homework.assignment_data

    if assignment_data.get('is_custom'):
        # Для кастомных заданий используем вопросы напрямую
        custom_questions = assignment_data.get('custom_questions', [])
        if not custom_questions:
            await query.message.edit_text(
                "❌ В этом задании нет вопросов.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="student_homework_list")
                ]]),
                parse_mode='HTML'
            )
            return

        # Для кастомных заданий используем ID вопросов из списка
        question_ids = [q['id'] for q in custom_questions]
        task_module = 'custom'

        # Создаем topics_data для кастомных вопросов
        topics_data = {
            'topics_by_id': {
                q['id']: {'title': q['text'][:50] + ('...' if len(q['text']) > 50 else '')}
                for q in custom_questions
            }
        }
    elif assignment_data.get('is_mixed'):
        # Для смешанных заданий собираем все вопросы из всех модулей
        question_ids = []
        combined_topics = {}

        from ..services.topics_loader import load_topics_for_module

        for module_data in assignment_data.get('modules', []):
            module_question_ids = module_data.get('question_ids', [])
            question_ids.extend(module_question_ids)

            # Загружаем topics для каждого модуля
            module_code = module_data['task_module']
            topics_data_temp = load_topics_for_module(module_code)
            combined_topics.update(topics_data_temp['topics_by_id'])

        topics_data = {'topics_by_id': combined_topics}
        task_module = 'mixed'
    elif assignment_data.get('task_module') == 'full_exam' or assignment_data.get('full_exam_questions'):
        # Для полного варианта ЕГЭ собираем все вопросы из всех модулей
        full_exam_questions = assignment_data.get('full_exam_questions', [])
        question_ids = [q['question_id'] for q in full_exam_questions]
        combined_topics = {}

        from ..services.topics_loader import load_topics_for_module

        for q in full_exam_questions:
            module_code = q['module']
            q_id = q['question_id']

            # Для test_part используем exam_number
            if module_code == 'test_part':
                exam_num = q.get('exam_number', q_id)
                combined_topics[q_id] = {
                    'title': f"Задание {exam_num}",
                    'exam_number': exam_num
                }
            else:
                # Загружаем данные для остальных модулей
                if module_code not in ['task19', 'task20', 'task24', 'task25']:
                    continue

                topics_data_temp = load_topics_for_module(module_code)
                topic_data = topics_data_temp['topics_by_id'].get(q_id)
                if topic_data:
                    combined_topics[q_id] = topic_data
                else:
                    # Fallback если не нашли
                    combined_topics[q_id] = {'title': q.get('title', f'Вопрос {q_id}')}

        topics_data = {'topics_by_id': combined_topics}
        task_module = 'full_exam'
    else:
        # Для обычных заданий
        question_ids = assignment_data.get('question_ids', [])
        task_module = assignment_data.get('task_module', 'unknown')

        if not question_ids:
            await query.message.edit_text(
                "❌ В этом задании нет вопросов.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="student_homework_list")
                ]]),
                parse_mode='HTML'
            )
            return

        # Загружаем информацию о вопросах
        from ..services.topics_loader import load_topics_for_module
        topics_data = load_topics_for_module(task_module)

    # Получаем прогресс выполнения
    completed_questions = await assignment_service.get_completed_question_ids(homework_id, user_id)

    # Формируем текст
    task_names = {
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25',
        'mixed': '🔀 Смешанное задание',
        'custom': '📝 Кастомное задание',
        'full_exam': '🎯 Полный вариант ЕГЭ'
    }
    task_name = task_names.get(task_module, task_module)

    completed_count = len(completed_questions)
    total_count = len(question_ids)

    text = (
        f"📝 <b>{homework.title}</b>\n"
        f"🎯 <b>{task_name}</b>\n\n"
        f"📊 Прогресс: {completed_count}/{total_count}\n\n"
        "Выберите задание для выполнения:\n"
    )

    # Формируем клавиатуру с вопросами
    keyboard = []

    for idx, q_id in enumerate(question_ids, 1):
        topic = topics_data['topics_by_id'].get(q_id)
        if topic:
            title = topic.get('title', f'Вопрос {q_id}')
            # Обрезаем длинные названия
            if len(title) > 45:
                title = title[:42] + "..."

            # Проверяем, выполнен ли вопрос
            if q_id in completed_questions:
                emoji = "✅"
                button_text = f"{emoji} {idx}. {title}"
            else:
                emoji = "⬜"
                button_text = f"{emoji} {idx}. {title}"

            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"hw_question:{homework_id}:{q_id}"
                )
            ])

    keyboard.append([InlineKeyboardButton("◀️ К списку заданий", callback_data="student_homework_list")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')


async def show_homework_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает конкретный вопрос из домашнего задания"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Парсим callback_data: hw_question:homework_id:question_id
    _, homework_id_str, question_id_str = query.data.split(':')
    homework_id = int(homework_id_str)
    question_id = int(question_id_str)

    # Получаем задание
    homework = await assignment_service.get_homework_by_id(homework_id)
    if not homework:
        await query.message.edit_text(
            "❌ Задание не найдено.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="student_homework_list")
            ]]),
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Определяем модуль для вопроса (для смешанных и кастомных заданий)
    assignment_data = homework.assignment_data

    if assignment_data.get('is_custom'):
        # Для кастомных заданий используем модуль custom
        task_module = 'custom'
    elif assignment_data.get('is_mixed'):
        # Для смешанных заданий ищем модуль, содержащий этот вопрос
        task_module = None
        for module_data in assignment_data.get('modules', []):
            if question_id in module_data.get('question_ids', []):
                task_module = module_data['task_module']
                break
        if not task_module:
            await query.message.edit_text(
                "❌ Вопрос не найден в задании.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="student_homework_list")
                ]]),
                parse_mode='HTML'
            )
            return ConversationHandler.END
    elif assignment_data.get('task_module') == 'full_exam' or assignment_data.get('full_exam_questions'):
        # Для полного экзамена ищем модуль вопроса
        task_module = None
        full_exam_questions = assignment_data.get('full_exam_questions', [])
        for q in full_exam_questions:
            if q['question_id'] == question_id:
                task_module = q['module']
                break
        if not task_module:
            await query.message.edit_text(
                "❌ Вопрос не найден в задании.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="student_homework_list")
                ]]),
                parse_mode='HTML'
            )
            return ConversationHandler.END
    else:
        # Для обычных заданий берем модуль напрямую
        task_module = assignment_data.get('task_module')

    # Проверяем, выполнен ли уже этот вопрос
    progress = await assignment_service.get_question_progress(homework_id, user_id, question_id)

    if progress:
        # Показываем результат выполнения
        text = (
            f"✅ <b>Вопрос уже выполнен</b>\n\n"
            f"<b>Ваш ответ:</b>\n{progress['user_answer']}\n\n"
        )

        if progress['ai_feedback']:
            text += f"<b>Обратная связь:</b>\n{progress['ai_feedback']}\n\n"

        if progress['is_correct']:
            text += "✅ Ответ принят"
        else:
            text += "❌ Требуется доработка"

        keyboard = [
            [InlineKeyboardButton("◀️ К списку вопросов", callback_data=f"start_homework_{homework_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return ConversationHandler.END

    # Загружаем вопрос
    if task_module == 'custom':
        # Для кастомных заданий берем текст вопроса из assignment_data
        custom_questions = assignment_data.get('custom_questions', [])
        question_data = next((q for q in custom_questions if q['id'] == question_id), None)

        if not question_data:
            await query.message.edit_text(
                "❌ Вопрос не найден в задании.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ К списку вопросов", callback_data=f"start_homework_{homework_id}")
                ]]),
                parse_mode='HTML'
            )
            return ConversationHandler.END

        question_text = f"<b>Вопрос {question_id}:</b>\n\n{question_data['text']}"
    else:
        # Для стандартных заданий используем question_loader
        from ..services.question_loader import load_question_by_id, format_question_for_display

        question_data = load_question_by_id(task_module, question_id)

        if not question_data:
            await query.message.edit_text(
                "❌ Вопрос не найден в базе данных.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ К списку вопросов", callback_data=f"start_homework_{homework_id}")
                ]]),
                parse_mode='HTML'
            )
            return ConversationHandler.END

        # Форматируем вопрос для отображения
        question_text = format_question_for_display(task_module, question_data)

    text = (
        f"📝 <b>{homework.title}</b>\n\n"
        f"{question_text}\n\n"
        "💬 Отправьте свой ответ текстовым сообщением."
    )

    # Сохраняем контекст для обработки ответа
    context.user_data['current_homework_id'] = homework_id
    context.user_data['current_question_id'] = question_id
    context.user_data['current_task_module'] = task_module

    keyboard = [
        [InlineKeyboardButton("◀️ К списку вопросов", callback_data=f"start_homework_{homework_id}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    # Переводим в состояние ожидания ответа
    from ..states import StudentStates
    return StudentStates.DOING_HOMEWORK


async def process_homework_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает ответ ученика на вопрос"""
    user_id = update.effective_user.id
    answer = update.message.text

    # Получаем контекст
    homework_id = context.user_data.get('current_homework_id')
    question_id = context.user_data.get('current_question_id')
    task_module = context.user_data.get('current_task_module')

    if not all([homework_id, question_id, task_module]):
        await update.message.reply_text(
            "❌ Ошибка: потерян контекст выполнения задания.\n"
            "Пожалуйста, начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
            ]]),
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # ПРОВЕРКА ЛИМИТОВ: Проверяем доступность AI-проверок для ученика
    from core.freemium_manager import get_freemium_manager

    freemium_manager = get_freemium_manager(
        context.bot_data.get('subscription_manager')
    )

    # Проверяем лимит для соответствующего модуля
    can_use, remaining, limit_msg = await freemium_manager.check_ai_limit(user_id, task_module)

    if not can_use:
        # Лимит исчерпан - показываем сообщение
        await update.message.reply_text(
            f"{limit_msg}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎁 Попробовать за 1₽", callback_data="subscribe_start")],
                [InlineKeyboardButton("💎 Оформить подписку", callback_data="subscribe_start")],
                [InlineKeyboardButton("📋 Мои задания", callback_data="student_homework_list")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
            ]),
            parse_mode='HTML'
        )
        # Очищаем контекст
        context.user_data.pop('current_homework_id', None)
        context.user_data.pop('current_question_id', None)
        context.user_data.pop('current_task_module', None)
        return ConversationHandler.END

    # Отправляем сообщение о проверке
    checking_msg = await update.message.reply_text(
        "⏳ Проверяю ответ через AI...",
        parse_mode='HTML'
    )

    # Загружаем данные вопроса для AI проверки
    from ..services.question_loader import load_question_by_id
    from ..services.ai_homework_evaluator import evaluate_homework_answer

    question_data = load_question_by_id(task_module, question_id)

    if not question_data:
        await checking_msg.edit_text(
            "❌ Ошибка: не удалось загрузить данные вопроса для проверки.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Выполняем AI проверку
    is_correct, ai_feedback = await evaluate_homework_answer(
        task_module=task_module,
        question_data=question_data,
        user_answer=answer,
        user_id=user_id
    )

    # Регистрируем использование AI-проверки
    from core import db
    await db.increment_ai_check_usage(user_id)

    # Получаем информацию об остатке проверок
    limit_info = await freemium_manager.get_limit_info(user_id, task_module)
    remaining_checks = limit_info.get('checks_remaining', 0)

    # Сохраняем прогресс
    success = await assignment_service.save_question_progress(
        homework_id=homework_id,
        student_id=user_id,
        question_id=question_id,
        user_answer=answer,
        is_correct=is_correct,
        ai_feedback=ai_feedback
    )

    if not success:
        await checking_msg.edit_text(
            "❌ Ошибка при сохранении ответа. Попробуйте еще раз.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Показываем результат
    text = (
        f"✅ <b>Ответ сохранен!</b>\n\n"
        f"<b>Обратная связь:</b>\n{ai_feedback}\n\n"
        "Вы можете продолжить выполнение других заданий."
    )

    # Добавляем информацию о лимите если пользователь не Premium
    if not limit_info.get('is_premium') and remaining_checks <= 3:
        if remaining_checks > 0:
            text += f"\n\n📊 Осталось проверок сегодня: <b>{remaining_checks}</b>"
        else:
            text += f"\n\n⏳ Бесплатные проверки на сегодня исчерпаны. Лимит обновится завтра."

    # Очищаем контекст
    context.user_data.pop('current_homework_id', None)
    context.user_data.pop('current_question_id', None)
    context.user_data.pop('current_task_module', None)

    keyboard = [
        [InlineKeyboardButton("➡️ К списку вопросов", callback_data=f"start_homework_{homework_id}")],
        [InlineKeyboardButton("📋 Мои задания", callback_data="student_homework_list")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await checking_msg.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return ConversationHandler.END


async def cancel_homework_execution(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена выполнения домашнего задания и возврат в главное меню"""
    # Очищаем контекст если есть
    context.user_data.pop('current_homework_id', None)
    context.user_data.pop('current_question_id', None)
    context.user_data.pop('current_task_module', None)

    return ConversationHandler.END
