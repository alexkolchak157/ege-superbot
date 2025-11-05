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
        [InlineKeyboardButton("📋 Мои задания", callback_data="teacher_my_assignments")],
        [InlineKeyboardButton("➕ Создать задание", callback_data="teacher_create_assignment")],
        [InlineKeyboardButton("📊 Статистика", callback_data="teacher_statistics")],
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


async def create_assignment_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало создания домашнего задания"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Проверяем, что пользователь учитель
    if not await has_active_teacher_subscription(user_id):
        await query.message.edit_text(
            "❌ Для создания заданий требуется активная подписка учителя.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Проверяем, что у учителя есть ученики
    students = await teacher_service.get_teacher_students(user_id)
    if not students:
        text = (
            "📝 <b>Создание задания</b>\n\n"
            "❌ У вас пока нет учеников.\n\n"
            "Сначала поделитесь своим кодом с учениками, чтобы они могли подключиться."
        )
        keyboard = [
            [InlineKeyboardButton("🔑 Мой код", callback_data="teacher_profile")],
            [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return ConversationHandler.END

    # Показываем выбор типа задания
    text = (
        "📝 <b>Создание домашнего задания</b>\n\n"
        "Выберите тип задания:"
    )

    keyboard = [
        [InlineKeyboardButton("💡 Задание 19", callback_data="assign_task_task19")],
        [InlineKeyboardButton("⚙️ Задание 20", callback_data="assign_task_task20")],
        [InlineKeyboardButton("📊 Задание 24", callback_data="assign_task_task24")],
        [InlineKeyboardButton("💻 Задание 25", callback_data="assign_task_task25")],
        [InlineKeyboardButton("◀️ Отмена", callback_data="teacher_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.CREATE_ASSIGNMENT


async def select_task_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор типа задачи и переход к выбору учеников"""
    query = update.callback_query
    await query.answer()

    # Извлекаем тип задачи из callback_data
    task_type = query.data.replace("assign_task_", "")

    # Сохраняем выбранный тип задания
    context.user_data['assignment_task_type'] = task_type

    task_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    # Получаем список учеников
    user_id = update.effective_user.id
    student_ids = await teacher_service.get_teacher_students(user_id)

    # Инициализируем список выбранных учеников
    if 'selected_students' not in context.user_data:
        context.user_data['selected_students'] = []

    text = (
        f"📝 <b>Создание задания: {task_name}</b>\n\n"
        "Выберите учеников для назначения задания:\n"
        "(можно выбрать несколько)"
    )

    keyboard = []

    # TODO: Загрузить имена учеников из БД пользователей
    for student_id in student_ids:
        selected = student_id in context.user_data['selected_students']
        emoji = "✅" if selected else "⬜"
        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} Ученик {student_id}",
                callback_data=f"toggle_student_{student_id}"
            )
        ])

    if context.user_data['selected_students']:
        keyboard.append([InlineKeyboardButton("➡️ Далее", callback_data="assignment_set_deadline")])

    keyboard.append([InlineKeyboardButton("◀️ Отмена", callback_data="teacher_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.CREATE_ASSIGNMENT


async def toggle_student_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Переключение выбора ученика"""
    query = update.callback_query
    await query.answer()

    # Извлекаем student_id из callback_data
    student_id = int(query.data.replace("toggle_student_", ""))

    # Переключаем выбор
    if 'selected_students' not in context.user_data:
        context.user_data['selected_students'] = []

    if student_id in context.user_data['selected_students']:
        context.user_data['selected_students'].remove(student_id)
    else:
        context.user_data['selected_students'].append(student_id)

    # Перерисовываем меню
    return await select_task_type(update, context)


async def set_assignment_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка дедлайна для задания"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type', '')
    task_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    selected_count = len(context.user_data.get('selected_students', []))

    text = (
        f"📝 <b>Создание задания: {task_name}</b>\n\n"
        f"👥 Выбрано учеников: {selected_count}\n\n"
        "Установите дедлайн для выполнения задания:"
    )

    from datetime import datetime, timedelta

    keyboard = []

    # Предлагаем варианты дедлайнов
    today = datetime.now()
    for days in [1, 3, 7, 14]:
        deadline_date = today + timedelta(days=days)
        date_str = deadline_date.strftime("%d.%m.%Y")
        keyboard.append([
            InlineKeyboardButton(
                f"Через {days} дн. ({date_str})",
                callback_data=f"deadline_{days}"
            )
        ])

    keyboard.append([InlineKeyboardButton("⏰ Без дедлайна", callback_data="deadline_none")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"assign_task_{task_type}")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.CREATE_ASSIGNMENT


async def confirm_and_create_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение и создание задания"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Извлекаем данные из контекста
    task_type = context.user_data.get('assignment_task_type')
    selected_students = context.user_data.get('selected_students', [])

    # Парсим дедлайн из callback_data
    deadline_days = query.data.replace("deadline_", "")

    deadline = None
    if deadline_days != "none":
        from datetime import datetime, timedelta
        deadline = datetime.now() + timedelta(days=int(deadline_days))

    # Создаём задание через assignment_service
    from ..services import assignment_service
    from ..models import AssignmentType, TargetType

    task_names = {
        'task19': 'Задание 19',
        'task20': 'Задание 20',
        'task24': 'Задание 24',
        'task25': 'Задание 25'
    }
    title = task_names.get(task_type, f"Задание {task_type}")

    assignment_data = {
        'task_module': task_type,
        'questions_count': 10  # По умолчанию 10 вопросов
    }

    homework = await assignment_service.create_homework_assignment(
        teacher_id=user_id,
        title=title,
        assignment_type=AssignmentType.EXISTING_TASK,
        assignment_data=assignment_data,
        target_type=TargetType.SELECTED_STUDENTS,
        student_ids=selected_students,
        description=f"Практика по теме '{title}'",
        deadline=deadline
    )

    if homework:
        deadline_text = deadline.strftime("%d.%m.%Y") if deadline else "не установлен"

        text = (
            "✅ <b>Задание успешно создано!</b>\n\n"
            f"📝 <b>Тип:</b> {title}\n"
            f"👥 <b>Назначено учеников:</b> {len(selected_students)}\n"
            f"⏰ <b>Дедлайн:</b> {deadline_text}\n\n"
            "Ученики получат уведомление о новом задании."
        )

        keyboard = [
            [InlineKeyboardButton("📊 Статистика по заданию", callback_data=f"homework_stats_{homework.id}")],
            [InlineKeyboardButton("◀️ В меню учителя", callback_data="teacher_menu")]
        ]
    else:
        text = (
            "❌ <b>Ошибка при создании задания</b>\n\n"
            "Попробуйте еще раз позже."
        )
        keyboard = [[InlineKeyboardButton("◀️ В меню учителя", callback_data="teacher_menu")]]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    # Очищаем контекст
    context.user_data.pop('assignment_task_type', None)
    context.user_data.pop('selected_students', None)

    return ConversationHandler.END


async def show_student_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать список учеников учителя"""
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

    if not student_ids:
        text = (
            "👥 <b>Мои ученики</b>\n\n"
            "У вас пока нет учеников.\n\n"
            f"📤 Отправьте свой код <code>{profile.teacher_code}</code> ученикам, "
            "чтобы они могли подключиться к вам."
        )
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
        ]
    else:
        max_students = profile.max_students
        max_students_text = "∞" if max_students == -1 else str(max_students)

        text = (
            "👥 <b>Мои ученики</b>\n\n"
            f"📊 Всего учеников: {len(student_ids)}/{max_students_text}\n\n"
        )

        # TODO: Получить имена учеников из БД пользователей
        text += "<b>Список учеников:</b>\n"
        for i, student_id in enumerate(student_ids, 1):
            text += f"{i}. Ученик ID: {student_id}\n"

        keyboard = [
            [InlineKeyboardButton("📊 Общая статистика", callback_data="teacher_statistics")],
            [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


async def show_teacher_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать статистику учителя"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем список учеников
    student_ids = await teacher_service.get_teacher_students(user_id)

    # Получаем все задания учителя
    from ..services import assignment_service
    homeworks = await assignment_service.get_teacher_homeworks(user_id)

    # Собираем статистику
    total_students = len(student_ids)
    total_homeworks = len(homeworks)

    # Считаем статистику по заданиям
    active_homeworks = sum(1 for hw in homeworks if hw.status.value == 'active')
    completed_count = 0
    in_progress_count = 0

    for hw in homeworks:
        stats = await assignment_service.get_homework_statistics(hw.id)
        completed_count += stats.get('completed', 0) + stats.get('checked', 0)
        in_progress_count += stats.get('in_progress', 0)

    text = (
        "📊 <b>Статистика учителя</b>\n\n"
        f"👥 <b>Учеников:</b> {total_students}\n"
        f"📝 <b>Всего заданий:</b> {total_homeworks}\n"
        f"✅ <b>Активных заданий:</b> {active_homeworks}\n\n"
        "<b>Выполнение заданий:</b>\n"
        f"✅ Завершено: {completed_count}\n"
        f"⏳ В процессе: {in_progress_count}\n"
    )

    if homeworks:
        text += "\n<b>Последние задания:</b>\n"
        for hw in homeworks[:5]:  # Показываем последние 5
            status_emoji = {
                'active': '✅',
                'archived': '📦',
                'draft': '📝'
            }.get(hw.status.value, '❓')

            deadline_text = ""
            if hw.deadline:
                deadline_text = f" (до {hw.deadline.strftime('%d.%m')})"

            text += f"\n{status_emoji} {hw.title}{deadline_text}"

    keyboard = [
        [InlineKeyboardButton("👥 Список учеников", callback_data="teacher_students")],
        [InlineKeyboardButton("📋 Мои задания", callback_data="teacher_my_assignments")],
        [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


async def show_teacher_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать список заданий учителя"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем все задания учителя
    from ..services import assignment_service
    homeworks = await assignment_service.get_teacher_homeworks(user_id)

    if not homeworks:
        text = (
            "📋 <b>Мои задания</b>\n\n"
            "У вас пока нет созданных заданий."
        )
        keyboard = [
            [InlineKeyboardButton("➕ Создать задание", callback_data="teacher_create_assignment")],
            [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
        ]
    else:
        text = (
            "📋 <b>Мои задания</b>\n\n"
            f"Всего заданий: {len(homeworks)}\n"
            "Выберите задание для просмотра статистики:"
        )

        keyboard = []
        for hw in homeworks[:10]:  # Показываем последние 10
            # Получаем статистику по заданию
            stats = await assignment_service.get_homework_statistics(hw.id)

            status_emoji = {
                'active': '✅',
                'archived': '📦',
                'draft': '📝'
            }.get(hw.status.value, '❓')

            deadline_text = ""
            if hw.deadline:
                deadline_text = f" до {hw.deadline.strftime('%d.%m')}"

            button_text = f"{status_emoji} {hw.title} ({stats['completed']}/{stats['total']}){deadline_text}"

            keyboard.append([
                InlineKeyboardButton(button_text, callback_data=f"homework_stats_{hw.id}")
            ])

        keyboard.append([InlineKeyboardButton("➕ Создать новое задание", callback_data="teacher_create_assignment")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


async def show_homework_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать детальную статистику по заданию"""
    query = update.callback_query
    await query.answer()

    # Извлекаем homework_id из callback_data
    homework_id = int(query.data.replace("homework_stats_", ""))

    # Получаем задание
    from ..services import assignment_service
    homework = await assignment_service.get_homework_by_id(homework_id)

    if not homework:
        await query.message.edit_text(
            "❌ Задание не найдено.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Получаем статистику
    stats = await assignment_service.get_homework_statistics(homework_id)

    deadline_text = "не установлен"
    if homework.deadline:
        deadline_text = homework.deadline.strftime("%d.%m.%Y %H:%M")

    text = (
        f"📊 <b>Статистика: {homework.title}</b>\n\n"
        f"📝 <b>Описание:</b> {homework.description or 'Не указано'}\n"
        f"⏰ <b>Дедлайн:</b> {deadline_text}\n"
        f"📅 <b>Создано:</b> {homework.created_at.strftime('%d.%m.%Y')}\n\n"
        "<b>Статус выполнения:</b>\n"
        f"👥 Всего учеников: {stats['total']}\n"
        f"✅ Завершили: {stats['completed']} ({stats['completed']*100//stats['total'] if stats['total'] > 0 else 0}%)\n"
        f"✔️ Проверено: {stats['checked']}\n"
        f"⏳ В процессе: {stats['in_progress']}\n"
        f"📝 Назначено: {stats['assigned']}\n"
    )

    keyboard = [
        [InlineKeyboardButton("📋 Все задания", callback_data="teacher_my_assignments")],
        [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU

