"""
Обработчики для учителей.

АРХИТЕКТУРА ИНТЕГРАЦИИ С PAYMENT МОДУЛЕМ:
==========================================

Этот модуль содержит обработчики для teacher ConversationHandler, включая
интеграцию с payment модулем для оформления подписок учителей.

ПРОБЛЕМА:
---------
У нас есть два ConversationHandler'а:
1. payment ConversationHandler (group=-50) - обрабатывается ПЕРВЫМ
2. teacher ConversationHandler (group=-40) - обрабатывается ВТОРЫМ

Когда пользователь находится в режиме учителя и хочет оформить подписку,
нам нужно обработать payment flow БЕЗ выхода из teacher conversation,
иначе теряется контекст и состояние пользователя.

РЕШЕНИЕ:
--------
Создан "мост" между teacher и payment модулями:
- handle_teacher_subscription_payment() - начало оплаты (pay_teacher_)
- handle_payment_callback() - обработка payment callbacks (confirm, duration, etc)
- handle_payment_email_input() - ввод email для оплаты

Эти функции делегируют вызовы в payment.handlers, но:
1. Остаются в контексте teacher ConversationHandler
2. Управляют переходами состояний (TEACHER_MENU ↔ PAYMENT_ENTERING_EMAIL)
3. Обрабатывают ошибки и логируют действия

МАСШТАБИРОВАНИЕ:
----------------
При добавлении новых типов подписок или изменении payment flow,
нужно обновить только маршрутизацию в handle_payment_callback().
Основная логика остается в payment модуле - это обеспечивает
единую точку правды для всех платежных операций.

ОТЛАДКА:
--------
Все payment-related операции логируются с префиксом [Teacher Payment]
для упрощения отладки и мониторинга.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from ..states import TeacherStates
from ..services import teacher_service
from payment.config import get_all_teacher_plans, is_teacher_plan
from core.config import ADMIN_IDS

logger = logging.getLogger(__name__)


async def is_teacher(user_id: int) -> bool:
    """Проверяет, является ли пользователь учителем"""
    profile = await teacher_service.get_teacher_profile(user_id)
    return profile is not None


async def has_active_teacher_subscription(user_id: int) -> bool:
    """
    Проверяет, есть ли у учителя активная подписка.

    УНИФИЦИРОВАНО: Использует единую функцию has_teacher_access() из teacher_service.
    Проверяет существование профиля, активность и дату истечения подписки.
    """
    return await teacher_service.has_teacher_access(user_id)


async def teacher_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Главное меню учителя"""
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    user_id = update.effective_user.id

    # Админы имеют доступ к режиму учителя по умолчанию
    is_admin = user_id in ADMIN_IDS

    # ИСПРАВЛЕНИЕ: Автоматически создаем профиль учителя для администратора
    if is_admin:
        profile = await teacher_service.get_teacher_profile(user_id)
        if not profile:
            # Получаем имя пользователя
            user = update.effective_user
            display_name = user.first_name or user.username or f"Admin {user_id}"

            # Создаем профиль учителя для администратора с полным доступом
            profile = await teacher_service.create_teacher_profile(
                user_id=user_id,
                display_name=display_name,
                subscription_tier='teacher_premium'
            )

            # Активируем подписку для администратора
            if profile:
                import aiosqlite
                from datetime import datetime, timedelta
                from core.config import DATABASE_FILE

                async with aiosqlite.connect(DATABASE_FILE) as db:
                    # Устанавливаем бессрочную активную подписку для админа
                    expires = datetime.now() + timedelta(days=3650)  # 10 лет
                    await db.execute("""
                        UPDATE teacher_profiles
                        SET has_active_subscription = 1,
                            subscription_expires = ?,
                            subscription_tier = 'teacher_premium'
                        WHERE user_id = ?
                    """, (expires, user_id))
                    await db.commit()

                logger.info(f"Автоматически создан профиль учителя для администратора {user_id}")

    # Проверяем, является ли пользователь учителем (или админом)
    if not is_admin and not await is_teacher(user_id):
        text = (
            "👨‍🏫 <b>Режим учителя</b>\n\n"
            "У вас еще нет профиля учителя.\n\n"
            "Чтобы стать учителем, оформите подписку для учителей.\n\n"
            "💡 <b>Что вы получите:</b>\n"
            "• Создание домашних заданий для учеников\n"
            "• Отслеживание прогресса в режиме реального времени\n"
            "• Подробная статистика по каждому ученику\n"
            "• Возможность подарить подписку\n\n"
            "📝 <b>Примеры заданий:</b>\n"
            "• <i>\"Решить 15 вопросов из тестовой части\"</i>\n"
            "• <i>\"Написать план по теме 'Политическая система'\"</i>\n"
            "• <i>\"Составить аргументы за и против федерализма\"</i>\n\n"
            "🎯 <b>Автоматизация:</b>\n"
            "ИИ проверяет задания учеников, вы видите результаты и слабые места"
        )

        keyboard = [
            [InlineKeyboardButton("💳 Подписки для учителей", callback_data="teacher_subscriptions")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_cabinet")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return TeacherStates.TEACHER_MENU  # Остаемся в состоянии, чтобы кнопки работали

    # Проверяем активность подписки (админы освобождаются от этой проверки)
    if not is_admin and not await has_active_teacher_subscription(user_id):
        text = (
            "👨‍🏫 <b>Режим учителя</b>\n\n"
            "⚠️ Ваша подписка учителя неактивна.\n\n"
            "Продлите подписку, чтобы продолжить работу с учениками."
        )

        keyboard = [
            [InlineKeyboardButton("💳 Продлить подписку", callback_data="teacher_subscriptions")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_to_cabinet")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return TeacherStates.TEACHER_MENU  # Остаемся в состоянии, чтобы кнопки работали

    # Все проверки пройдены - показываем меню
    keyboard = [
        [InlineKeyboardButton("👥 Мои ученики", callback_data="teacher_students")],
        [InlineKeyboardButton("📋 Мои задания", callback_data="teacher_my_assignments")],
        [InlineKeyboardButton("➕ Создать задание", callback_data="teacher_create_assignment")],
        [InlineKeyboardButton("📊 Статистика", callback_data="teacher_statistics")],
        [InlineKeyboardButton("🎁 Подарить подписку", callback_data="teacher_gift_menu")],
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
    is_admin = user_id in ADMIN_IDS

    # Получаем профиль учителя
    profile = await teacher_service.get_teacher_profile(user_id)

    # Если админ без профиля учителя - показываем упрощённое сообщение
    if not profile and is_admin:
        text = (
            "👤 <b>Ваш профиль учителя</b>\n\n"
            "👑 <b>Статус:</b> Администратор\n"
            "🔓 <b>Доступ:</b> Полный доступ к функциям учителя\n\n"
            "ℹ️ У вас нет профиля учителя, но как администратор вы имеете полный доступ к функциям.\n\n"
            "💡 Чтобы получить код для учеников, оформите подписку учителя."
        )
        keyboard = [
            [InlineKeyboardButton("💳 Оформить подписку", callback_data="teacher_subscriptions")],
            [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return TeacherStates.TEACHER_MENU

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
        "⏱️ <b>Экономьте время на проверке ДЗ:</b>\n"
        "• ИИ автоматически проверяет задания учеников\n"
        "• Вы видите готовые результаты и аналитику\n"
        "• Фокусируйтесь на обучении, а не на рутине\n\n"
        "📊 <b>Отслеживайте прогресс:</b>\n"
        "• Статистика по каждому ученику\n"
        "• Слабые и сильные стороны\n"
        "• История выполнения заданий\n\n"
        "💰 <b>Дополнительный доход:</b>\n"
        "• Подарите ученику скидку на подписку (100₽)\n"
        "• Повысьте ценность своих занятий\n\n"
        "👇 <b>Выберите подходящий тариф:</b>\n"
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
        [InlineKeyboardButton("💳 Оформить подписку", callback_data=f"pay_{plan_id}")],
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

    # Проверяем, что пользователь учитель (админы освобождаются от проверки)
    is_admin = user_id in ADMIN_IDS
    if not is_admin and not await has_active_teacher_subscription(user_id):
        await query.message.edit_text(
            "❌ Для создания заданий требуется активная подписка учителя.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Показываем выбор типа задания (ученики не обязательны)
    text = (
        "📝 <b>Создание домашнего задания</b>\n\n"
        "Выберите тип задания:"
    )

    keyboard = [
        [InlineKeyboardButton("💡 Задание 19", callback_data="assign_task_task19")],
        [InlineKeyboardButton("⚙️ Задание 20", callback_data="assign_task_task20")],
        [InlineKeyboardButton("📊 Задание 24", callback_data="assign_task_task24")],
        [InlineKeyboardButton("💻 Задание 25", callback_data="assign_task_task25")],
        [InlineKeyboardButton("🔀 Смешанное задание", callback_data="assign_task_mixed")],
        [InlineKeyboardButton("📝 Кастомное задание", callback_data="assign_task_custom")],
        [InlineKeyboardButton("◀️ Отмена", callback_data="teacher_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.CREATE_ASSIGNMENT


async def select_task_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор типа задачи и переход к выбору способа отбора"""
    query = update.callback_query
    await query.answer()

    # Извлекаем тип задачи из callback_data
    task_type = query.data.replace("assign_task_", "")

    # Обрабатываем смешанный тип отдельно
    if task_type == "mixed":
        context.user_data['assignment_task_type'] = 'mixed'
        context.user_data['mixed_modules'] = []  # Список выбранных модулей
        context.user_data['mixed_modules_data'] = []  # Данные по каждому модулю
        return await show_mixed_modules_selection(update, context)

    # Обрабатываем кастомный тип отдельно
    if task_type == "custom":
        context.user_data['assignment_task_type'] = 'custom'
        context.user_data['custom_questions'] = []  # Список кастомных вопросов
        return await start_custom_question_entry(update, context)

    # Сохраняем выбранный тип задания
    context.user_data['assignment_task_type'] = task_type

    task_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    # Показываем выбор способа отбора заданий
    text = (
        f"📝 <b>Создание задания: {task_name}</b>\n\n"
        "Выберите способ отбора заданий:\n\n"
        "🎲 <b>Все задания</b> - случайные задания из всего банка\n"
        "📚 <b>По темам</b> - выбор конкретных тем из кодификатора\n"
        "🔢 <b>Конкретные номера</b> - ввод ID конкретных заданий"
    )

    keyboard = [
        [InlineKeyboardButton("🎲 Все задания", callback_data="selection_mode_all")],
        [InlineKeyboardButton("📚 По темам", callback_data="selection_mode_topics")],
        [InlineKeyboardButton("🔢 Конкретные номера", callback_data="selection_mode_numbers")],
        [InlineKeyboardButton("◀️ Назад", callback_data="teacher_create_assignment")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.SELECT_SELECTION_MODE


async def select_selection_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора способа отбора заданий"""
    query = update.callback_query
    await query.answer()

    mode = query.data.replace("selection_mode_", "")
    task_type = context.user_data.get('assignment_task_type')

    # Сохраняем выбранный режим
    context.user_data['selection_mode'] = mode

    task_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    # Обрабатываем разные режимы отбора
    if mode == "all":
        # Режим "Все задания" - запрашиваем количество заданий
        from ..services.topics_loader import load_topics_for_module

        topics_data = load_topics_for_module(task_type)
        total_count = topics_data['total_count']

        await query.message.edit_text(
            f"🎲 <b>{task_name}: Случайные задания</b>\n\n"
            f"📚 В банке доступно: {total_count} заданий\n\n"
            "Сколько заданий вы хотите включить в домашнюю работу?\n\n"
            "Введите число (например: 5, 10, 15):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Отмена", callback_data=f"assign_task_{task_type}")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.ENTER_QUESTION_COUNT

    elif mode == "topics":
        # Режим "По темам" - показываем список блоков
        return await show_topic_blocks_selection(update, context)

    elif mode == "numbers":
        # Режим "Конкретные номера" - показываем инструкцию для ввода
        from ..services.topics_loader import load_topics_for_module

        topics_data = load_topics_for_module(task_type)
        total_count = topics_data['total_count']

        await query.message.edit_text(
            f"🔢 <b>{task_name}: Ввод номеров заданий</b>\n\n"
            f"📚 В банке доступно: {total_count} заданий (ID: 1-{total_count})\n\n"
            "Введите ID заданий одним сообщением:\n\n"
            "<b>Примеры форматов:</b>\n"
            "• Отдельные номера: <code>1,5,10,23</code>\n"
            "• Диапазоны: <code>1-5,10-15,20</code>\n"
            "• Комбинированно: <code>1,3,5-10,15,20-25</code>\n\n"
            "💡 Можно использовать пробелы для читаемости",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Отмена", callback_data=f"assign_task_{task_type}")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.ENTER_QUESTION_NUMBERS

    return TeacherStates.CREATE_ASSIGNMENT


def parse_question_numbers(input_text: str) -> list:
    """
    Парсит строку с номерами заданий.

    Поддерживаемые форматы:
    - Отдельные номера: "1,5,10"
    - Диапазоны: "1-5,10-15"
    - Комбинированно: "1,3,5-10,15"

    Args:
        input_text: Строка с номерами

    Returns:
        Список уникальных ID заданий
    """
    result = set()

    # Убираем пробелы
    text = input_text.replace(' ', '')

    # Разбиваем по запятым
    parts = text.split(',')

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Проверяем, есть ли диапазон
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                start_num = int(start)
                end_num = int(end)

                if start_num > end_num:
                    raise ValueError(f"Некорректный диапазон: {part}")

                result.update(range(start_num, end_num + 1))
            except ValueError as e:
                raise ValueError(f"Ошибка в диапазоне '{part}': {e}")
        else:
            # Отдельный номер
            try:
                num = int(part)
                result.add(num)
            except ValueError:
                raise ValueError(f"Некорректный номер: '{part}'")

    return sorted(list(result))


async def process_question_numbers_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода номеров заданий"""
    user_input = update.message.text
    task_type = context.user_data.get('assignment_task_type')

    task_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    try:
        # Парсим введенные номера
        question_ids = parse_question_numbers(user_input)

        if not question_ids:
            await update.message.reply_text(
                "❌ Не удалось распознать номера заданий.\n\n"
                "Попробуйте еще раз, например: <code>1,5,10-15</code>",
                parse_mode='HTML'
            )
            return TeacherStates.ENTER_QUESTION_NUMBERS

        # Проверяем валидность номеров
        from ..services.topics_loader import load_topics_for_module

        topics_data = load_topics_for_module(task_type)
        valid_ids = set(topics_data['topics_by_id'].keys())

        invalid_ids = [qid for qid in question_ids if qid not in valid_ids]

        if invalid_ids:
            await update.message.reply_text(
                f"❌ Некоторые ID не найдены в банке заданий:\n"
                f"<code>{', '.join(map(str, invalid_ids[:10]))}</code>"
                f"{' и другие...' if len(invalid_ids) > 10 else ''}\n\n"
                f"Доступны ID: 1-{topics_data['total_count']}\n\n"
                "Попробуйте еще раз:",
                parse_mode='HTML'
            )
            return TeacherStates.ENTER_QUESTION_NUMBERS

        # Сохраняем выбранные ID
        context.user_data['selected_question_ids'] = question_ids
        context.user_data['selected_blocks'] = []  # Для режима "номера" блоки не используются

        # Показываем список заданий для подтверждения
        return await show_numbers_confirmation(update, context, question_ids, task_type, topics_data)

    except ValueError as e:
        await update.message.reply_text(
            f"❌ <b>Ошибка при парсинге номеров:</b>\n\n"
            f"{str(e)}\n\n"
            "Попробуйте еще раз:",
            parse_mode='HTML'
        )
        return TeacherStates.ENTER_QUESTION_NUMBERS


async def show_numbers_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                    question_ids: List[int], task_type: str,
                                    topics_data: Dict) -> int:
    """Показать список заданий по введенным номерам для подтверждения"""

    task_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    # Формируем список заданий с названиями
    text = (
        f"📝 <b>{task_name}: Подтверждение заданий</b>\n\n"
        f"✅ Выбрано заданий: {len(question_ids)}\n\n"
        "Список выбранных заданий:\n\n"
    )

    # Добавляем информацию о каждом задании
    for idx, q_id in enumerate(question_ids, 1):
        topic = topics_data['topics_by_id'].get(q_id)
        if topic:
            title = topic.get('title', 'Без названия')
            # Обрезаем длинные названия
            if len(title) > 60:
                title = title[:57] + "..."
            text += f"{idx}. <b>№{q_id}</b>: {title}\n"
        else:
            text += f"{idx}. <b>№{q_id}</b>: (название не найдено)\n"

    text += "\n<i>Подтвердите выбор или введите номера заново</i>"

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить выбор", callback_data="confirm_numbers_selection")],
        [InlineKeyboardButton("🔄 Ввести заново", callback_data=f"assign_task_{task_type}:numbers")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"assign_task_{task_type}")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем новое сообщение (так как предыдущее было текстовым вводом)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_QUESTION_NUMBERS


async def confirm_numbers_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение выбранных заданий по номерам и переход к выбору учеников"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type')
    selected_question_ids = context.user_data.get('selected_question_ids', [])

    if not selected_question_ids:
        await query.answer("⚠️ Список заданий пуст", show_alert=True)
        return TeacherStates.ENTER_QUESTION_NUMBERS

    # Сохраняем в assignment_data
    context.user_data['assignment_data'] = {
        'task_module': task_type,
        'selection_mode': 'numbers',
        'selected_blocks': [],
        'question_ids': selected_question_ids,
        'questions_count': len(selected_question_ids)
    }

    # Переходим к выбору учеников
    return await proceed_to_student_selection(update, context)


async def process_question_count_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода количества случайных заданий"""
    task_type = context.user_data.get('assignment_task_type')

    # Обработка для смешанного задания
    if task_type == 'mixed':
        return await process_mixed_question_counts(update, context)

    try:
        count = int(update.message.text.strip())

        if count <= 0:
            await update.message.reply_text(
                "❌ <b>Количество должно быть больше нуля</b>\n\n"
                "Попробуйте еще раз:",
                parse_mode='HTML'
            )
            return TeacherStates.ENTER_QUESTION_COUNT

        # Загружаем темы для проверки максимального количества
        from ..services.topics_loader import load_topics_for_module

        topics_data = load_topics_for_module(task_type)
        total_count = topics_data['total_count']

        if count > total_count:
            await update.message.reply_text(
                f"❌ <b>Слишком много заданий</b>\n\n"
                f"В банке доступно только {total_count} заданий.\n"
                f"Введите число от 1 до {total_count}:",
                parse_mode='HTML'
            )
            return TeacherStates.ENTER_QUESTION_COUNT

        # Сохраняем количество в контексте
        context.user_data['question_count'] = count

        # Генерируем случайные задания
        return await generate_and_show_random_questions(update, context, count, task_type, topics_data)

    except ValueError:
        await update.message.reply_text(
            "❌ <b>Неверный формат</b>\n\n"
            "Введите целое число (например: 5, 10, 15):",
            parse_mode='HTML'
        )
        return TeacherStates.ENTER_QUESTION_COUNT


async def generate_and_show_random_questions(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                             count: int, task_type: str, topics_data: Dict) -> int:
    """Генерирует случайные задания и показывает для подтверждения"""
    import random

    # Получаем все доступные ID
    all_question_ids = list(topics_data['topics_by_id'].keys())

    # Выбираем случайные N заданий
    if count >= len(all_question_ids):
        selected_ids = all_question_ids
    else:
        selected_ids = random.sample(all_question_ids, count)

    # Сортируем для удобства отображения
    selected_ids.sort()

    # Сохраняем в контексте
    context.user_data['selected_question_ids'] = selected_ids
    context.user_data['selected_blocks'] = []  # Для режима "все" блоки не используются

    # Показываем список для подтверждения
    task_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    text = (
        f"🎲 <b>{task_name}: Случайные задания</b>\n\n"
        f"✅ Сгенерировано заданий: {len(selected_ids)}\n\n"
        "Список выбранных заданий:\n\n"
    )

    # Добавляем информацию о каждом задании
    for idx, q_id in enumerate(selected_ids, 1):
        topic = topics_data['topics_by_id'].get(q_id)
        if topic:
            title = topic.get('title', 'Без названия')
            # Обрезаем длинные названия
            if len(title) > 60:
                title = title[:57] + "..."
            text += f"{idx}. <b>№{q_id}</b>: {title}\n"
        else:
            text += f"{idx}. <b>№{q_id}</b>: (название не найдено)\n"

    text += "\n<i>Подтвердите выбор или сгенерируйте заново</i>"

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить выбор", callback_data="confirm_all_tasks_selection")],
        [InlineKeyboardButton("🔄 Генерировать заново", callback_data="regenerate_all_tasks")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"assign_task_{task_type}")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем новое сообщение (так как предыдущее было текстовым вводом)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_QUESTION_COUNT


async def regenerate_all_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Перегенерирует случайные задания"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type')
    count = context.user_data.get('question_count', 10)

    # Загружаем темы
    from ..services.topics_loader import load_topics_for_module
    topics_data = load_topics_for_module(task_type)

    # Генерируем новые случайные задания
    import random
    all_question_ids = list(topics_data['topics_by_id'].keys())

    if count >= len(all_question_ids):
        selected_ids = all_question_ids
    else:
        selected_ids = random.sample(all_question_ids, count)

    selected_ids.sort()

    # Сохраняем в контексте
    context.user_data['selected_question_ids'] = selected_ids

    # Показываем обновленный список
    task_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    text = (
        f"🎲 <b>{task_name}: Случайные задания</b>\n\n"
        f"✅ Сгенерировано заданий: {len(selected_ids)}\n\n"
        "Список выбранных заданий:\n\n"
    )

    # Добавляем информацию о каждом задании
    for idx, q_id in enumerate(selected_ids, 1):
        topic = topics_data['topics_by_id'].get(q_id)
        if topic:
            title = topic.get('title', 'Без названия')
            # Обрезаем длинные названия
            if len(title) > 60:
                title = title[:57] + "..."
            text += f"{idx}. <b>№{q_id}</b>: {title}\n"
        else:
            text += f"{idx}. <b>№{q_id}</b>: (название не найдено)\n"

    text += "\n<i>Подтвердите выбор или сгенерируйте заново</i>"

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить выбор", callback_data="confirm_all_tasks_selection")],
        [InlineKeyboardButton("🔄 Генерировать заново", callback_data="regenerate_all_tasks")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"assign_task_{task_type}")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Редактируем сообщение
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_QUESTION_COUNT


async def confirm_all_tasks_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение случайно сгенерированных заданий и переход к выбору учеников"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type')
    selected_question_ids = context.user_data.get('selected_question_ids', [])

    if not selected_question_ids:
        await query.answer("⚠️ Список заданий пуст", show_alert=True)
        return TeacherStates.ENTER_QUESTION_COUNT

    # Сохраняем в assignment_data
    context.user_data['assignment_data'] = {
        'task_module': task_type,
        'selection_mode': 'all',
        'selected_blocks': [],
        'question_ids': selected_question_ids,
        'questions_count': len(selected_question_ids)
    }

    # Переходим к выбору учеников
    return await proceed_to_student_selection(update, context)


async def show_topic_blocks_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать выбор блоков тем для задания"""
    query = update.callback_query
    task_type = context.user_data.get('assignment_task_type')

    from ..services.topics_loader import load_topics_for_module

    # Загружаем темы для модуля
    topics_data = load_topics_for_module(task_type)
    blocks = topics_data['blocks']

    if not blocks:
        await query.message.edit_text(
            f"❌ <b>Темы не найдены</b>\n\n"
            f"Для {task_type} отсутствуют темы в банке заданий.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data=f"assign_task_{task_type}")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.SELECT_SELECTION_MODE

    # Инициализируем список выбранных блоков
    if 'selected_blocks' not in context.user_data:
        context.user_data['selected_blocks'] = []

    task_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    text = (
        f"📚 <b>{task_name}: Выбор тем</b>\n\n"
        "Выберите блоки тем из кодификатора ЕГЭ:\n"
        "(можно выбрать несколько)\n\n"
    )

    # Показываем статистику по блокам
    for block_name, block_topics in blocks.items():
        text += f"• {block_name}: {len(block_topics)} тем\n"

    keyboard = []

    # Создаем кнопки для каждого блока
    for block_name in sorted(blocks.keys()):
        selected = block_name in context.user_data['selected_blocks']
        emoji = "✅" if selected else "⬜"
        topic_count = len(blocks[block_name])

        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {block_name} ({topic_count})",
                callback_data=f"toggle_block:{block_name}"
            )
        ])

    # Кнопка "Далее" если выбран хотя бы один блок
    if context.user_data['selected_blocks']:
        total_topics = sum(
            len(blocks[b]) for b in context.user_data['selected_blocks']
        )
        keyboard.append([
            InlineKeyboardButton(
                f"➡️ Выбрано блоков: {len(context.user_data['selected_blocks'])} ({total_topics} тем)",
                callback_data="topics_confirm_blocks"
            )
        ])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"assign_task_{task_type}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.SELECT_TOPICS


async def toggle_block_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Переключение выбора блока тем"""
    query = update.callback_query
    await query.answer()

    # Извлекаем название блока из callback_data
    block_name = query.data.replace("toggle_block:", "")

    # Переключаем выбор
    if 'selected_blocks' not in context.user_data:
        context.user_data['selected_blocks'] = []

    if block_name in context.user_data['selected_blocks']:
        context.user_data['selected_blocks'].remove(block_name)
    else:
        context.user_data['selected_blocks'].append(block_name)

    # Перерисовываем меню
    return await show_topic_blocks_selection(update, context)


async def confirm_topic_blocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение выбора блоков тем и переход к выбору конкретных заданий"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type')
    selected_blocks = context.user_data.get('selected_blocks', [])

    if not selected_blocks:
        await query.answer("⚠️ Выберите хотя бы один блок", show_alert=True)
        return TeacherStates.SELECT_TOPICS

    # Переходим к выбору конкретных заданий из этих блоков
    return await show_specific_questions_selection(update, context)


async def show_specific_questions_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать список конкретных заданий из выбранных блоков для выбора"""
    query = update.callback_query

    task_type = context.user_data.get('assignment_task_type')
    selected_blocks = context.user_data.get('selected_blocks', [])

    from ..services.topics_loader import load_topics_for_module

    # Загружаем все темы
    topics_data = load_topics_for_module(task_type)

    # Инициализируем список выбранных заданий если его нет
    if 'selected_question_ids' not in context.user_data:
        context.user_data['selected_question_ids'] = []

    # Собираем все задания из выбранных блоков
    available_questions = []
    for block_name in selected_blocks:
        block_topics = topics_data['blocks'].get(block_name, [])
        available_questions.extend(block_topics)

    if not available_questions:
        await query.answer("⚠️ В выбранных блоках нет заданий", show_alert=True)
        return TeacherStates.SELECT_TOPICS

    # Формируем текст
    task_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    selected_count = len(context.user_data['selected_question_ids'])
    total_count = len(available_questions)

    text = (
        f"📝 <b>{task_name}: Выбор заданий</b>\n\n"
        f"📚 Блоки: {', '.join(selected_blocks)}\n"
        f"✅ Выбрано: {selected_count} из {total_count}\n\n"
        "Выберите конкретные задания для домашней работы:\n"
        "(отметьте нужные галочками)"
    )

    keyboard = []

    # Добавляем кнопки для каждого задания
    for question in available_questions:
        q_id = question['id']
        q_title = question['title']

        # Обрезаем длинные названия
        if len(q_title) > 50:
            q_title = q_title[:47] + "..."

        selected = q_id in context.user_data['selected_question_ids']
        emoji = "✅" if selected else "⬜"

        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {q_id}. {q_title}",
                callback_data=f"toggle_question:{q_id}"
            )
        ])

    # Кнопки управления
    if selected_count > 0:
        keyboard.append([
            InlineKeyboardButton(f"✅ Подтвердить выбор ({selected_count})", callback_data="confirm_selected_questions")
        ])

    keyboard.append([
        InlineKeyboardButton("🔄 Выбрать все", callback_data="select_all_questions"),
        InlineKeyboardButton("❌ Снять все", callback_data="deselect_all_questions")
    ])
    keyboard.append([
        InlineKeyboardButton("◀️ Назад к блокам", callback_data=f"assign_task_{task_type}")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.SELECT_SPECIFIC_QUESTIONS


async def toggle_question_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Переключение выбора конкретного задания"""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID задания из callback_data
    question_id = int(query.data.split(':')[1])

    # Переключаем выбор
    if 'selected_question_ids' not in context.user_data:
        context.user_data['selected_question_ids'] = []

    if question_id in context.user_data['selected_question_ids']:
        context.user_data['selected_question_ids'].remove(question_id)
    else:
        context.user_data['selected_question_ids'].append(question_id)

    # Перерисовываем меню
    return await show_specific_questions_selection(update, context)


async def select_all_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбрать все задания из текущих блоков"""
    query = update.callback_query
    await query.answer("✅ Все задания выбраны")

    task_type = context.user_data.get('assignment_task_type')
    selected_blocks = context.user_data.get('selected_blocks', [])

    from ..services.topics_loader import load_topics_for_module

    topics_data = load_topics_for_module(task_type)

    # Собираем все ID заданий из выбранных блоков
    all_ids = []
    for block_name in selected_blocks:
        block_topics = topics_data['blocks'].get(block_name, [])
        all_ids.extend([q['id'] for q in block_topics])

    context.user_data['selected_question_ids'] = all_ids

    # Перерисовываем меню
    return await show_specific_questions_selection(update, context)


async def deselect_all_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Снять выбор со всех заданий"""
    query = update.callback_query
    await query.answer("❌ Выбор снят")

    context.user_data['selected_question_ids'] = []

    # Перерисовываем меню
    return await show_specific_questions_selection(update, context)


async def confirm_selected_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение выбранных заданий и переход к выбору учеников"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type')
    selected_blocks = context.user_data.get('selected_blocks', [])
    selected_question_ids = context.user_data.get('selected_question_ids', [])

    if not selected_question_ids:
        await query.answer("⚠️ Выберите хотя бы одно задание", show_alert=True)
        return TeacherStates.SELECT_SPECIFIC_QUESTIONS

    # Сохраняем в assignment_data
    context.user_data['assignment_data'] = {
        'task_module': task_type,
        'selection_mode': 'topics',
        'selected_blocks': selected_blocks,
        'question_ids': selected_question_ids,
        'questions_count': len(selected_question_ids)
    }

    # Переходим к выбору учеников
    return await proceed_to_student_selection(update, context)


async def proceed_to_student_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Переход к выбору учеников после определения заданий"""
    query = update.callback_query
    task_type = context.user_data.get('assignment_task_type')

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

    keyboard = []

    if not student_ids:
        # Если учеников нет - предлагаем создать задание как черновик
        text = (
            f"📝 <b>Создание задания: {task_name}</b>\n\n"
            "У вас пока нет подключенных учеников.\n\n"
            "Вы можете создать задание сейчас, и назначить его ученикам позже, "
            "когда они подключатся к вам."
        )
        keyboard.append([InlineKeyboardButton("➡️ Создать задание", callback_data="assignment_set_deadline")])
        keyboard.append([InlineKeyboardButton("🔑 Мой код учителя", callback_data="teacher_profile")])
    else:
        # Если есть ученики - показываем список для выбора
        text = (
            f"📝 <b>Создание задания: {task_name}</b>\n\n"
            "Выберите учеников для назначения задания:\n"
            "(можно выбрать несколько или создать задание без назначения)"
        )

        # Получаем отображаемые имена учеников
        student_names = await teacher_service.get_users_display_names(student_ids)

        for student_id in student_ids:
            selected = student_id in context.user_data['selected_students']
            emoji = "✅" if selected else "⬜"
            display_name = student_names.get(student_id, f"ID: {student_id}")
            keyboard.append([
                InlineKeyboardButton(
                    f"{emoji} {display_name}",
                    callback_data=f"toggle_student_{student_id}"
                )
            ])

        # Всегда показываем кнопку "Далее", даже если ученики не выбраны
        if context.user_data['selected_students']:
            keyboard.append([InlineKeyboardButton("➡️ Назначить выбранным", callback_data="assignment_set_deadline")])
        else:
            keyboard.append([InlineKeyboardButton("➡️ Создать без назначения", callback_data="assignment_set_deadline")])

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

    # Перерисовываем меню выбора учеников
    return await proceed_to_student_selection(update, context)


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

    if selected_count > 0:
        text = (
            f"📝 <b>Создание задания: {task_name}</b>\n\n"
            f"👥 Выбрано учеников: {selected_count}\n\n"
            "Установите дедлайн для выполнения задания:"
        )
    else:
        text = (
            f"📝 <b>Создание задания: {task_name}</b>\n\n"
            "📋 Задание будет создано без назначения конкретным ученикам\n\n"
            "Установите дедлайн для выполнения задания:"
        )

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

    # Используем assignment_data из контекста если он установлен, иначе создаем по умолчанию
    assignment_data = context.user_data.get('assignment_data', {
        'task_module': task_type,
        'questions_count': 10,  # По умолчанию 10 вопросов
        'selection_mode': 'all'  # По умолчанию все задания
    })

    # Определяем тип назначения в зависимости от выбранных учеников
    if selected_students:
        target_type = TargetType.SPECIFIC_STUDENTS
    else:
        target_type = TargetType.ALL_STUDENTS

    homework = await assignment_service.create_homework_assignment(
        teacher_id=user_id,
        title=title,
        assignment_type=AssignmentType.EXISTING_TOPICS,
        assignment_data=assignment_data,
        target_type=target_type,
        student_ids=selected_students if selected_students else [],
        description=f"Практика по теме '{title}'",
        deadline=deadline
    )

    if homework:
        deadline_text = deadline.strftime("%d.%m.%Y") if deadline else "не установлен"

        if selected_students:
            # Задание назначено ученикам
            text = (
                "✅ <b>Задание успешно создано!</b>\n\n"
                f"📝 <b>Тип:</b> {title}\n"
                f"👥 <b>Назначено учеников:</b> {len(selected_students)}\n"
                f"⏰ <b>Дедлайн:</b> {deadline_text}\n\n"
                "Ученики получат уведомление о новом задании."
            )
        else:
            # Задание создано без назначения
            text = (
                "✅ <b>Задание успешно создано!</b>\n\n"
                f"📝 <b>Тип:</b> {title}\n"
                f"⏰ <b>Дедлайн:</b> {deadline_text}\n\n"
                "📋 Задание создано без назначения конкретным ученикам.\n"
                "Вы сможете назначить его позже через список заданий или "
                "оно будет автоматически доступно новым ученикам."
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
    context.user_data.pop('assignment_data', None)
    context.user_data.pop('selection_mode', None)
    context.user_data.pop('selected_blocks', None)

    return ConversationHandler.END


async def show_student_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать список учеников учителя"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS

    # Получаем профиль учителя
    profile = await teacher_service.get_teacher_profile(user_id)

    # Если профиль не найден и пользователь не админ - показываем сообщение с кнопками
    if not profile and not is_admin:
        text = (
            "❌ <b>Профиль учителя не найден</b>\n\n"
            "Чтобы стать учителем и добавлять учеников, оформите подписку для учителей."
        )
        keyboard = [
            [InlineKeyboardButton("💳 Подписки для учителей", callback_data="teacher_subscriptions")],
            [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return TeacherStates.TEACHER_MENU

    # Если админ без профиля - показываем специальное сообщение
    if not profile and is_admin:
        text = (
            "👑 <b>Режим администратора</b>\n\n"
            "У вас нет профиля учителя, но как администратор вы имеете полный доступ.\n\n"
            "💡 Чтобы получить код для учеников и управлять ими, оформите подписку учителя."
        )
        keyboard = [
            [InlineKeyboardButton("💳 Оформить подписку", callback_data="teacher_subscriptions")],
            [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return TeacherStates.TEACHER_MENU

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

        # Получаем имена учеников из БД
        student_names = await teacher_service.get_users_display_names(student_ids)

        text += "<b>Список учеников:</b>\n"

        keyboard = []

        # Добавляем кнопку статистики для каждого ученика
        for i, student_id in enumerate(student_ids, 1):
            display_name = student_names.get(student_id, f"ID: {student_id}")
            text += f"{i}. {display_name}\n"

            # Добавляем кнопку с именем ученика и иконкой статистики
            button_text = f"📊 {display_name[:20]}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"student_stats:{student_id}")])

        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")])

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
        [InlineKeyboardButton("📝 Просмотреть ответы учеников", callback_data=f"homework_submissions:{homework_id}")],
        [InlineKeyboardButton("📋 Все задания", callback_data="teacher_my_assignments")],
        [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


# ========== ПОДАРКИ И ПРОМОКОДЫ ==========

async def show_gift_subscription_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Меню подарков подписок"""
    query = update.callback_query
    await query.answer()

    text = (
        "🎁 <b>Подарить подписку</b>\n\n"
        "Выберите способ подарка:"
    )

    keyboard = [
        [InlineKeyboardButton("🎟️ Создать промокод", callback_data="gift_create_promo")],
        [InlineKeyboardButton("📋 Мои промокоды", callback_data="gift_my_promos")],
        [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    return TeacherStates.TEACHER_MENU


async def show_promo_codes_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать список промокодов учителя"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    from ..services import gift_service

    # Получаем промокоды учителя
    promos = await gift_service.get_teacher_promo_codes(user_id)

    if not promos:
        text = (
            "🎟️ <b>Мои промокоды</b>\n\n"
            "У вас пока нет созданных промокодов.\n\n"
            "Создайте промокод, чтобы подарить подписку нескольким ученикам."
        )
        keyboard = [
            [InlineKeyboardButton("➕ Создать промокод", callback_data="gift_create_promo")],
            [InlineKeyboardButton("◀️ Назад", callback_data="teacher_gift_menu")]
        ]
    else:
        text = (
            f"🎟️ <b>Мои промокоды</b>\n\n"
            f"Всего промокодов: {len(promos)}\n\n"
        )

        for promo in promos[:10]:
            status = "✅ Активен" if promo.status == "active" else "❌ Использован"
            used_text = f"{promo.used_count}/{promo.max_uses if promo.max_uses else '∞'}"
            text += f"<code>{promo.code}</code> - {used_text} ({status})\n"

        keyboard = [
            [InlineKeyboardButton("➕ Создать промокод", callback_data="gift_create_promo")],
            [InlineKeyboardButton("◀️ Назад", callback_data="teacher_gift_menu")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    return TeacherStates.TEACHER_MENU


async def start_create_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало создания промокода"""
    query = update.callback_query
    await query.answer()

    text = (
        "🎟️ <b>Создание промокода</b>\n\n"
        "Промокод позволит нескольким ученикам получить подписку.\n\n"
        "Выберите срок действия подписки:"
    )

    keyboard = [
        [InlineKeyboardButton("📅 7 дней", callback_data="promo_duration_7")],
        [InlineKeyboardButton("📅 14 дней", callback_data="promo_duration_14")],
        [InlineKeyboardButton("📅 30 дней", callback_data="promo_duration_30")],
        [InlineKeyboardButton("📅 90 дней", callback_data="promo_duration_90")],
        [InlineKeyboardButton("◀️ Отмена", callback_data="gift_my_promos")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    return TeacherStates.TEACHER_MENU


async def set_promo_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка срока действия промокода"""
    query = update.callback_query
    await query.answer()

    # Извлекаем количество дней из callback_data
    days = int(query.data.replace("promo_duration_", ""))
    context.user_data['promo_duration'] = days

    text = (
        f"🎟️ <b>Создание промокода</b>\n\n"
        f"Срок подписки: {days} дней\n\n"
        "Выберите количество использований:"
    )

    keyboard = [
        [InlineKeyboardButton("1️⃣ 1 использование", callback_data="promo_uses_1")],
        [InlineKeyboardButton("5️⃣ 5 использований", callback_data="promo_uses_5")],
        [InlineKeyboardButton("🔟 10 использований", callback_data="promo_uses_10")],
        [InlineKeyboardButton("♾️ Без ограничений", callback_data="promo_uses_unlimited")],
        [InlineKeyboardButton("◀️ Назад", callback_data="gift_create_promo")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    return TeacherStates.TEACHER_MENU


async def create_promo_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Финальное создание промокода"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    uses_str = query.data.replace("promo_uses_", "")
    max_uses = None if uses_str == "unlimited" else int(uses_str)
    duration_days = context.user_data.get('promo_duration', 30)

    from ..services import gift_service

    promo = await gift_service.create_promo_code(
        creator_id=user_id,
        duration_days=duration_days,
        max_uses=max_uses,
        expires_at=None
    )

    if promo:
        uses_text = f"{max_uses} раз" if max_uses else "Неограниченно"
        text = (
            "✅ <b>Промокод создан!</b>\n\n"
            f"🎟️ <b>Код:</b> <code>{promo.code}</code>\n"
            f"📅 <b>Подписка:</b> {duration_days} дней\n"
            f"🔢 <b>Использований:</b> {uses_text}\n\n"
            "Отправьте этот код своим ученикам."
        )
        keyboard = [
            [InlineKeyboardButton("📋 Мои промокоды", callback_data="gift_my_promos")],
            [InlineKeyboardButton("➕ Создать еще", callback_data="gift_create_promo")],
            [InlineKeyboardButton("◀️ В меню", callback_data="teacher_menu")]
        ]
    else:
        text = "❌ Ошибка при создании промокода"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="gift_my_promos")]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
    context.user_data.pop('promo_duration', None)
    return TeacherStates.TEACHER_MENU


async def back_to_personal_cabinet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возврат в личный кабинет"""
    query = update.callback_query
    await query.answer()

    # Импортируем функцию показа личного кабинета
    from personal_cabinet.handlers import show_personal_cabinet

    # Показываем личный кабинет
    await show_personal_cabinet(update, context)

    # Выходим из conversation handler режима учителя
    return ConversationHandler.END


async def view_homework_submissions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Просмотр ответов учеников по конкретному заданию"""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID задания из callback_data: homework_submissions:homework_id
    homework_id = int(query.data.split(':')[1])

    # Получаем задание
    homework = await assignment_service.get_homework_by_id(homework_id)
    if not homework:
        await query.message.edit_text(
            "❌ Задание не найдено.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="teacher_my_assignments")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

    # Получаем прогресс всех учеников
    progress_by_student = await assignment_service.get_homework_all_progress(homework_id)

    # Получаем назначения для этого задания
    student_assignments = await assignment_service.get_homework_student_assignments(homework_id)

    # Получаем имена учеников
    student_ids = [sa.student_id for sa in student_assignments]
    student_names = await teacher_service.get_users_display_names(student_ids)

    text = f"📊 <b>{homework.title}</b>\n\n"
    text += f"👥 <b>Ученики: {len(student_assignments)}</b>\n\n"

    if not student_assignments:
        text += "Нет назначенных учеников."
    else:
        text += "<b>Прогресс учеников:</b>\n\n"

        for sa in student_assignments:
            student_id = sa.student_id
            student_name = student_names.get(student_id, f"ID: {student_id}")

            # Получаем прогресс этого ученика
            student_progress = progress_by_student.get(student_id, [])
            total_questions = homework.assignment_data.get('questions_count', 0)
            completed_count = len(student_progress)

            # Эмодзи статуса
            if completed_count == 0:
                emoji = "⬜"
                status = "Не начато"
            elif completed_count < total_questions:
                emoji = "🔄"
                status = f"В процессе ({completed_count}/{total_questions})"
            else:
                emoji = "✅"
                status = f"Выполнено ({completed_count}/{total_questions})"

            text += f"{emoji} <b>{student_name}</b>: {status}\n"

    keyboard = []

    # Кнопки для каждого ученика
    for sa in student_assignments:
        student_id = sa.student_id
        student_name = student_names.get(student_id, f"ID: {student_id}")
        student_progress = progress_by_student.get(student_id, [])

        if student_progress:
            keyboard.append([
                InlineKeyboardButton(
                    f"📝 {student_name} ({len(student_progress)} отв.)",
                    callback_data=f"view_student_progress:{homework_id}:{student_id}"
                )
            ])

    keyboard.append([InlineKeyboardButton("◀️ К моим заданиям", callback_data="teacher_my_assignments")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="teacher_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


async def view_student_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Просмотр ответов конкретного ученика на задание"""
    query = update.callback_query
    await query.answer()

    # Парсим callback_data: view_student_progress:homework_id:student_id
    _, homework_id_str, student_id_str = query.data.split(':')
    homework_id = int(homework_id_str)
    student_id = int(student_id_str)

    # Получаем задание
    homework = await assignment_service.get_homework_by_id(homework_id)
    if not homework:
        await query.message.edit_text(
            "❌ Задание не найдено.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="teacher_my_assignments")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

    # Получаем имя ученика
    student_names = await teacher_service.get_users_display_names([student_id])
    student_name = student_names.get(student_id, f"ID: {student_id}")

    # Получаем прогресс ученика
    progress_list = await assignment_service.get_homework_student_progress(homework_id, student_id)

    # Загружаем информацию о вопросах
    from ..services.topics_loader import load_topics_for_module
    task_module = homework.assignment_data.get('task_module')
    topics_data = load_topics_for_module(task_module)

    text = (
        f"📝 <b>{homework.title}</b>\n"
        f"👤 <b>Ученик:</b> {student_name}\n\n"
        f"📊 Выполнено заданий: {len(progress_list)}/{homework.assignment_data.get('questions_count', 0)}\n\n"
    )

    if not progress_list:
        text += "Ученик еще не приступил к выполнению."

    keyboard = []

    # Кнопки для каждого ответа
    for idx, progress in enumerate(progress_list, 1):
        q_id = progress['question_id']
        topic = topics_data['topics_by_id'].get(q_id)
        title = topic.get('title', f'Вопрос {q_id}') if topic else f'Вопрос {q_id}'

        # Обрезаем название
        if len(title) > 35:
            title = title[:32] + "..."

        emoji = "✅" if progress['is_correct'] else "❌"

        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {idx}. {title}",
                callback_data=f"view_answer:{progress['id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton("◀️ К списку учеников", callback_data=f"homework_submissions:{homework_id}")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="teacher_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


async def view_answer_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Просмотр конкретного ответа ученика с возможностью добавить комментарий"""
    query = update.callback_query
    await query.answer()

    # Парсим callback_data: view_answer:progress_id
    progress_id = int(query.data.split(':')[1])

    # Получаем прогресс по ID
    progress_data = await assignment_service.get_question_progress_by_id(progress_id)

    if not progress_data:
        await query.message.edit_text(
            "❌ Ответ не найден.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="teacher_my_assignments")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

    homework_id = progress_data['homework_id']
    student_id = progress_data['student_id']
    question_id = progress_data['question_id']

    # Получаем задание
    homework = await assignment_service.get_homework_by_id(homework_id)

    # Получаем имя ученика
    student_names = await teacher_service.get_users_display_names([student_id])
    student_name = student_names.get(student_id, f"ID: {student_id}")

    # Загружаем вопрос
    from ..services.question_loader import load_question_by_id, format_question_for_display
    task_module = homework.assignment_data.get('task_module')
    question_data = load_question_by_id(task_module, question_id)

    # Форматируем текст
    text = f"📝 <b>{homework.title}</b>\n"
    text += f"👤 <b>Ученик:</b> {student_name}\n\n"

    if question_data:
        question_text = format_question_for_display(task_module, question_data)
        text += f"<b>Вопрос:</b>\n{question_text}\n\n"

    # Обрезаем длинные ответы
    user_answer = progress_data['user_answer']
    if len(user_answer) > 2000:
        user_answer = user_answer[:1997] + "..."

    text += f"<b>Ответ ученика:</b>\n{user_answer}\n\n"

    # AI обратная связь
    if progress_data['ai_feedback']:
        feedback = progress_data['ai_feedback']
        if len(feedback) > 2000:
            feedback = feedback[:1997] + "..."
        text += f"<b>Обратная связь AI:</b>\n{feedback}\n\n"

    status = "✅ Принят" if progress_data['is_correct'] else "❌ Требует доработки"
    text += f"<b>Статус:</b> {status}\n"

    # Сохраняем progress_id в контексте для добавления комментария
    context.user_data['viewing_answer_id'] = progress_id
    context.user_data['viewing_student_id'] = student_id
    context.user_data['viewing_homework_id'] = homework_id

    keyboard = [
        [InlineKeyboardButton("💬 Добавить комментарий", callback_data=f"add_comment:{progress_id}")],
        [InlineKeyboardButton("✏️ Переоценить ответ", callback_data=f"override_score:{progress_id}")],
        [InlineKeyboardButton("◀️ К ответам ученика", callback_data=f"view_student_progress:{homework_id}:{student_id}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="teacher_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем как новое сообщение если текст слишком длинный
    if len(text) > 4000:
        await query.message.reply_text(
            "⚠️ Ответ слишком длинный, отправлен отдельным сообщением.",
            parse_mode='HTML'
        )
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


async def initiate_comment_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Начинает процесс ввода комментария учителя к ответу ученика.

    Callback pattern: add_comment:{progress_id}
    """
    query = update.callback_query
    await query.answer()

    # Извлекаем progress_id из callback_data
    progress_id = int(query.data.split(':')[1])

    # Сохраняем в контексте
    context.user_data['commenting_progress_id'] = progress_id

    text = "💬 <b>Введите комментарий к ответу ученика:</b>\n\n"
    text += "Ваш комментарий будет добавлен к AI обратной связи и виден ученику.\n\n"
    text += "Для отмены нажмите /cancel"

    keyboard = [
        [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_comment:{progress_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTERING_COMMENT


async def process_teacher_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обрабатывает введенный комментарий учителя и сохраняет его.
    """
    progress_id = context.user_data.get('commenting_progress_id')

    if not progress_id:
        await update.message.reply_text(
            "❌ Ошибка: не найден ID ответа для комментирования.",
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

    teacher_comment = update.message.text.strip()

    # Сохраняем комментарий
    from ..services import assignment_service
    success = await assignment_service.add_teacher_comment(progress_id, teacher_comment)

    if success:
        text = "✅ <b>Комментарий успешно добавлен!</b>\n\n"
        text += f"Ваш комментарий:\n{teacher_comment}"

        # Возвращаемся к просмотру ответа
        keyboard = [
            [InlineKeyboardButton("◀️ Вернуться к ответу", callback_data=f"view_answer:{progress_id}")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="teacher_menu")]
        ]
    else:
        text = "❌ <b>Ошибка при сохранении комментария.</b>\n\n"
        text += "Попробуйте еще раз или обратитесь к администратору."

        keyboard = [
            [InlineKeyboardButton("🏠 Главное меню", callback_data="teacher_menu")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    # Очищаем контекст
    context.user_data.pop('commenting_progress_id', None)

    return TeacherStates.TEACHER_MENU


async def cancel_comment_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Отменяет ввод комментария и возвращает к просмотру ответа.

    Callback pattern: cancel_comment:{progress_id}
    """
    query = update.callback_query
    await query.answer()

    progress_id = int(query.data.split(':')[1])

    # Очищаем контекст
    context.user_data.pop('commenting_progress_id', None)

    # Возвращаемся к просмотру ответа
    # Создаем фейковый update с правильным callback_data
    from telegram import Update as TelegramUpdate, CallbackQuery

    # Просто вызываем view_answer_detail напрямую
    query.data = f"view_answer:{progress_id}"
    return await view_answer_detail(update, context)


async def initiate_score_override(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Начинает процесс переоценки ответа учителя.

    Callback pattern: override_score:{progress_id}
    """
    query = update.callback_query
    await query.answer()

    # Извлекаем progress_id из callback_data
    progress_id = int(query.data.split(':')[1])

    # Получаем данные ответа
    from ..services import assignment_service
    progress_data = await assignment_service.get_question_progress_by_id(progress_id)

    if not progress_data:
        await query.message.edit_text(
            "❌ Ошибка: ответ не найден.",
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

    # Сохраняем в контексте
    context.user_data['overriding_progress_id'] = progress_id

    current_status = "✅ Принят" if progress_data['is_correct'] else "❌ Требует доработки"

    text = f"✏️ <b>Переоценка ответа</b>\n\n"
    text += f"<b>Текущий статус:</b> {current_status}\n\n"
    text += "Выберите новый статус для ответа ученика:"

    keyboard = [
        [InlineKeyboardButton("✅ Принять ответ", callback_data=f"set_score_accept:{progress_id}")],
        [InlineKeyboardButton("❌ Отклонить ответ", callback_data=f"set_score_reject:{progress_id}")],
        [InlineKeyboardButton("◀️ Отменить", callback_data=f"view_answer:{progress_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.OVERRIDING_SCORE


async def process_score_override(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обрабатывает переоценку ответа учителя.

    Callback patterns:
    - set_score_accept:{progress_id}
    - set_score_reject:{progress_id}
    """
    query = update.callback_query
    await query.answer()

    # Извлекаем action и progress_id из callback_data
    parts = query.data.split(':')
    action = parts[0]  # set_score_accept или set_score_reject
    progress_id = int(parts[1])

    # Определяем новый статус
    new_is_correct = (action == "set_score_accept")

    # Обновляем статус в БД
    from ..services import assignment_service
    success = await assignment_service.override_answer_score(progress_id, new_is_correct)

    if success:
        status_text = "принят ✅" if new_is_correct else "отклонен ❌"
        text = f"✅ <b>Оценка успешно изменена!</b>\n\n"
        text += f"Новый статус: Ответ {status_text}"

        # Добавляем комментарий об override
        override_comment = f"Оценка изменена учителем: ответ {status_text}"
        await assignment_service.add_teacher_comment(progress_id, override_comment)

        keyboard = [
            [InlineKeyboardButton("◀️ Вернуться к ответу", callback_data=f"view_answer:{progress_id}")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="teacher_menu")]
        ]
    else:
        text = "❌ <b>Ошибка при изменении оценки.</b>\n\n"
        text += "Попробуйте еще раз или обратитесь к администратору."

        keyboard = [
            [InlineKeyboardButton("🏠 Главное меню", callback_data="teacher_menu")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    # Очищаем контекст
    context.user_data.pop('overriding_progress_id', None)

    return TeacherStates.TEACHER_MENU


async def show_mixed_modules_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Показывает экран выбора модулей для смешанного задания.
    """
    query = update.callback_query

    selected_modules = context.user_data.get('mixed_modules', [])

    text = "🔀 <b>Смешанное задание</b>\n\n"
    text += "Выберите модули для включения в задание:\n\n"

    # Показываем какие модули выбраны
    module_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }

    keyboard = []
    for module_code, module_name in module_names.items():
        is_selected = module_code in selected_modules
        checkbox = "☑️" if is_selected else "◻️"
        button_text = f"{checkbox} {module_name}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"toggle_mixed_module:{module_code}")])

    # Кнопка продолжения (только если выбран хотя бы один модуль)
    if selected_modules:
        text += f"\n<b>Выбрано модулей:</b> {len(selected_modules)}"
        keyboard.append([InlineKeyboardButton("✅ Продолжить", callback_data="proceed_mixed_selection")])

    keyboard.append([InlineKeyboardButton("◀️ Отмена", callback_data="teacher_create_assignment")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.SELECT_SELECTION_MODE


async def toggle_mixed_module_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Переключает выбор модуля для смешанного задания.

    Callback pattern: toggle_mixed_module:{module_code}
    """
    query = update.callback_query
    await query.answer()

    module_code = query.data.split(':')[1]
    selected_modules = context.user_data.get('mixed_modules', [])

    if module_code in selected_modules:
        selected_modules.remove(module_code)
    else:
        selected_modules.append(module_code)

    context.user_data['mixed_modules'] = selected_modules

    return await show_mixed_modules_selection(update, context)


async def proceed_with_mixed_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Переход к вводу количества заданий для каждого выбранного модуля.
    """
    query = update.callback_query
    await query.answer()

    selected_modules = context.user_data.get('mixed_modules', [])

    if not selected_modules:
        await query.answer("⚠️ Выберите хотя бы один модуль", show_alert=True)
        return TeacherStates.SELECT_SELECTION_MODE

    module_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }

    text = "🔀 <b>Смешанное задание</b>\n\n"
    text += "Для каждого выбранного модуля введите количество заданий:\n\n"
    text += "<b>Формат:</b> числа через запятую в том же порядке\n\n"

    for module_code in selected_modules:
        text += f"• {module_names[module_code]}\n"

    text += f"\n<b>Пример:</b> 5, 3, 2 (для {len(selected_modules)} модулей)"

    keyboard = [
        [InlineKeyboardButton("◀️ Назад", callback_data="assign_task_mixed")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_QUESTION_COUNT


async def process_mixed_question_counts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обрабатывает ввод количества заданий для каждого модуля в смешанном задании.
    """
    import random
    from ..services.topics_loader import load_topics_for_module

    selected_modules = context.user_data.get('mixed_modules', [])
    user_input = update.message.text.strip()

    try:
        # Парсим числа через запятую
        counts = [int(c.strip()) for c in user_input.split(',')]

        if len(counts) != len(selected_modules):
            await update.message.reply_text(
                f"❌ <b>Неверное количество чисел</b>\n\n"
                f"Вы выбрали {len(selected_modules)} модулей, "
                f"но ввели {len(counts)} чисел.\n\n"
                f"Введите ровно {len(selected_modules)} чисел через запятую:",
                parse_mode='HTML'
            )
            return TeacherStates.ENTER_QUESTION_COUNT

        # Проверяем, что все числа > 0
        if any(c <= 0 for c in counts):
            await update.message.reply_text(
                "❌ <b>Все числа должны быть больше нуля</b>\n\n"
                "Попробуйте еще раз:",
                parse_mode='HTML'
            )
            return TeacherStates.ENTER_QUESTION_COUNT

        # Генерируем задания для каждого модуля
        modules_data = []
        total_questions = 0

        module_names = {
            'task19': '💡 Задание 19',
            'task20': '⚙️ Задание 20',
            'task24': '📊 Задание 24',
            'task25': '💻 Задание 25'
        }

        for module_code, count in zip(selected_modules, counts):
            # Загружаем темы для модуля
            topics_data = load_topics_for_module(module_code)
            total_count = topics_data['total_count']

            if count > total_count:
                await update.message.reply_text(
                    f"❌ <b>Слишком много заданий для {module_names[module_code]}</b>\n\n"
                    f"Доступно только {total_count} заданий.\n\n"
                    f"Попробуйте еще раз:",
                    parse_mode='HTML'
                )
                return TeacherStates.ENTER_QUESTION_COUNT

            # Генерируем случайные задания
            all_question_ids = list(topics_data['topics_by_id'].keys())
            if count >= len(all_question_ids):
                selected_ids = all_question_ids
            else:
                selected_ids = random.sample(all_question_ids, count)

            selected_ids.sort()

            # Добавляем данные модуля
            modules_data.append({
                'task_module': module_code,
                'selection_mode': 'all',
                'selected_blocks': [],
                'question_ids': selected_ids,
                'questions_count': len(selected_ids)
            })

            total_questions += len(selected_ids)

        # Сохраняем в assignment_data
        context.user_data['assignment_data'] = {
            'is_mixed': True,
            'modules': modules_data,
            'total_questions_count': total_questions
        }

        # Показываем подтверждение
        text = "🔀 <b>Смешанное задание</b>\n\n"
        text += f"✅ Всего заданий: {total_questions}\n\n"

        for module_data in modules_data:
            module_code = module_data['task_module']
            count = module_data['questions_count']
            text += f"• {module_names[module_code]}: {count} заданий\n"

        text += "\n<i>Подтвердите выбор или введите количества заново</i>"

        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить выбор", callback_data="confirm_mixed_selection")],
            [InlineKeyboardButton("🔄 Ввести заново", callback_data="proceed_mixed_selection")],
            [InlineKeyboardButton("◀️ Назад", callback_data="assign_task_mixed")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return TeacherStates.ENTER_QUESTION_COUNT

    except ValueError:
        await update.message.reply_text(
            "❌ <b>Неверный формат</b>\n\n"
            "Введите целые числа через запятую (например: 5, 3, 2):",
            parse_mode='HTML'
        )
        return TeacherStates.ENTER_QUESTION_COUNT


async def confirm_mixed_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Подтверждение смешанного задания и переход к выбору учеников.
    """
    query = update.callback_query
    await query.answer()

    assignment_data = context.user_data.get('assignment_data')

    if not assignment_data or not assignment_data.get('is_mixed'):
        await query.answer("❌ Ошибка: данные задания не найдены", show_alert=True)
        return TeacherStates.ENTER_QUESTION_COUNT

    # Переходим к выбору учеников
    return await proceed_to_student_selection(update, context)


async def start_custom_question_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Начинает процесс создания кастомного задания.
    """
    query = update.callback_query

    custom_questions = context.user_data.get('custom_questions', [])
    question_count = len(custom_questions)

    text = "📝 <b>Кастомное задание</b>\n\n"

    if question_count == 0:
        text += "Вы можете создать свои собственные вопросы для учеников.\n\n"
        text += "💬 Отправьте текст первого вопроса:"
    else:
        text += f"✅ Добавлено вопросов: {question_count}\n\n"
        text += "💬 Отправьте текст следующего вопроса или завершите создание:"

    keyboard = []

    if question_count > 0:
        keyboard.append([InlineKeyboardButton(f"✅ Завершить ({question_count} вопросов)", callback_data="finish_custom_questions")])
        keyboard.append([InlineKeyboardButton("👀 Просмотреть вопросы", callback_data="review_custom_questions")])

    keyboard.append([InlineKeyboardButton("❌ Отменить", callback_data="teacher_create_assignment")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_CUSTOM_QUESTION


async def process_custom_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обрабатывает ввод текста кастомного вопроса.
    """
    question_text = update.message.text.strip()

    if len(question_text) < 10:
        await update.message.reply_text(
            "❌ <b>Вопрос слишком короткий</b>\n\n"
            "Минимальная длина вопроса: 10 символов.\n"
            "Попробуйте еще раз:",
            parse_mode='HTML'
        )
        return TeacherStates.ENTER_CUSTOM_QUESTION

    if len(question_text) > 2000:
        await update.message.reply_text(
            "❌ <b>Вопрос слишком длинный</b>\n\n"
            "Максимальная длина вопроса: 2000 символов.\n"
            "Попробуйте еще раз:",
            parse_mode='HTML'
        )
        return TeacherStates.ENTER_CUSTOM_QUESTION

    # Добавляем вопрос в список
    custom_questions = context.user_data.get('custom_questions', [])
    question_id = len(custom_questions) + 1

    custom_questions.append({
        'id': question_id,
        'text': question_text
    })

    context.user_data['custom_questions'] = custom_questions

    text = f"✅ <b>Вопрос #{question_id} добавлен!</b>\n\n"
    text += f"<i>{question_text[:100]}{'...' if len(question_text) > 100 else ''}</i>\n\n"
    text += f"📊 Всего вопросов: {len(custom_questions)}\n\n"
    text += "💬 Отправьте следующий вопрос или завершите создание:"

    keyboard = [
        [InlineKeyboardButton(f"✅ Завершить ({len(custom_questions)} вопросов)", callback_data="finish_custom_questions")],
        [InlineKeyboardButton("👀 Просмотреть все вопросы", callback_data="review_custom_questions")],
        [InlineKeyboardButton("❌ Отменить", callback_data="teacher_create_assignment")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_CUSTOM_QUESTION


async def review_custom_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Показывает список всех введенных кастомных вопросов.
    """
    query = update.callback_query
    await query.answer()

    custom_questions = context.user_data.get('custom_questions', [])

    if not custom_questions:
        await query.answer("⚠️ Нет добавленных вопросов", show_alert=True)
        return TeacherStates.ENTER_CUSTOM_QUESTION

    text = f"📝 <b>Кастомное задание</b>\n\n"
    text += f"📊 Всего вопросов: {len(custom_questions)}\n\n"

    for q in custom_questions:
        question_preview = q['text'][:80] + ('...' if len(q['text']) > 80 else '')
        text += f"<b>{q['id']}.</b> {question_preview}\n\n"

    if len(text) > 3900:
        text = text[:3900] + "\n\n<i>(список обрезан)</i>"

    keyboard = [
        [InlineKeyboardButton("➕ Добавить еще вопрос", callback_data="add_more_custom_questions")],
        [InlineKeyboardButton(f"✅ Завершить ({len(custom_questions)} вопросов)", callback_data="finish_custom_questions")],
        [InlineKeyboardButton("🗑️ Удалить последний", callback_data="delete_last_custom_question")],
        [InlineKeyboardButton("❌ Отменить все", callback_data="teacher_create_assignment")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.REVIEW_CUSTOM_QUESTIONS


async def delete_last_custom_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Удаляет последний добавленный вопрос.
    """
    query = update.callback_query
    await query.answer()

    custom_questions = context.user_data.get('custom_questions', [])

    if not custom_questions:
        await query.answer("⚠️ Нет вопросов для удаления", show_alert=True)
        return TeacherStates.REVIEW_CUSTOM_QUESTIONS

    deleted_question = custom_questions.pop()
    context.user_data['custom_questions'] = custom_questions

    await query.answer(f"🗑️ Вопрос #{deleted_question['id']} удален", show_alert=True)

    # Возвращаемся к просмотру
    return await review_custom_questions(update, context)


async def add_more_custom_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Возвращается к добавлению вопросов из режима просмотра.
    """
    query = update.callback_query
    await query.answer()

    return await start_custom_question_entry(update, context)


async def finish_custom_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Завершает создание кастомных вопросов и переходит к выбору учеников.
    """
    query = update.callback_query
    await query.answer()

    custom_questions = context.user_data.get('custom_questions', [])

    if not custom_questions:
        await query.answer("⚠️ Добавьте хотя бы один вопрос", show_alert=True)
        return TeacherStates.ENTER_CUSTOM_QUESTION

    # Сохраняем в assignment_data
    context.user_data['assignment_data'] = {
        'task_module': 'custom',
        'is_custom': True,
        'custom_questions': custom_questions,
        'questions_count': len(custom_questions)
    }

    # Переходим к выбору учеников
    return await proceed_to_student_selection(update, context)


async def show_student_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Показывает детальную статистику конкретного ученика.

    Callback pattern: student_stats:{student_id}
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Извлекаем student_id из callback_data
    student_id = int(query.data.split(':')[1])

    # Получаем статистику
    from ..services import assignment_service, teacher_service

    stats = await assignment_service.get_student_statistics(user_id, student_id)

    if not stats:
        await query.message.edit_text(
            "❌ Ошибка при получении статистики.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="teacher_students")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

    # Получаем имя ученика
    student_names = await teacher_service.get_users_display_names([student_id])
    student_name = student_names.get(student_id, f"ID: {student_id}")

    # Формируем текст статистики
    text = f"📊 <b>Статистика ученика</b>\n\n"
    text += f"👤 <b>Ученик:</b> {student_name}\n\n"

    # Общая статистика
    text += "📈 <b>Общие показатели:</b>\n"
    text += f"• Получено заданий: {stats['total_assignments']}\n"
    text += f"• Завершено заданий: {stats['completed_assignments']}\n"
    text += f"• Всего вопросов: {stats['total_questions']}\n"
    text += f"• Дано ответов: {stats['total_answered']}\n\n"

    if stats['total_answered'] > 0:
        text += f"✅ <b>Правильных ответов:</b> {stats['correct_answers']} ({stats['accuracy_rate']}%)\n"
        text += f"❌ <b>Неправильных ответов:</b> {stats['incorrect_answers']}\n\n"

        # Определяем общий уровень
        accuracy = stats['accuracy_rate']
        if accuracy >= 80:
            level = "🌟 Отличный"
            emoji = "🎉"
        elif accuracy >= 60:
            level = "👍 Хороший"
            emoji = "💪"
        elif accuracy >= 40:
            level = "⚠️ Средний"
            emoji = "📚"
        else:
            level = "❗ Требует внимания"
            emoji = "🔔"

        text += f"{emoji} <b>Уровень:</b> {level}\n\n"

        # Слабые темы
        if stats['weak_modules']:
            text += "📉 <b>Требуют проработки:</b>\n"

            module_names = {
                'task19': '💡 Задание 19',
                'task20': '⚙️ Задание 20',
                'task24': '📊 Задание 24',
                'task25': '💻 Задание 25',
                'custom': '📝 Кастомные',
                'mixed': '🔀 Смешанные'
            }

            for weak in stats['weak_modules']:
                module_display = module_names.get(weak['module'], weak['module'])
                text += f"  • {module_display}: {weak['correct']}/{weak['total']} ({weak['accuracy']:.1f}%)\n"

            text += "\n"

        # Сильные темы
        if stats['strong_modules']:
            text += "📈 <b>Сильные стороны:</b>\n"

            for strong in stats['strong_modules']:
                module_display = module_names.get(strong['module'], strong['module'])
                text += f"  • {module_display}: {strong['correct']}/{strong['total']} ({strong['accuracy']:.1f}%)\n"

            text += "\n"

        # Рекомендации
        text += "💡 <b>Рекомендации:</b>\n"
        if accuracy < 50:
            text += "  • Рекомендуется дополнительная практика\n"
            text += "  • Уделите внимание разбору ошибок\n"
        if stats['weak_modules']:
            text += "  • Сфокусируйтесь на слабых темах\n"
        if stats['completed_assignments'] < stats['total_assignments']:
            text += "  • Завершите все полученные задания\n"
    else:
        text += "ℹ️ Ученик еще не начал выполнять задания.\n"

    keyboard = [
        [InlineKeyboardButton("📋 Домашние задания", callback_data="teacher_my_assignments")],
        [InlineKeyboardButton("◀️ К списку учеников", callback_data="teacher_students")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="teacher_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


async def handle_teacher_subscription_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик оплаты подписки для учителя.
    Перенаправляет на основной обработчик оплаты из payment модуля.

    АРХИТЕКТУРА:
    Эта функция является мостом между teacher ConversationHandler и payment модулем.
    Она позволяет обрабатывать payment flow внутри teacher conversation,
    предотвращая потерю контекста и состояния пользователя.
    """
    query = update.callback_query
    user_id = update.effective_user.id
    callback_data = query.data

    logger.info(f"[Teacher Payment] User {user_id} initiated payment: {callback_data}")

    try:
        from payment.handlers import handle_plan_selection

        # Вызываем основной обработчик оплаты
        result = await handle_plan_selection(update, context)

        logger.info(f"[Teacher Payment] Payment handler returned state: {result}")

        # Возвращаем текущее состояние, чтобы остаться в teacher conversation
        return TeacherStates.TEACHER_MENU

    except Exception as e:
        logger.error(f"[Teacher Payment] Error in payment handler for user {user_id}: {e}", exc_info=True)
        await query.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)
        return TeacherStates.TEACHER_MENU


async def handle_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Универсальный обработчик для payment-related callbacks.
    Перенаправляет на соответствующие обработчики из payment модуля.

    МАРШРУТИЗАЦИЯ:
    - confirm_teacher_plan: → подтверждение выбора тарифа
    - duration_: → выбор длительности подписки (после этого переход к промокоду)
    """
    query = update.callback_query
    callback_data = query.data
    user_id = update.effective_user.id

    logger.info(f"[Teacher Payment] User {user_id} payment callback: {callback_data}")

    try:
        # Импортируем нужные обработчики из payment
        from payment.handlers import (
            handle_teacher_plan_confirmation,
            handle_duration_selection,
            ENTERING_EMAIL
        )

        # Маршрутизируем на соответствующий обработчик
        if callback_data.startswith("confirm_teacher_plan:"):
            result = await handle_teacher_plan_confirmation(update, context)
            logger.info(f"[Teacher Payment] Teacher plan confirmation result: {result}")
            # Если результат - запрос email, переключаемся в состояние ввода email
            if result == ENTERING_EMAIL:
                return TeacherStates.PAYMENT_ENTERING_EMAIL
        elif callback_data.startswith("duration_"):
            result = await handle_duration_selection(update, context)
            logger.info(f"[Teacher Payment] Duration selection result: {result}")
            # После выбора длительности payment модуль переходит к вводу промокода
            # Переключаемся в состояние ввода промокода
            return TeacherStates.PAYMENT_ENTERING_PROMO
        else:
            logger.warning(f"[Teacher Payment] Unknown callback: {callback_data}")
            await query.answer("❌ Неизвестная команда")
            return TeacherStates.TEACHER_MENU

        # По умолчанию возвращаем текущее состояние
        return TeacherStates.TEACHER_MENU

    except Exception as e:
        logger.error(f"[Teacher Payment] Error in payment callback for user {user_id}: {e}", exc_info=True)
        await query.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)
        return TeacherStates.TEACHER_MENU


async def handle_payment_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик ввода email для оплаты подписки.
    Перенаправляет на обработчик из payment модуля.

    ВАЖНО:
    После успешного ввода email payment обработчик показывает экран выбора автопродления.
    Переходим в состояние PAYMENT_AUTO_RENEWAL_CHOICE для обработки выбора.
    """
    user_id = update.effective_user.id
    email = update.message.text

    logger.info(f"[Teacher Payment] User {user_id} entered email: {email}")

    try:
        from payment.handlers import handle_email_input

        # Вызываем обработчик из payment модуля
        # Он показывает экран выбора автопродления (show_auto_renewal_choice)
        result = await handle_email_input(update, context)

        logger.info(f"[Teacher Payment] Email input result: {result}")

        # После ввода email переходим к выбору типа оплаты (автопродление)
        return TeacherStates.PAYMENT_AUTO_RENEWAL_CHOICE

    except Exception as e:
        logger.error(f"[Teacher Payment] Error processing email for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при обработке email. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад в меню учителя", callback_data="teacher_menu")]
            ])
        )
        return ConversationHandler.END





async def handle_auto_renewal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик выбора типа оплаты (с автопродлением или разовая).
    Маршрутизирует все callback_data на соответствующие методы из payment модуля.
    """
    query = update.callback_query
    user_id = update.effective_user.id
    callback_data = query.data

    logger.info(f"[Teacher Payment] User {user_id} auto renewal choice: {callback_data}")

    try:
        from payment.auto_renewal_consent import AutoRenewalConsent
        from payment.subscription_manager import SubscriptionManager

        # ВАЖНО: Переиспользуем ОДИН экземпляр AutoRenewalConsent из bot_data
        # чтобы сохранить состояние user_consents между вызовами
        subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())

        if 'auto_renewal_consent' not in context.bot_data:
            context.bot_data['auto_renewal_consent'] = AutoRenewalConsent(subscription_manager)

        consent_handler = context.bot_data['auto_renewal_consent']

        # МАРШРУТИЗАЦИЯ callback_data на соответствующие методы
        if callback_data in ["choose_auto_renewal", "choose_no_auto_renewal", "show_auto_renewal_terms"]:
            # Основной выбор типа оплаты
            result = await consent_handler.handle_choice_selection(update, context)
            logger.info(f"[Teacher Payment] Choice selection result: {result}")

            # Если выбрано автопродление, остаемся в состоянии для обработки экрана согласия
            if callback_data == "choose_auto_renewal":
                return TeacherStates.PAYMENT_AUTO_RENEWAL_CHOICE
            # Если выбрана разовая оплата или показаны условия, завершаем
            return ConversationHandler.END

        elif callback_data == "toggle_consent_checkbox":
            # Переключение чек-бокса согласия
            result = await consent_handler.toggle_consent(update, context)
            logger.info(f"[Teacher Payment] Toggle consent result: {result}")
            return TeacherStates.PAYMENT_AUTO_RENEWAL_CHOICE  # Остаемся в этом состоянии

        elif callback_data == "confirm_with_auto_renewal":
            # Подтверждение с автопродлением
            result = await consent_handler.confirm_with_auto_renewal(update, context)
            logger.info(f"[Teacher Payment] Confirm with auto renewal result: {result}")
            # После подтверждения завершаем conversation (платеж будет создан)
            return ConversationHandler.END

        elif callback_data == "need_consent_reminder":
            # Показываем напоминание о необходимости согласия
            await query.answer("⚠️ Необходимо отметить согласие с условиями", show_alert=True)
            return TeacherStates.PAYMENT_AUTO_RENEWAL_CHOICE

        elif callback_data == "show_user_agreement":
            # Показываем подробные условия
            result = await consent_handler.show_detailed_terms(update, context)
            logger.info(f"[Teacher Payment] Show detailed terms result: {result}")
            return TeacherStates.PAYMENT_AUTO_RENEWAL_CHOICE

        elif callback_data == "back_to_payment_choice":
            # Возврат к выбору типа оплаты
            result = await consent_handler.handle_back_navigation(update, context)
            logger.info(f"[Teacher Payment] Back navigation result: {result}")
            return TeacherStates.PAYMENT_AUTO_RENEWAL_CHOICE

        else:
            logger.warning(f"[Teacher Payment] Unknown callback: {callback_data}")
            await query.answer("❌ Неизвестная команда")
            return TeacherStates.TEACHER_MENU

    except Exception as e:
        logger.error(f"[Teacher Payment] Error in auto renewal choice for user {user_id}: {e}", exc_info=True)
        await query.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)
        return ConversationHandler.END


async def handle_back_to_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик возврата к выбору длительности подписки.
    Перенаправляет на обработчик из payment модуля.
    """
    query = update.callback_query
    user_id = update.effective_user.id

    logger.info(f"[Teacher Payment] User {user_id} going back to duration selection")

    try:
        from payment.handlers import show_duration_options

        # Вызываем показ экрана выбора длительности
        result = await show_duration_options(update, context)

        logger.info(f"[Teacher Payment] Back to duration result: {result}")

        # Возвращаемся в TEACHER_MENU (так как мы вернулись на шаг назад)
        return TeacherStates.TEACHER_MENU

    except Exception as e:
        logger.error(f"[Teacher Payment] Error going back to duration for user {user_id}: {e}", exc_info=True)
        await query.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)
        return TeacherStates.TEACHER_MENU


async def handle_skip_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик пропуска промокода.
    Перенаправляет на обработчик из payment модуля и переходит к вводу email.
    """
    query = update.callback_query
    user_id = update.effective_user.id

    logger.info(f"[Teacher Payment] User {user_id} skipped promo code")

    try:
        from payment.promo_handler import skip_promo

        # Вызываем обработчик пропуска промокода из payment модуля
        result = await skip_promo(update, context)

        logger.info(f"[Teacher Payment] Skip promo result: {result}")

        # После пропуска промокода переходим к вводу email
        return TeacherStates.PAYMENT_ENTERING_EMAIL

    except Exception as e:
        logger.error(f"[Teacher Payment] Error skipping promo for user {user_id}: {e}", exc_info=True)
        await query.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)
        return TeacherStates.TEACHER_MENU


async def handle_promo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик ввода промокода.
    Перенаправляет на обработчик из payment модуля.
    """
    user_id = update.effective_user.id
    promo_code = update.message.text

    logger.info(f"[Teacher Payment] User {user_id} entered promo code: {promo_code}")

    try:
        from payment.promo_handler import handle_promo_input as payment_handle_promo

        # Вызываем обработчик из payment модуля
        result = await payment_handle_promo(update, context)

        logger.info(f"[Teacher Payment] Promo input result: {result}")

        # После обработки промокода переходим к вводу email
        return TeacherStates.PAYMENT_ENTERING_EMAIL

    except Exception as e:
        logger.error(f"[Teacher Payment] Error processing promo for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при обработке промокода. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад в меню учителя", callback_data="teacher_menu")]
            ])
        )
        return ConversationHandler.END


async def handle_check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик проверки статуса платежа.
    Перенаправляет на обработчик из payment модуля.
    """
    query = update.callback_query
    user_id = update.effective_user.id

    logger.info(f"[Teacher Payment] User {user_id} checking payment status")

    try:
        from payment.handlers import check_payment_status

        # Вызываем обработчик из payment модуля
        await check_payment_status(update, context)

        logger.info(f"[Teacher Payment] Payment check completed for user {user_id}")

        # Завершаем conversation после проверки
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"[Teacher Payment] Error checking payment for user {user_id}: {e}", exc_info=True)
        await query.answer("❌ Произошла ошибка при проверке платежа.", show_alert=True)
        return ConversationHandler.END


async def handle_cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик отмены платежа.
    Перенаправляет на обработчик из payment модуля.
    """
    query = update.callback_query
    user_id = update.effective_user.id

    logger.info(f"[Teacher Payment] User {user_id} cancelling payment")

    try:
        from payment.handlers import cancel_payment

        # Вызываем обработчик из payment модуля
        await cancel_payment(update, context)

        logger.info(f"[Teacher Payment] Payment cancelled for user {user_id}")

        # Возвращаемся в меню учителя
        return TeacherStates.TEACHER_MENU

    except Exception as e:
        logger.error(f"[Teacher Payment] Error cancelling payment for user {user_id}: {e}", exc_info=True)
        if query:
            await query.answer("❌ Произошла ошибка при отмене.", show_alert=True)
        return TeacherStates.TEACHER_MENU
