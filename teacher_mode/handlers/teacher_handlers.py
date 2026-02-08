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
from telegram import WebAppInfo

from ..states import TeacherStates
from ..services import teacher_service
from ..utils.rate_limiter import check_operation_limit
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

            # ИСПРАВЛЕНО: Создаем профиль учителя для администратора с полным доступом
            # Профиль автоматически получит активную подписку на 100 лет для teacher_free
            # Для teacher_premium нужно вручную установить подписку
            import aiosqlite
            from datetime import datetime, timedelta
            from core.config import DATABASE_FILE

            # ИСПРАВЛЕНО: Используем ОДНО соединение для всех операций
            async with aiosqlite.connect(DATABASE_FILE, timeout=30.0) as db:
                # Начинаем эксклюзивную транзакцию
                await db.execute("BEGIN EXCLUSIVE")

                try:
                    # Создаем профиль учителя, передавая соединение
                    # Это предотвращает создание второго соединения и database lock
                    profile = await teacher_service.create_teacher_profile(
                        user_id=user_id,
                        display_name=display_name,
                        subscription_tier='teacher_premium',
                        db_connection=db  # ИСПРАВЛЕНО: Передаем существующее соединение
                    )

                    # Устанавливаем бессрочную активную подписку для админа (10 лет)
                    # Для teacher_premium это необходимо, так как по умолчанию подписка неактивна
                    if profile:
                        expires = utc_now() + timedelta(days=3650)
                        await db.execute("""
                            UPDATE teacher_profiles
                            SET has_active_subscription = 1,
                                subscription_expires = ?
                            WHERE user_id = ?
                        """, (expires, user_id))

                    await db.commit()
                    logger.info(f"Автоматически создан профиль учителя для администратора {user_id}")

                except Exception as e:
                    await db.rollback()
                    logger.error(f"Ошибка создания профиля учителя для администратора: {e}")
                    raise

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
    from core.config import WEBAPP_URL

    keyboard = [
        [InlineKeyboardButton("👥 Мои ученики", callback_data="teacher_students")],
        [InlineKeyboardButton("📋 Мои задания", callback_data="teacher_my_assignments")],
        [
            InlineKeyboardButton("➕ Создать задание", callback_data="teacher_create_assignment"),
            InlineKeyboardButton("🚀 Создать задание (WebApp)", web_app=WebAppInfo(url=WEBAPP_URL))
        ],
        [InlineKeyboardButton("📊 Статистика", callback_data="teacher_statistics")],
        [InlineKeyboardButton("🔍 Проверить работу", callback_data="quick_check_menu")],
    ]

    # Кнопка "Подарить подписку" доступна только для Premium-учителей
    if is_admin:
        # Админы имеют полный доступ
        keyboard.append([InlineKeyboardButton("🎁 Подарить подписку", callback_data="teacher_gift_menu")])
    else:
        # Для обычных учителей проверяем тариф
        profile = await teacher_service.get_teacher_profile(user_id)
        if profile and profile.subscription_tier == 'teacher_premium':
            keyboard.append([InlineKeyboardButton("🎁 Подарить подписку", callback_data="teacher_gift_menu")])

    keyboard.extend([
        [InlineKeyboardButton("👤 Мой профиль", callback_data="teacher_profile")],
        [InlineKeyboardButton("◀️ Назад в главное меню", callback_data="main_menu")],
    ])
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
        'teacher_free': '🆓 Бесплатный',
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

    # Добавляем предупреждение для teacher_free если достигнут лимит
    if profile.subscription_tier == 'teacher_free' and student_count >= max_students:
        text += (
            "\n\n"
            "⚠️ <b>Достигнут лимит учеников</b>\n\n"
            "💡 Обновите тариф, чтобы подключить больше учеников и получить "
            "доступ к расширенным функциям!"
        )

    keyboard = [
        [InlineKeyboardButton("📋 Список учеников", callback_data="teacher_students")]
    ]

    # Добавляем кнопку обновления тарифа для teacher_free
    if profile.subscription_tier == 'teacher_free':
        keyboard.insert(0, [InlineKeyboardButton("💎 Обновить тариф", callback_data="teacher_subscriptions")])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.TEACHER_MENU


async def show_teacher_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать доступные подписки для учителей"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    teacher_plans = get_all_teacher_plans(user_id)

    # Проверяем, использовал ли пользователь пробный период
    subscription_manager = context.bot_data.get('subscription_manager')
    if not subscription_manager:
        from payment.subscription_manager import SubscriptionManager
        subscription_manager = SubscriptionManager()

    has_used_trial = await subscription_manager.has_used_teacher_trial(user_id)

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

    # Показываем пробный период первым, если он еще не использован
    if not has_used_trial:
        keyboard.append([
            InlineKeyboardButton(
                "🎁 Пробный период — 1₽ (до 3 учеников, 7 дней)",
                callback_data="buy_teacher_teacher_trial_7days"
            )
        ])

    # Показываем остальные планы (кроме триала)
    for plan in teacher_plans:
        plan_id = plan['plan_id']

        # Пропускаем пробный период, так как уже показали его выше
        if plan_id == 'teacher_trial_7days':
            continue

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

    # Для триального периода показываем срок в днях, для остальных - в месяцах
    if plan_id == 'teacher_trial_7days':
        text += f"💰 <b>Цена:</b> {plan['price_rub']}₽ за {plan['duration_days']} дней\n\n"
    else:
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
        [InlineKeyboardButton("💳 Оформить подписку", callback_data=f"pay_teacher_{plan_id}")],
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
        [InlineKeyboardButton("🎯 Полный вариант ЕГЭ", callback_data="assign_task_full_exam")],
        [InlineKeyboardButton("📝 Тестовая часть (1-16)", callback_data="assign_task_test_part")],
        [InlineKeyboardButton("💡 Задание 19", callback_data="assign_task_task19")],
        [InlineKeyboardButton("⚙️ Задание 20", callback_data="assign_task_task20")],
        [InlineKeyboardButton("📊 Задание 21", callback_data="assign_task_task21")],
        [InlineKeyboardButton("📝 Задание 22", callback_data="assign_task_task22")],
        [InlineKeyboardButton("📜 Задание 23", callback_data="assign_task_task23")],
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

    # Обрабатываем полный вариант ЕГЭ отдельно
    if task_type == "full_exam":
        context.user_data['assignment_task_type'] = 'full_exam'
        return await create_full_exam_variant(update, context)

    # Сохраняем выбранный тип задания
    context.user_data['assignment_task_type'] = task_type

    # Очищаем все данные предыдущего выбора
    context.user_data['selected_blocks'] = []
    context.user_data['selected_topic_ids'] = []
    context.user_data['selected_exam_numbers'] = []
    context.user_data['selected_question_ids'] = []
    context.user_data['available_question_ids'] = []

    task_names = {
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
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


async def create_full_exam_variant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Создание полного варианта ЕГЭ (20 заданий)"""
    import random
    from ..services.topics_loader import load_topics_for_module

    query = update.callback_query

    # Показываем сообщение о создании
    await query.message.edit_text(
        "🎯 <b>Создание полного варианта ЕГЭ</b>\n\n"
        "⏳ Генерирую задания...",
        parse_mode='HTML'
    )

    try:
        # Структура для хранения всех заданий
        full_exam_questions = []

        # 1. Генерируем тестовую часть (1-16)
        test_part_data = load_topics_for_module('test_part')
        all_test_questions = test_part_data.get('questions', [])

        # Группируем вопросы по номерам экзамена
        questions_by_exam_num = {}
        for q in all_test_questions:
            exam_num = q.get('exam_number')
            if exam_num and 1 <= exam_num <= 16:
                if exam_num not in questions_by_exam_num:
                    questions_by_exam_num[exam_num] = []
                questions_by_exam_num[exam_num].append(q)

        # Выбираем по одному случайному вопросу для каждого номера 1-16
        test_part_questions = []
        for exam_num in range(1, 17):
            if exam_num in questions_by_exam_num and questions_by_exam_num[exam_num]:
                selected_q = random.choice(questions_by_exam_num[exam_num])
                test_part_questions.append({
                    'module': 'test_part',
                    'question_id': selected_q['id'],
                    'exam_number': exam_num,
                    'title': selected_q.get('title', f'Задание {exam_num}')
                })

        full_exam_questions.extend(test_part_questions)

        # 2. Генерируем задания 19, 20, 24, 25 (по 1 заданию каждое)
        advanced_modules = ['task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25']
        module_names = {
            'task19': '💡 Задание 19',
            'task20': '⚙️ Задание 20',
            'task21': '📊 Задание 21',
            'task22': '📝 Задание 22',
            'task23': '📜 Задание 23',
            'task24': '📊 Задание 24',
            'task25': '💻 Задание 25'
        }

        for module in advanced_modules:
            module_data = load_topics_for_module(module)
            all_questions_ids = list(module_data['topics_by_id'].keys())

            if all_questions_ids:
                selected_id = random.choice(all_questions_ids)
                topic = module_data['topics_by_id'].get(selected_id)
                full_exam_questions.append({
                    'module': module,
                    'question_id': selected_id,
                    'title': topic.get('title', f'{module_names[module]}') if topic else module_names[module]
                })

        # Сохраняем в assignment_data
        context.user_data['assignment_data'] = {
            'task_module': 'full_exam',
            'selection_mode': 'full_exam',
            'full_exam_questions': full_exam_questions,
            'questions_count': len(full_exam_questions)
        }

        # Формируем сообщение с подтверждением
        text = (
            "🎯 <b>Полный вариант ЕГЭ сгенерирован</b>\n\n"
            f"✅ Всего заданий: {len(full_exam_questions)}\n\n"
            "<b>Состав варианта:</b>\n"
            f"📝 Тестовая часть (1-16): {len(test_part_questions)} заданий\n"
            f"💡 Задание 19: 1 задание\n"
            f"⚙️ Задание 20: 1 задание\n"
            f"📊 Задание 21: 1 задание\n"
            f"📝 Задание 22: 1 задание\n"
            f"📜 Задание 23: 1 задание\n"
            f"📊 Задание 24: 1 задание\n"
            f"💻 Задание 25: 1 задание\n\n"
            "<i>Нажмите 'Продолжить' для выбора студентов</i>"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Продолжить", callback_data="confirm_full_exam")],
            [InlineKeyboardButton("🔄 Генерировать заново", callback_data="regenerate_full_exam")],
            [InlineKeyboardButton("◀️ Отмена", callback_data="teacher_create_assignment")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return TeacherStates.SELECT_SELECTION_MODE

    except Exception as e:
        await query.message.edit_text(
            f"❌ <b>Ошибка при создании варианта</b>\n\n"
            f"Произошла ошибка: {str(e)}\n\n"
            "Попробуйте снова или выберите другой тип задания.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="teacher_create_assignment")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.CREATE_ASSIGNMENT


async def regenerate_full_exam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Перегенерирует полный вариант ЕГЭ"""
    query = update.callback_query
    await query.answer()

    # Просто вызываем создание заново
    return await create_full_exam_variant(update, context)


async def confirm_full_exam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение полного варианта ЕГЭ и переход к выбору студентов"""
    query = update.callback_query
    await query.answer()

    # Переходим к выбору студентов
    return await proceed_to_student_selection(update, context)


async def select_selection_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора способа отбора заданий"""
    query = update.callback_query
    await query.answer()

    mode = query.data.replace("selection_mode_", "")
    task_type = context.user_data.get('assignment_task_type')

    # Сохраняем выбранный режим
    context.user_data['selection_mode'] = mode

    task_names = {
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
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
        # Очищаем данные предыдущего выбора тем
        context.user_data['selected_blocks'] = []
        context.user_data['selected_topic_ids'] = []
        context.user_data['selected_exam_numbers'] = []
        context.user_data['selected_question_ids'] = []
        context.user_data['available_question_ids'] = []
        return await show_topic_blocks_selection(update, context)

    elif mode == "numbers":
        # Режим "Конкретные номера" - показываем выбор способа ввода
        await query.message.edit_text(
            f"🔢 <b>{task_name}: Выбор конкретных заданий</b>\n\n"
            "Выберите способ отбора заданий:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Выбрать из списка", callback_data=f"numbers_browser_{task_type}")],
                [InlineKeyboardButton("✏️ Ввести вручную", callback_data=f"numbers_manual_{task_type}")],
                [InlineKeyboardButton("◀️ Назад", callback_data=f"assign_task_{task_type}")]
            ]),
            parse_mode='HTML'
        )
        return TeacherStates.ENTER_QUESTION_NUMBERS

    return TeacherStates.CREATE_ASSIGNMENT


async def show_manual_numbers_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает инструкцию для ручного ввода номеров заданий"""
    query = update.callback_query
    await query.answer()

    task_type = query.data.replace("numbers_manual_", "")
    context.user_data['assignment_task_type'] = task_type

    from ..services.topics_loader import load_topics_for_module

    topics_data = load_topics_for_module(task_type)
    total_count = topics_data['total_count']

    task_names = {
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    # Для test_part показываем выбор по номерам ЕГЭ (1-16)
    if task_type == 'test_part':
        await query.message.edit_text(
            f"✏️ <b>{task_name}: Ввод номеров вручную</b>\n\n"
            f"📚 Доступны задания: 1-16 (тестовая часть)\n"
            f"📊 Всего вопросов в базе: {total_count}\n\n"
            "Введите номера заданий ЕГЭ одним сообщением:\n\n"
            "<b>Примеры форматов:</b>\n"
            "• Отдельные номера: <code>1,5,10</code>\n"
            "• Диапазоны: <code>1-5,10-13</code>\n"
            "• Комбинированно: <code>1,3,5-10,15</code>\n\n"
            "💡 Можно использовать пробелы для читаемости",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="selection_mode_numbers")
            ]]),
            parse_mode='HTML'
        )
    else:
        # Для остальных модулей показываем выбор по ID из банка тем
        await query.message.edit_text(
            f"✏️ <b>{task_name}: Ввод номеров вручную</b>\n\n"
            f"📚 В банке доступно: {total_count} заданий (ID: 1-{total_count})\n\n"
            "Введите ID заданий одним сообщением:\n\n"
            "<b>Примеры форматов:</b>\n"
            "• Отдельные номера: <code>1,5,10,23</code>\n"
            "• Диапазоны: <code>1-5,10-15,20</code>\n"
            "• Комбинированно: <code>1,3,5-10,15,20-25</code>\n\n"
            "💡 Можно использовать пробелы для читаемости",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="selection_mode_numbers")
            ]]),
            parse_mode='HTML'
        )
    return TeacherStates.ENTER_QUESTION_NUMBERS


async def show_question_browser(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> int:
    """Показывает браузер заданий с возможностью выбора"""
    query = update.callback_query
    await query.answer()

    # Извлекаем task_type из callback_data или из контекста
    if query.data.startswith("numbers_browser_"):
        task_type = query.data.replace("numbers_browser_", "")
        context.user_data['assignment_task_type'] = task_type
        # Инициализируем список выбранных заданий ТОЛЬКО если его еще нет
        # Это позволяет сохранить выбор при возврате из подтверждения
        if 'browser_selected_ids' not in context.user_data:
            context.user_data['browser_selected_ids'] = []
            context.user_data['browser_page'] = 0
            context.user_data['browser_search_query'] = None
        # При возврате из подтверждения восстанавливаем выбор из selected_question_ids
        elif 'selected_question_ids' in context.user_data:
            context.user_data['browser_selected_ids'] = context.user_data['selected_question_ids']
    else:
        task_type = context.user_data.get('assignment_task_type')

    from ..services.topics_loader import load_topics_for_module

    topics_data = load_topics_for_module(task_type)
    all_questions = list(topics_data['topics_by_id'].items())

    # Применяем поиск если есть
    search_query = context.user_data.get('browser_search_query')
    if search_query:
        filtered_questions = []
        for q_id, q_data in all_questions:
            title = q_data.get('title', '').lower()
            if search_query.lower() in title:
                filtered_questions.append((q_id, q_data))
        all_questions = filtered_questions

    task_names = {
        'test_part': '📝 Тестовая часть',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    # Получаем текущую страницу
    page = context.user_data.get('browser_page', 0)
    items_per_page = 5
    total_pages = (len(all_questions) + items_per_page - 1) // items_per_page

    # Ограничиваем страницу
    page = max(0, min(page, total_pages - 1)) if total_pages > 0 else 0
    context.user_data['browser_page'] = page

    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_questions = all_questions[start_idx:end_idx]

    # Получаем список выбранных ID
    selected_ids = set(context.user_data.get('browser_selected_ids', []))

    # Формируем текст
    text = f"📋 <b>{task_name}: Выбор заданий</b>\n\n"
    text += f"✅ Выбрано: {len(selected_ids)} заданий\n"

    if search_query:
        text += f"🔍 Поиск: <code>{search_query}</code>\n"
        text += f"📊 Найдено: {len(all_questions)} заданий\n\n"
    else:
        text += f"📊 Всего: {len(all_questions)} заданий\n\n"

    text += f"<b>Страница {page + 1} из {total_pages}</b>\n\n"

    if not page_questions:
        text += "<i>Ничего не найдено</i>\n\n"

    # Формируем клавиатуру
    keyboard = []

    for q_id, q_data in page_questions:
        title = q_data.get('title', f'Вопрос {q_id}')
        # Обрезаем длинные названия
        if len(title) > 50:
            title = title[:47] + "..."

        # Показываем статус выбора
        if q_id in selected_ids:
            emoji = "✅"
        else:
            emoji = "⬜"

        button_text = f"{emoji} №{q_id}: {title}"
        keyboard.append([
            InlineKeyboardButton(button_text, callback_data=f"browser_toggle_{q_id}")
        ])

    # Навигация
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data="browser_prev_page"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️ Далее", callback_data="browser_next_page"))
    if nav_row:
        keyboard.append(nav_row)

    # Дополнительные кнопки
    keyboard.append([
        InlineKeyboardButton("🔍 Поиск", callback_data="browser_search"),
        InlineKeyboardButton("🔄 Сбросить поиск", callback_data="browser_clear_search") if search_query else InlineKeyboardButton("📝 Ввести вручную", callback_data=f"numbers_manual_{task_type}")
    ])

    keyboard.append([
        InlineKeyboardButton(f"✅ Подтвердить ({len(selected_ids)})", callback_data="browser_confirm") if selected_ids else InlineKeyboardButton("◀️ Назад", callback_data="selection_mode_numbers")
    ])

    if selected_ids:
        keyboard.append([
            InlineKeyboardButton("◀️ Назад", callback_data="selection_mode_numbers")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_QUESTION_NUMBERS


async def toggle_question_browser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Добавляет или удаляет вопрос из выбранных"""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID вопроса
    question_id = int(query.data.replace("browser_toggle_", ""))

    # Получаем список выбранных ID
    selected_ids = context.user_data.get('browser_selected_ids', [])

    # Toggle: если есть - удаляем, если нет - добавляем
    if question_id in selected_ids:
        selected_ids.remove(question_id)
    else:
        selected_ids.append(question_id)

    context.user_data['browser_selected_ids'] = selected_ids

    # Обновляем отображение
    return await show_question_browser(update, context)


async def navigate_question_browser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Навигация по страницам браузера"""
    query = update.callback_query
    await query.answer()

    current_page = context.user_data.get('browser_page', 0)

    if query.data == "browser_next_page":
        context.user_data['browser_page'] = current_page + 1
    elif query.data == "browser_prev_page":
        context.user_data['browser_page'] = max(0, current_page - 1)

    return await show_question_browser(update, context)


async def start_browser_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрашивает поисковый запрос"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type')

    task_names = {
        'test_part': '📝 Тестовая часть',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    await query.message.edit_text(
        f"🔍 <b>{task_name}: Поиск заданий</b>\n\n"
        "Введите ключевое слово или фразу для поиска в названиях заданий:\n\n"
        "<i>Например: алгоритм, база данных, функция</i>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Назад", callback_data="browser_cancel_search")
        ]]),
        parse_mode='HTML'
    )

    return TeacherStates.BROWSER_SEARCH


async def process_browser_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает поисковый запрос"""
    search_query = update.message.text.strip()

    if not search_query:
        await update.message.reply_text(
            "❌ Поисковый запрос не может быть пустым. Попробуйте еще раз:",
            parse_mode='HTML'
        )
        return TeacherStates.BROWSER_SEARCH

    # Сохраняем запрос и сбрасываем страницу
    context.user_data['browser_search_query'] = search_query
    context.user_data['browser_page'] = 0

    # Загружаем данные и генерируем браузер вручную
    task_type = context.user_data.get('assignment_task_type')

    from ..services.topics_loader import load_topics_for_module

    topics_data = load_topics_for_module(task_type)
    all_questions = list(topics_data['topics_by_id'].items())

    # Применяем поиск
    filtered_questions = []
    for q_id, q_data in all_questions:
        title = q_data.get('title', '').lower()
        if search_query.lower() in title:
            filtered_questions.append((q_id, q_data))

    task_names = {
        'test_part': '📝 Тестовая часть',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    # Получаем список выбранных ID
    selected_ids = set(context.user_data.get('browser_selected_ids', []))

    # Пагинация
    page = 0
    items_per_page = 5
    total_pages = (len(filtered_questions) + items_per_page - 1) // items_per_page if filtered_questions else 1
    page_questions = filtered_questions[0:items_per_page]

    # Формируем текст
    text = f"📋 <b>{task_name}: Выбор заданий</b>\n\n"
    text += f"✅ Выбрано: {len(selected_ids)} заданий\n"
    text += f"🔍 Поиск: <code>{search_query}</code>\n"
    text += f"📊 Найдено: {len(filtered_questions)} заданий\n\n"
    text += f"<b>Страница 1 из {total_pages}</b>\n\n"

    if not page_questions:
        text += "<i>Ничего не найдено</i>\n\n"

    # Формируем клавиатуру
    keyboard = []

    for q_id, q_data in page_questions:
        title = q_data.get('title', f'Вопрос {q_id}')
        if len(title) > 50:
            title = title[:47] + "..."

        emoji = "✅" if q_id in selected_ids else "⬜"
        button_text = f"{emoji} №{q_id}: {title}"
        keyboard.append([
            InlineKeyboardButton(button_text, callback_data=f"browser_toggle_{q_id}")
        ])

    # Навигация
    if total_pages > 1:
        nav_row = []
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️ Далее", callback_data="browser_next_page"))
        if nav_row:
            keyboard.append(nav_row)

    # Дополнительные кнопки
    keyboard.append([
        InlineKeyboardButton("🔍 Новый поиск", callback_data="browser_search"),
        InlineKeyboardButton("🔄 Сбросить поиск", callback_data="browser_clear_search")
    ])

    keyboard.append([
        InlineKeyboardButton(f"✅ Подтвердить ({len(selected_ids)})", callback_data="browser_confirm") if selected_ids else InlineKeyboardButton("◀️ Назад", callback_data="selection_mode_numbers")
    ])

    if selected_ids:
        keyboard.append([
            InlineKeyboardButton("◀️ Назад", callback_data="selection_mode_numbers")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем новое сообщение с результатами поиска
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_QUESTION_NUMBERS


async def clear_browser_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сбрасывает поисковый запрос"""
    query = update.callback_query
    await query.answer()

    context.user_data['browser_search_query'] = None
    context.user_data['browser_page'] = 0

    return await show_question_browser(update, context)


async def cancel_browser_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет ввод поискового запроса"""
    query = update.callback_query
    await query.answer()

    return await show_question_browser(update, context)


async def confirm_browser_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждает выбор заданий из браузера"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type')
    selected_ids = context.user_data.get('browser_selected_ids', [])

    if not selected_ids:
        await query.answer("⚠️ Не выбрано ни одного задания", show_alert=True)
        return TeacherStates.ENTER_QUESTION_NUMBERS

    # Сохраняем выбранные ID для дальнейшей обработки
    context.user_data['selected_question_ids'] = sorted(selected_ids)
    context.user_data['selected_blocks'] = []

    # Загружаем данные для отображения
    from ..services.topics_loader import load_topics_for_module
    topics_data = load_topics_for_module(task_type)

    # Показываем подтверждение (используем существующую функцию)
    return await show_numbers_confirmation_from_browser(update, context, sorted(selected_ids), task_type, topics_data)


async def show_numbers_confirmation_from_browser(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                                  question_ids: List[int], task_type: str,
                                                  topics_data: Dict) -> int:
    """Показать список заданий выбранных через браузер для финального подтверждения"""

    task_names = {
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25',
        'test_part': '📝 Тестовая часть'
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

    text += "\n<i>Подтвердите выбор или вернитесь к браузеру</i>"

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить выбор", callback_data="confirm_numbers_selection")],
        [InlineKeyboardButton("◀️ К браузеру", callback_data=f"numbers_browser_{task_type}")],
        [InlineKeyboardButton("❌ Отмена", callback_data="selection_mode_numbers")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Обновляем сообщение
    query = update.callback_query
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_QUESTION_NUMBERS


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
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    try:
        # Парсим введенные номера
        entered_numbers = parse_question_numbers(user_input)

        if not entered_numbers:
            await update.message.reply_text(
                "❌ Не удалось распознать номера заданий.\n\n"
                "Попробуйте еще раз, например: <code>1,5,10-15</code>",
                parse_mode='HTML'
            )
            return TeacherStates.ENTER_QUESTION_NUMBERS

        # Для test_part обрабатываем номера ЕГЭ (1-16)
        if task_type == 'test_part':
            # Проверяем диапазон 1-16
            invalid_nums = [n for n in entered_numbers if n < 1 or n > 16]

            if invalid_nums:
                await update.message.reply_text(
                    f"❌ Некоторые номера вне допустимого диапазона:\n"
                    f"<code>{', '.join(map(str, invalid_nums[:10]))}</code>\n\n"
                    f"Для тестовой части доступны номера: 1-16\n\n"
                    "Попробуйте еще раз:",
                    parse_mode='HTML'
                )
                return TeacherStates.ENTER_QUESTION_NUMBERS

            # Загружаем все вопросы и фильтруем по exam_number
            from test_part.loader import get_questions_list_flat

            all_questions = get_questions_list_flat()
            if not all_questions:
                await update.message.reply_text(
                    "❌ Ошибка загрузки вопросов. Попробуйте позже.",
                    parse_mode='HTML'
                )
                return TeacherStates.ENTER_QUESTION_NUMBERS

            # Собираем все ID вопросов для выбранных номеров ЕГЭ
            question_ids_by_exam = {}
            for exam_num in entered_numbers:
                matching_questions = [q for q in all_questions if q.get('exam_number') == exam_num]
                question_ids_by_exam[exam_num] = [q['id'] for q in matching_questions]

            # Сохраняем данные для подтверждения
            context.user_data['selected_exam_numbers'] = entered_numbers
            context.user_data['question_ids_by_exam'] = question_ids_by_exam
            context.user_data['selected_blocks'] = []

            # Показываем подтверждение
            return await show_exam_numbers_confirmation(update, context, entered_numbers, question_ids_by_exam)

        else:
            # Для остальных модулей работаем с ID тем как раньше
            from ..services.topics_loader import load_topics_for_module

            topics_data = load_topics_for_module(task_type)
            valid_ids = set(topics_data['topics_by_id'].keys())

            invalid_ids = [qid for qid in entered_numbers if qid not in valid_ids]

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
            context.user_data['selected_question_ids'] = entered_numbers
            context.user_data['selected_blocks'] = []  # Для режима "номера" блоки не используются

            # Показываем список заданий для подтверждения
            return await show_numbers_confirmation(update, context, entered_numbers, task_type, topics_data)

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
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
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


async def show_exam_numbers_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                         exam_numbers: List[int], question_ids_by_exam: Dict) -> int:
    """Показать подтверждение выбранных номеров ЕГЭ для test_part"""

    # Подсчитываем общее количество вопросов
    total_questions = sum(len(qids) for qids in question_ids_by_exam.values())

    text = (
        f"📝 <b>Тестовая часть: Подтверждение заданий</b>\n\n"
        f"✅ Выбрано номеров ЕГЭ: {len(exam_numbers)}\n"
        f"📊 Всего вопросов в базе: {total_questions}\n\n"
        "Список выбранных заданий:\n\n"
    )

    # Добавляем информацию о каждом номере
    for exam_num in sorted(exam_numbers):
        question_count = len(question_ids_by_exam.get(exam_num, []))
        text += f"• <b>Задание {exam_num}</b> — {question_count} вопросов\n"

    text += "\n<i>Подтвердите выбор или введите номера заново</i>"

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить выбор", callback_data="confirm_exam_numbers_selection")],
        [InlineKeyboardButton("🔄 Ввести заново", callback_data="assign_task_test_part:numbers")],
        [InlineKeyboardButton("◀️ Назад", callback_data="assign_task_test_part")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем новое сообщение
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_QUESTION_NUMBERS


async def confirm_exam_numbers_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение выбранных номеров ЕГЭ для test_part"""
    query = update.callback_query
    await query.answer()

    question_ids_by_exam = context.user_data.get('question_ids_by_exam', {})

    if not question_ids_by_exam:
        await query.answer("⚠️ Список заданий пуст", show_alert=True)
        return TeacherStates.ENTER_QUESTION_NUMBERS

    # Собираем все question_ids из всех номеров экзамена
    all_question_ids = []
    for exam_num in sorted(question_ids_by_exam.keys()):
        all_question_ids.extend(question_ids_by_exam[exam_num])

    # Сохраняем в assignment_data
    context.user_data['assignment_data'] = {
        'task_module': 'test_part',
        'selection_mode': 'exam_numbers',
        'selected_blocks': [],
        'question_ids': all_question_ids,
        'questions_count': len(all_question_ids),
        'exam_numbers': list(question_ids_by_exam.keys())
    }

    # Переходим к выбору учеников
    return await proceed_to_student_selection(update, context)


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
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
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
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
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

    # Список выбранных блоков уже инициализирован в select_selection_mode
    # Но на всякий случай проверяем
    if 'selected_blocks' not in context.user_data:
        context.user_data['selected_blocks'] = []

    task_names = {
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    text = (
        f"📚 <b>{task_name}: Выбор тем</b>\n\n"
        "Выберите блоки тем из кодификатора ЕГЭ:\n"
        "(можно выбрать несколько)\n\n"
    )

    # Убрали дублирующуюся статистику - она уже показывается на кнопках

    keyboard = []

    # Создаем кнопки для каждого блока
    for block_name in sorted(blocks.keys()):
        selected = block_name in context.user_data['selected_blocks']
        # Используем 📂 вместо чекбокса, чтобы не создавать впечатление выбора всех тем
        prefix = "📂 " if selected else "📁 "
        topic_count = len(blocks[block_name])

        keyboard.append([
            InlineKeyboardButton(
                f"{prefix}{block_name} ({topic_count} тем)",
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
    """Подтверждение выбора блоков тем и переход к выбору конкретных тем"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type')
    selected_blocks = context.user_data.get('selected_blocks', [])

    if not selected_blocks:
        await query.answer("⚠️ Выберите хотя бы один блок", show_alert=True)
        return TeacherStates.SELECT_TOPICS

    # Переходим к выбору конкретных тем из этих блоков
    return await show_topics_selection(update, context)


async def show_topics_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать выбор конкретных тем кодификатора из выбранных блоков"""
    query = update.callback_query

    task_type = context.user_data.get('assignment_task_type')
    selected_blocks = context.user_data.get('selected_blocks', [])

    from ..services.topics_loader import load_topics_for_module

    # Загружаем темы
    topics_data = load_topics_for_module(task_type)

    # Инициализируем список выбранных тем
    if 'selected_topic_ids' not in context.user_data:
        context.user_data['selected_topic_ids'] = []

    # Собираем темы из выбранных блоков
    available_topics = []
    for block_name in selected_blocks:
        block_topics = topics_data['blocks'].get(block_name, [])
        available_topics.extend(block_topics)

    if not available_topics:
        await query.answer("⚠️ В выбранных блоках нет тем", show_alert=True)
        return TeacherStates.SELECT_TOPICS

    task_names = {
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    text = (
        f"📖 <b>{task_name}: Выбор тем</b>\n\n"
        f"Выберите темы кодификатора:\n"
        f"(можно выбрать несколько)\n\n"
        f"<i>Выбрано блоков: {', '.join(selected_blocks)}</i>\n\n"
    )

    keyboard = []

    # Группируем темы по блокам для удобства
    for block_name in selected_blocks:
        block_topics = topics_data['blocks'].get(block_name, [])

        if not block_topics:
            continue

        # Заголовок блока
        keyboard.append([InlineKeyboardButton(
            f"📁 {block_name}",
            callback_data="noop"  # Неактивная кнопка-заголовок
        )])

        # Темы блока
        for topic in block_topics:
            topic_id = topic['id']
            selected = topic_id in context.user_data['selected_topic_ids']
            emoji = "✅" if selected else "⬜"

            # Обрезаем длинные названия
            title = topic['title']
            if len(title) > 45:
                title = title[:42] + "..."

            keyboard.append([InlineKeyboardButton(
                f"{emoji} {title}",
                callback_data=f"toggle_topic:{topic_id}"
            )])

    # Кнопка "Далее" если выбрана хотя бы одна тема
    if context.user_data['selected_topic_ids']:
        total_questions = sum(
            topics_data['topics_by_id'][tid]['questions_count']
            for tid in context.user_data['selected_topic_ids']
            if tid in topics_data['topics_by_id']
        )

        keyboard.append([InlineKeyboardButton(
            f"➡️ Выбрано тем: {len(context.user_data['selected_topic_ids'])} ({total_questions} вопр.)",
            callback_data="topics_confirm_topics"
        )])

    keyboard.append([InlineKeyboardButton("◀️ Назад к блокам", callback_data=f"assign_task_{task_type}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.SELECT_TOPICS


async def toggle_topic_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Переключение выбора темы"""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID темы из callback_data
    topic_id = int(query.data.replace("toggle_topic:", ""))

    # Переключаем выбор
    if 'selected_topic_ids' not in context.user_data:
        context.user_data['selected_topic_ids'] = []

    if topic_id in context.user_data['selected_topic_ids']:
        context.user_data['selected_topic_ids'].remove(topic_id)
    else:
        context.user_data['selected_topic_ids'].append(topic_id)

    # Перерисовываем меню
    return await show_topics_selection(update, context)


async def confirm_topics_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение выбора тем и переход к фильтру по номеру задания ЕГЭ (опционально)"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type')
    selected_topic_ids = context.user_data.get('selected_topic_ids', [])

    if not selected_topic_ids:
        await query.answer("⚠️ Выберите хотя бы одну тему", show_alert=True)
        return TeacherStates.SELECT_TOPICS

    # Для test_part предлагаем фильтр по номеру задания ЕГЭ
    if task_type == 'test_part':
        return await show_exam_number_filter(update, context)
    else:
        # Для других модулей сразу переходим к выбору конкретных вопросов
        return await show_specific_questions_selection(update, context)


async def show_exam_number_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать фильтр по номеру задания ЕГЭ (1-16)"""
    query = update.callback_query

    task_type = context.user_data.get('assignment_task_type')
    selected_topic_ids = context.user_data.get('selected_topic_ids', [])

    from ..services.topics_loader import load_topics_for_module

    # Загружаем темы
    topics_data = load_topics_for_module(task_type)

    # Собираем все доступные номера заданий из выбранных тем
    available_exam_numbers = set()
    for topic_id in selected_topic_ids:
        topic_data = topics_data['topics_by_id'].get(topic_id)
        if topic_data and 'exam_numbers' in topic_data:
            available_exam_numbers.update(topic_data['exam_numbers'])

    available_exam_numbers = sorted(list(available_exam_numbers))

    # Инициализируем выбранные номера заданий
    if 'selected_exam_numbers' not in context.user_data:
        context.user_data['selected_exam_numbers'] = []

    text = (
        f"🎯 <b>Тестовая часть: Фильтр по номеру задания</b>\n\n"
        f"Выберите номера заданий ЕГЭ для фильтрации:\n"
        f"(можно выбрать несколько или пропустить этот шаг)\n\n"
        f"<i>Доступны номера: {', '.join(map(str, available_exam_numbers))}</i>\n\n"
    )

    keyboard = []

    # Создаем кнопки для номеров заданий (по 4 в ряд)
    row = []
    for exam_num in available_exam_numbers:
        selected = exam_num in context.user_data['selected_exam_numbers']
        emoji = "✅" if selected else "⬜"

        row.append(InlineKeyboardButton(
            f"{emoji} №{exam_num}",
            callback_data=f"toggle_exam_num:{exam_num}"
        ))

        if len(row) == 4:
            keyboard.append(row)
            row = []

    if row:  # Добавляем оставшиеся кнопки
        keyboard.append(row)

    # Кнопки действий
    action_buttons = []

    # Кнопка "Выбрать все"
    if len(context.user_data['selected_exam_numbers']) < len(available_exam_numbers):
        action_buttons.append(InlineKeyboardButton(
            "✅ Выбрать все",
            callback_data="exam_num_select_all"
        ))

    # Кнопка "Снять все"
    if context.user_data['selected_exam_numbers']:
        action_buttons.append(InlineKeyboardButton(
            "⬜ Снять все",
            callback_data="exam_num_deselect_all"
        ))

    if action_buttons:
        keyboard.append(action_buttons)

    # Кнопка "Продолжить"
    continue_text = "➡️ Продолжить без фильтра"
    if context.user_data['selected_exam_numbers']:
        continue_text = f"➡️ Применить фильтр ({len(context.user_data['selected_exam_numbers'])} номеров)"

    keyboard.append([InlineKeyboardButton(
        continue_text,
        callback_data="exam_num_confirm"
    )])

    keyboard.append([InlineKeyboardButton("◀️ Назад к темам", callback_data="topics_back_to_topics")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.SELECT_TOPICS


async def toggle_exam_number_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Переключение выбора номера задания в фильтре"""
    query = update.callback_query
    await query.answer()

    # Извлекаем номер задания из callback_data
    exam_num = int(query.data.replace("toggle_exam_num:", ""))

    # Переключаем выбор
    if 'selected_exam_numbers' not in context.user_data:
        context.user_data['selected_exam_numbers'] = []

    if exam_num in context.user_data['selected_exam_numbers']:
        context.user_data['selected_exam_numbers'].remove(exam_num)
    else:
        context.user_data['selected_exam_numbers'].append(exam_num)

    # Перерисовываем меню
    return await show_exam_number_filter(update, context)


async def exam_number_filter_select_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбрать все номера заданий в фильтре"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type')
    selected_topic_ids = context.user_data.get('selected_topic_ids', [])

    from ..services.topics_loader import load_topics_for_module

    topics_data = load_topics_for_module(task_type)

    # Собираем все доступные номера заданий
    available_exam_numbers = set()
    for topic_id in selected_topic_ids:
        topic_data = topics_data['topics_by_id'].get(topic_id)
        if topic_data and 'exam_numbers' in topic_data:
            available_exam_numbers.update(topic_data['exam_numbers'])

    context.user_data['selected_exam_numbers'] = sorted(list(available_exam_numbers))

    return await show_exam_number_filter(update, context)


async def exam_number_filter_deselect_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Снять все номера заданий в фильтре"""
    query = update.callback_query
    await query.answer()

    context.user_data['selected_exam_numbers'] = []

    return await show_exam_number_filter(update, context)


async def confirm_exam_number_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение фильтра по номеру задания"""
    query = update.callback_query
    await query.answer()

    # Переходим к выбору конкретных вопросов
    return await show_specific_questions_selection(update, context)


async def show_specific_questions_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показать список конкретных заданий из выбранных тем для выбора"""
    query = update.callback_query

    task_type = context.user_data.get('assignment_task_type')
    selected_topic_ids = context.user_data.get('selected_topic_ids', [])
    selected_exam_numbers = context.user_data.get('selected_exam_numbers', [])

    from ..services.topics_loader import load_topics_for_module

    # Загружаем темы
    topics_data = load_topics_for_module(task_type)

    # Инициализируем список выбранных заданий если его нет
    if 'selected_question_ids' not in context.user_data:
        context.user_data['selected_question_ids'] = []

    # Собираем ID вопросов из выбранных тем с учетом фильтра
    available_question_ids = []

    for topic_id in selected_topic_ids:
        topic_data = topics_data['topics_by_id'].get(topic_id)
        if not topic_data:
            continue

        question_ids = topic_data.get('question_ids', [])
        available_question_ids.extend(question_ids)

    # Если есть фильтр по exam_number, применяем его
    if selected_exam_numbers and task_type == 'test_part':
        # Загружаем реальные вопросы для фильтрации
        from test_part.loader import get_questions_dict_flat

        questions_dict = get_questions_dict_flat()
        if questions_dict:
            # Фильтруем по exam_number
            available_question_ids = [
                q_id for q_id in available_question_ids
                if q_id in questions_dict and
                questions_dict[q_id].get('exam_number') in selected_exam_numbers
            ]

    if not available_question_ids:
        await query.answer("⚠️ В выбранных темах нет заданий", show_alert=True)
        return TeacherStates.SELECT_TOPICS

    # Загружаем реальные вопросы для отображения
    from test_part.loader import get_questions_dict_flat
    questions_dict = get_questions_dict_flat() if task_type == 'test_part' else {}

    task_names = {
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    task_name = task_names.get(task_type, task_type)

    selected_count = len(context.user_data['selected_question_ids'])
    total_count = len(available_question_ids)

    # Формируем текст
    text = (
        f"📝 <b>{task_name}: Выбор заданий</b>\n\n"
        f"✅ Выбрано: {selected_count} из {total_count}\n\n"
    )

    if selected_exam_numbers:
        text += f"🎯 Фильтр по №: {', '.join(map(str, selected_exam_numbers))}\n\n"

    text += "Выберите конкретные задания для домашней работы:\n"

    keyboard = []

    # Добавляем кнопки для каждого задания
    for q_id in available_question_ids[:50]:  # Ограничиваем первыми 50 для избежания ошибок Telegram
        # Получаем информацию о вопросе
        if task_type == 'test_part' and questions_dict:
            question_data = questions_dict.get(q_id, {})
            exam_num = question_data.get('exam_number', '?')
            topic = question_data.get('topic', '?')
            q_title = f"№{exam_num} | {topic}"
        else:
            q_title = str(q_id)

        selected = q_id in context.user_data['selected_question_ids']
        emoji = "✅" if selected else "⬜"

        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {q_title}",
                callback_data=f"toggle_question:{q_id}"
            )
        ])

    # Показываем сообщение если заданий больше 50
    if len(available_question_ids) > 50:
        text += f"\n<i>⚠️ Показаны первые 50 из {total_count} заданий</i>\n"

    # Кнопки управления
    if selected_count > 0:
        keyboard.append([
            InlineKeyboardButton(f"✅ Подтвердить выбор ({selected_count})", callback_data="confirm_selected_questions")
        ])

    keyboard.append([
        InlineKeyboardButton("🔄 Выбрать все", callback_data="select_all_questions"),
        InlineKeyboardButton("❌ Снять все", callback_data="deselect_all_questions")
    ])

    # Кнопка "Назад"
    if task_type == 'test_part' and selected_exam_numbers:
        keyboard.append([InlineKeyboardButton("◀️ Назад к фильтру", callback_data="topics_back_to_exam_filter")])
    else:
        keyboard.append([InlineKeyboardButton("◀️ Назад к темам", callback_data="topics_back_to_topics")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    # Сохраняем список всех доступных вопросов для кнопок "Выбрать все"/"Снять все"
    context.user_data['available_question_ids'] = available_question_ids

    return TeacherStates.SELECT_SPECIFIC_QUESTIONS


async def toggle_question_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Переключение выбора конкретного задания"""
    query = update.callback_query
    await query.answer()

    # Извлекаем ID задания из callback_data (может быть строкой или числом)
    question_id = query.data.split(':')[1]

    # Пробуем преобразовать в int для других модулей
    try:
        question_id = int(question_id)
    except ValueError:
        # Оставляем как строку (для test_part)
        pass

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
    """Выбрать все задания из доступных"""
    query = update.callback_query
    await query.answer("✅ Все задания выбраны")

    # Используем сохраненный список доступных вопросов
    available_question_ids = context.user_data.get('available_question_ids', [])
    context.user_data['selected_question_ids'] = available_question_ids.copy()

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
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
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
        keyboard.append([InlineKeyboardButton("➡️ Создать задание", callback_data="assignment_enter_title")])
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
            keyboard.append([InlineKeyboardButton("➡️ Далее", callback_data="assignment_enter_title")])
        else:
            keyboard.append([InlineKeyboardButton("➡️ Создать без назначения", callback_data="assignment_enter_title")])

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


async def prompt_assignment_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрос названия для домашнего задания"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type', '')
    selected_count = len(context.user_data.get('selected_students', []))

    task_names = {
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25',
        'mixed': '🔀 Смешанное задание',
        'custom': '📝 Кастомное задание',
        'full_exam': '🎯 Полный вариант ЕГЭ'
    }
    default_title = task_names.get(task_type, f"Задание {task_type}")

    if selected_count > 0:
        text = (
            f"📝 <b>Создание задания</b>\n\n"
            f"👥 Будет назначено ученикам: {selected_count}\n\n"
            "✏️ <b>Введите название для задания</b>\n\n"
            f"Например:\n"
            f"• ДЗ по темам 1-5\n"
            f"• Контрольная работа №1\n"
            f"• Подготовка к пробному ЕГЭ\n\n"
            f"Или отправьте /skip чтобы использовать название по умолчанию:\n"
            f"<code>{default_title}</code>"
        )
    else:
        text = (
            f"📝 <b>Создание задания</b>\n\n"
            "✏️ <b>Введите название для задания</b>\n\n"
            f"Например:\n"
            f"• ДЗ по темам 1-5\n"
            f"• Контрольная работа №1\n"
            f"• Подготовка к пробному ЕГЭ\n\n"
            f"Или отправьте /skip чтобы использовать название по умолчанию:\n"
            f"<code>{default_title}</code>"
        )

    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_ASSIGNMENT_TITLE


async def process_assignment_title_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка введенного названия задания"""
    user_input = update.message.text.strip()

    # Проверка на команду skip
    if user_input == '/skip':
        task_type = context.user_data.get('assignment_task_type', '')
        task_names = {
            'test_part': '📝 Тестовая часть (1-16)',
            'task19': '💡 Задание 19',
            'task20': '⚙️ Задание 20',
            'task21': '📊 Задание 21',
            'task22': '📝 Задание 22',
            'task23': '📜 Задание 23',
            'task24': '📊 Задание 24',
            'task25': '💻 Задание 25',
            'mixed': '🔀 Смешанное задание',
            'custom': '📝 Кастомное задание',
            'full_exam': '🎯 Полный вариант ЕГЭ'
        }
        assignment_title = task_names.get(task_type, f"Задание {task_type}")
    else:
        # Валидация длины названия
        if len(user_input) > 100:
            await update.message.reply_text(
                "❌ <b>Название слишком длинное</b>\n\n"
                "Максимальная длина: 100 символов\n"
                "Попробуйте еще раз или отправьте /skip:",
                parse_mode='HTML'
            )
            return TeacherStates.ENTER_ASSIGNMENT_TITLE

        if len(user_input) < 3:
            await update.message.reply_text(
                "❌ <b>Название слишком короткое</b>\n\n"
                "Минимальная длина: 3 символа\n"
                "Попробуйте еще раз или отправьте /skip:",
                parse_mode='HTML'
            )
            return TeacherStates.ENTER_ASSIGNMENT_TITLE

        assignment_title = user_input

    # Сохраняем название в контексте
    context.user_data['assignment_title'] = assignment_title

    # Переходим к установке дедлайна
    # Создаем фейковый query для вызова set_assignment_deadline
    from telegram import CallbackQuery

    # Создаем новое сообщение с кнопками для дедлайна
    task_type = context.user_data.get('assignment_task_type', '')
    selected_count = len(context.user_data.get('selected_students', []))

    if selected_count > 0:
        text = (
            f"📝 <b>Создание задания: {assignment_title}</b>\n\n"
            f"👥 Выбрано учеников: {selected_count}\n\n"
            "Установите дедлайн для выполнения задания:"
        )
    else:
        text = (
            f"📝 <b>Создание задания: {assignment_title}</b>\n\n"
            "📋 Задание будет создано без назначения конкретным ученикам\n\n"
            "Установите дедлайн для выполнения задания:"
        )

    keyboard = []

    # Предлагаем варианты дедлайнов
    from teacher_mode.utils.datetime_utils import utc_now
    today = utc_now()  # ИСПРАВЛЕНО: timezone-aware datetime
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
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.CREATE_ASSIGNMENT


async def set_assignment_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка дедлайна для задания"""
    query = update.callback_query
    await query.answer()

    task_type = context.user_data.get('assignment_task_type', '')
    task_names = {
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
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
    from teacher_mode.utils.datetime_utils import utc_now
    today = utc_now()  # ИСПРАВЛЕНО: timezone-aware datetime
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

    # ИСПРАВЛЕНО: Rate limiting для защиты от спама создания заданий
    allowed, retry_after = check_operation_limit(user_id, 'create_homework')
    if not allowed:
        await query.message.edit_text(
            f"⏱ <b>Слишком много заданий создано</b>\n\n"
            f"Пожалуйста, подождите {retry_after} секунд и попробуйте снова.\n\n"
            f"💡 Лимит: 20 заданий в час",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ В меню учителя", callback_data="teacher_menu")
            ]]),
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Извлекаем данные из контекста
    task_type = context.user_data.get('assignment_task_type')
    selected_students = context.user_data.get('selected_students', [])

    # Парсим дедлайн из callback_data
    deadline_days = query.data.replace("deadline_", "")

    deadline = None
    if deadline_days != "none":
        from teacher_mode.utils.datetime_utils import utc_now
        deadline = utc_now() + timedelta(days=int(deadline_days))  # ИСПРАВЛЕНО: timezone-aware datetime

    # Создаём задание через assignment_service
    from ..services import assignment_service
    from ..models import AssignmentType, TargetType

    # Используем сохраненное название или генерируем по умолчанию
    title = context.user_data.get('assignment_title')
    if not title:
        task_names = {
            'test_part': 'Тестовая часть (1-16)',
            'task19': 'Задание 19',
            'task20': 'Задание 20',
            'task21': 'Задание 21',
            'task22': 'Задание 22',
            'task23': 'Задание 23',
            'task24': 'Задание 24',
            'task25': 'Задание 25',
            'mixed': 'Смешанное задание',
            'custom': 'Кастомное задание',
            'full_exam': 'Полный вариант ЕГЭ'
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

        # Отправляем уведомления ученикам
        if selected_students:
            from ..services import notification_service

            # Получаем имя учителя
            teacher_profile = await teacher_service.get_teacher_profile(user_id)
            teacher_name = teacher_profile.display_name if teacher_profile else "Ваш учитель"

            # Отправляем уведомления асинхронно (не блокируя UI)
            questions_count = assignment_data.get('questions_count', 0)

            notification_result = await notification_service.notify_students_about_homework(
                bot=context.bot,
                student_ids=selected_students,
                homework_title=title,
                teacher_name=teacher_name,
                deadline=deadline,
                questions_count=questions_count
            )

            # Формируем текст с учетом результатов отправки
            notification_info = ""
            if notification_result['success'] > 0:
                notification_info = f"✅ Уведомления отправлены: {notification_result['success']}/{len(selected_students)}"
            if notification_result['failed'] > 0:
                notification_info += f"\n⚠️ Не удалось отправить: {notification_result['failed']}"

            # Задание назначено ученикам
            text = (
                "✅ <b>Задание успешно создано!</b>\n\n"
                f"📝 <b>Название:</b> {title}\n"
                f"👥 <b>Назначено учеников:</b> {len(selected_students)}\n"
                f"⏰ <b>Дедлайн:</b> {deadline_text}\n\n"
                f"{notification_info}"
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
    context.user_data.pop('assignment_title', None)
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

    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS

    # Проверяем доступ: только Premium-учителя и админы
    if not is_admin:
        profile = await teacher_service.get_teacher_profile(user_id)
        if not profile or profile.subscription_tier != 'teacher_premium':
            await query.message.edit_text(
                "❌ <b>Доступ ограничен</b>\n\n"
                "Функция дарения подписок доступна только на тарифе <b>Teacher Premium</b>.\n\n"
                "💎 Преимущества Premium:\n"
                "• Безлимит учеников\n"
                "• Дарение подписок и создание промокодов\n"
                "• Продвинутая аналитика\n\n"
                "Перейдите на Premium для доступа к этой функции.",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Перейти на Premium", callback_data="teacher_subscriptions")],
                    [InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")]
                ])
            )
            return TeacherStates.TEACHER_MENU

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

    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS

    # Проверяем доступ: только Premium-учителя и админы
    if not is_admin:
        profile = await teacher_service.get_teacher_profile(user_id)
        if not profile or profile.subscription_tier != 'teacher_premium':
            await query.message.edit_text(
                "❌ <b>Доступ ограничен</b>\n\n"
                "Создание промокодов доступно только на тарифе <b>Teacher Premium</b>.",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Перейти на Premium", callback_data="teacher_subscriptions")],
                    [InlineKeyboardButton("◀️ Назад", callback_data="teacher_gift_menu")]
                ])
            )
            return TeacherStates.TEACHER_MENU

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

    # ИСПРАВЛЕНО: Rate limiting для защиты от спама создания промокодов
    allowed, retry_after = check_operation_limit(user_id, 'create_promo')
    if not allowed:
        await query.message.edit_text(
            f"⏱ <b>Слишком много промокодов создано</b>\n\n"
            f"Пожалуйста, подождите {retry_after} секунд и попробуйте снова.\n\n"
            f"💡 Лимит: 5 промокодов в час",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="gift_my_promos")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

    uses_str = query.data.replace("promo_uses_", "")
    max_uses = None if uses_str == "unlimited" else int(uses_str)
    duration_days = context.user_data.get('promo_duration', 30)

    from ..services import gift_service

    try:
        promo = await gift_service.create_promo_code(
            creator_id=user_id,
            duration_days=duration_days,
            max_uses=max_uses,
            expires_at=None
        )
    except PermissionError as e:
        text = f"❌ <b>Нет доступа</b>\n\n{e}"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="teacher_gift_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        context.user_data.pop('promo_duration', None)
        return TeacherStates.TEACHER_MENU

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

    # Импортируем необходимые сервисы
    from ..services import assignment_service, teacher_service

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


async def _verify_teacher_owns_homework(teacher_id: int, homework_id: int) -> bool:
    """Проверяет, что учитель является владельцем задания."""
    homework = await assignment_service.get_homework_by_id(homework_id)
    return homework is not None and homework.teacher_id == teacher_id


async def _verify_teacher_owns_progress(teacher_id: int, progress_id: int):
    """
    Проверяет, что учитель является владельцем ответа (через homework).
    Возвращает (progress_data, homework) или (None, None) если нет доступа.
    """
    progress_data = await assignment_service.get_question_progress_by_id(progress_id)
    if not progress_data:
        return None, None
    homework = await assignment_service.get_homework_by_id(progress_data['homework_id'])
    if not homework or homework.teacher_id != teacher_id:
        return None, None
    return progress_data, homework


async def view_answer_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Просмотр конкретного ответа ученика с возможностью добавить комментарий"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Парсим callback_data: view_answer:progress_id
    progress_id = int(query.data.split(':')[1])

    # Проверяем права доступа учителя к ответу
    progress_data, homework = await _verify_teacher_owns_progress(user_id, progress_id)

    if not progress_data:
        await query.message.edit_text(
            "❌ Ответ не найден или у вас нет доступа.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="teacher_my_assignments")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

    homework_id = progress_data['homework_id']
    student_id = progress_data['student_id']
    question_id = progress_data['question_id']

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

    user_id = update.effective_user.id

    # Извлекаем progress_id из callback_data
    progress_id = int(query.data.split(':')[1])

    # Проверяем права доступа учителя к ответу
    progress_data, homework = await _verify_teacher_owns_progress(user_id, progress_id)
    if not progress_data:
        await query.message.edit_text(
            "❌ У вас нет доступа к этому ответу.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="teacher_my_assignments")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

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
    user_id = update.effective_user.id

    # ИСПРАВЛЕНО: Rate limiting для защиты от спама комментариев
    allowed, retry_after = check_operation_limit(user_id, 'add_comment')
    if not allowed:
        await update.message.reply_text(
            f"⏱ <b>Слишком много комментариев</b>\n\n"
            f"Пожалуйста, подождите {retry_after} секунд и попробуйте снова.\n\n"
            f"💡 Лимит: 30 комментариев в минуту",
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

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

    user_id = update.effective_user.id

    # Извлекаем progress_id из callback_data
    progress_id = int(query.data.split(':')[1])

    # Проверяем права доступа учителя к ответу
    progress_data, homework = await _verify_teacher_owns_progress(user_id, progress_id)

    if not progress_data:
        await query.message.edit_text(
            "❌ Ответ не найден или у вас нет доступа.",
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

    user_id = update.effective_user.id

    # Извлекаем action и progress_id из callback_data
    parts = query.data.split(':')
    action = parts[0]  # set_score_accept или set_score_reject
    progress_id = int(parts[1])

    # Проверяем права доступа учителя к ответу
    progress_data, homework = await _verify_teacher_owns_progress(user_id, progress_id)
    if not progress_data:
        await query.message.edit_text(
            "❌ У вас нет доступа к этому ответу.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="teacher_my_assignments")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

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
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
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
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
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
            'test_part': '📝 Тестовая часть (1-16)',
            'task19': '💡 Задание 19',
            'task20': '⚙️ Задание 20',
            'task21': '📊 Задание 21',
            'task22': '📝 Задание 22',
            'task23': '📜 Задание 23',
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

    # Сохраняем текст вопроса во временное хранилище
    context.user_data['current_custom_question'] = {
        'text': question_text
    }

    # Просим выбрать тип задания
    text = f"✅ <b>Текст вопроса сохранен!</b>\n\n"
    text += f"<i>{question_text[:150]}{'...' if len(question_text) > 150 else ''}</i>\n\n"
    text += "📚 <b>Выберите тип задания:</b>\n\n"
    text += "Это определит, как будет проверяться ответ ученика."

    keyboard = [
        [InlineKeyboardButton("📝 Тестовая часть (короткий ответ)", callback_data="custom_type_test_part")],
        [InlineKeyboardButton("💡 Задание 19 (примеры)", callback_data="custom_type_task19")],
        [InlineKeyboardButton("⚙️ Задание 20 (слова)", callback_data="custom_type_task20")],
        [InlineKeyboardButton("📊 Задание 21 (графики)", callback_data="custom_type_task21")],
        [InlineKeyboardButton("📝 Задание 22 (анализ ситуаций)", callback_data="custom_type_task22")],
        [InlineKeyboardButton("📜 Задание 23 (Конституция РФ)", callback_data="custom_type_task23")],
        [InlineKeyboardButton("📊 Задание 24 (пропуски)", callback_data="custom_type_task24")],
        [InlineKeyboardButton("💻 Задание 25 (сочинение)", callback_data="custom_type_task25")],
        [InlineKeyboardButton("◀️ Отменить вопрос", callback_data="cancel_current_custom_question")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.SELECT_CUSTOM_QUESTION_TYPE


async def select_custom_question_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обрабатывает выбор типа задания для кастомного вопроса.
    """
    query = update.callback_query
    await query.answer()

    # Извлекаем тип из callback_data
    question_type = query.data.replace("custom_type_", "")

    current_question = context.user_data.get('current_custom_question', {})
    current_question['type'] = question_type

    context.user_data['current_custom_question'] = current_question

    type_names = {
        'test_part': '📝 Тестовая часть',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    type_name = type_names.get(question_type, question_type)

    # Спрашиваем, хочет ли учитель указать правильный ответ/критерии
    text = f"✅ <b>Тип задания: {type_name}</b>\n\n"
    text += "❓ <b>Хотите указать правильный ответ или критерии оценки?</b>\n\n"
    text += "Это поможет AI более точно проверять ответы учеников.\n\n"
    text += "• <b>Для тестовой части:</b> точный правильный ответ\n"
    text += "• <b>Для заданий 19-25:</b> критерии оценки или примеры правильного ответа"

    keyboard = [
        [InlineKeyboardButton("✍️ Да, указать ответ/критерии", callback_data="enter_custom_answer_yes")],
        [InlineKeyboardButton("⏭ Нет, пропустить", callback_data="enter_custom_answer_skip")],
        [InlineKeyboardButton("◀️ Отменить вопрос", callback_data="cancel_current_custom_question")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.SELECT_CUSTOM_QUESTION_TYPE


async def prompt_custom_question_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Запрашивает ввод правильного ответа или критериев оценки.
    """
    query = update.callback_query
    await query.answer()

    choice = query.data

    if choice == "enter_custom_answer_skip":
        # Пропускаем ввод ответа, сохраняем вопрос
        return await finalize_custom_question(update, context, skip_answer=True)

    # Запрашиваем ввод ответа/критериев
    current_question = context.user_data.get('current_custom_question', {})
    question_type = current_question.get('type', '')

    type_names = {
        'test_part': '📝 Тестовая часть',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    type_name = type_names.get(question_type, question_type)

    text = f"✍️ <b>{type_name}</b>\n\n"

    if question_type == 'test_part':
        text += "📝 <b>Введите правильный ответ:</b>\n\n"
        text += "Например: <code>125</code> или <code>программирование</code>\n\n"
        text += "Это поможет AI точнее проверять короткие ответы."
    else:
        text += "📝 <b>Введите критерии оценки или пример правильного ответа:</b>\n\n"
        text += "Например:\n"
        text += "• Ключевые пункты, которые должны быть в ответе\n"
        text += "• Примеры правильных формулировок\n"
        text += "• Критерии для оценки качества ответа"

    keyboard = [[InlineKeyboardButton("◀️ Отменить вопрос", callback_data="cancel_current_custom_question")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_CUSTOM_QUESTION_ANSWER


async def process_custom_question_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обрабатывает ввод правильного ответа/критериев оценки.
    """
    answer_text = update.message.text.strip()

    if len(answer_text) < 3:
        await update.message.reply_text(
            "❌ <b>Ответ слишком короткий</b>\n\n"
            "Минимальная длина: 3 символа.\n"
            "Попробуйте еще раз:",
            parse_mode='HTML'
        )
        return TeacherStates.ENTER_CUSTOM_QUESTION_ANSWER

    if len(answer_text) > 1000:
        await update.message.reply_text(
            "❌ <b>Ответ слишком длинный</b>\n\n"
            "Максимальная длина: 1000 символов.\n"
            "Попробуйте еще раз:",
            parse_mode='HTML'
        )
        return TeacherStates.ENTER_CUSTOM_QUESTION_ANSWER

    # Сохраняем ответ
    current_question = context.user_data.get('current_custom_question', {})
    current_question['correct_answer'] = answer_text
    context.user_data['current_custom_question'] = current_question

    # Финализируем вопрос
    return await finalize_custom_question_direct(update, context, skip_answer=False)


async def finalize_custom_question(update: Update, context: ContextTypes.DEFAULT_TYPE, skip_answer: bool = False) -> int:
    """
    Финализирует кастомный вопрос и добавляет его в список.
    """
    query = update.callback_query

    current_question = context.user_data.get('current_custom_question', {})

    if not current_question:
        await query.answer("⚠️ Ошибка: вопрос не найден", show_alert=True)
        return TeacherStates.ENTER_CUSTOM_QUESTION

    # Добавляем вопрос в список
    custom_questions = context.user_data.get('custom_questions', [])
    question_id = len(custom_questions) + 1

    question_data = {
        'id': question_id,
        'text': current_question['text'],
        'type': current_question.get('type', 'test_part'),
        'correct_answer': current_question.get('correct_answer', None)
    }

    custom_questions.append(question_data)
    context.user_data['custom_questions'] = custom_questions
    context.user_data.pop('current_custom_question', None)

    type_names = {
        'test_part': '📝 Тестовая часть',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    type_name = type_names.get(question_data['type'], question_data['type'])

    text = f"✅ <b>Вопрос #{question_id} добавлен!</b>\n\n"
    text += f"📚 <b>Тип:</b> {type_name}\n"
    text += f"📝 <b>Текст:</b> <i>{question_data['text'][:100]}{'...' if len(question_data['text']) > 100 else ''}</i>\n"
    if question_data['correct_answer']:
        text += f"✅ <b>Ответ/Критерии:</b> указаны\n"
    text += f"\n📊 <b>Всего вопросов:</b> {len(custom_questions)}\n\n"
    text += "💬 Отправьте текст следующего вопроса или завершите создание:"

    keyboard = [
        [InlineKeyboardButton(f"✅ Завершить ({len(custom_questions)} вопросов)", callback_data="finish_custom_questions")],
        [InlineKeyboardButton("👀 Просмотреть все вопросы", callback_data="review_custom_questions")],
        [InlineKeyboardButton("❌ Отменить", callback_data="teacher_create_assignment")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_CUSTOM_QUESTION


async def finalize_custom_question_direct(update: Update, context: ContextTypes.DEFAULT_TYPE, skip_answer: bool = False) -> int:
    """
    Финализирует кастомный вопрос после текстового ввода (без callback query).
    """
    current_question = context.user_data.get('current_custom_question', {})

    # Добавляем вопрос в список
    custom_questions = context.user_data.get('custom_questions', [])
    question_id = len(custom_questions) + 1

    question_data = {
        'id': question_id,
        'text': current_question['text'],
        'type': current_question.get('type', 'test_part'),
        'correct_answer': current_question.get('correct_answer', None)
    }

    custom_questions.append(question_data)
    context.user_data['custom_questions'] = custom_questions
    context.user_data.pop('current_custom_question', None)

    type_names = {
        'test_part': '📝 Тестовая часть',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }
    type_name = type_names.get(question_data['type'], question_data['type'])

    text = f"✅ <b>Вопрос #{question_id} добавлен!</b>\n\n"
    text += f"📚 <b>Тип:</b> {type_name}\n"
    text += f"📝 <b>Текст:</b> <i>{question_data['text'][:100]}{'...' if len(question_data['text']) > 100 else ''}</i>\n"
    if question_data['correct_answer']:
        text += f"✅ <b>Ответ/Критерии:</b> указаны\n"
    text += f"\n📊 <b>Всего вопросов:</b> {len(custom_questions)}\n\n"
    text += "💬 Отправьте текст следующего вопроса или завершите создание:"

    keyboard = [
        [InlineKeyboardButton(f"✅ Завершить ({len(custom_questions)} вопросов)", callback_data="finish_custom_questions")],
        [InlineKeyboardButton("👀 Просмотреть все вопросы", callback_data="review_custom_questions")],
        [InlineKeyboardButton("❌ Отменить", callback_data="teacher_create_assignment")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.ENTER_CUSTOM_QUESTION


async def cancel_current_custom_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Отменяет добавление текущего кастомного вопроса.
    """
    query = update.callback_query
    await query.answer("❌ Вопрос отменен")

    context.user_data.pop('current_custom_question', None)

    return await start_custom_question_entry(update, context)


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

    type_names = {
        'test_part': '📝 Тестовая часть',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task21': '📊 Задание 21',
        'task22': '📝 Задание 22',
        'task23': '📜 Задание 23',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
    }

    for q in custom_questions:
        question_preview = q['text'][:60] + ('...' if len(q['text']) > 60 else '')
        question_type = type_names.get(q.get('type', 'test_part'), 'Не указан')
        has_answer = "✅" if q.get('correct_answer') else "⚪"

        text += f"<b>{q['id']}.</b> {question_type} {has_answer}\n"
        text += f"<i>{question_preview}</i>\n\n"

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

    # Проверяем, что ученик принадлежит этому учителю
    student_ids = await teacher_service.get_teacher_students(user_id)
    if student_id not in student_ids:
        await query.message.edit_text(
            "❌ У вас нет доступа к статистике этого ученика.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="teacher_students")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

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
                'task21': '📊 Задание 21',
                'task22': '📝 Задание 22',
                'task23': '📜 Задание 23',
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


async def handle_free_activation_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик бесплатной активации подписки при 100% скидке (wrapper для teacher режима).
    Перенаправляет на основной обработчик из payment модуля.
    """
    query = update.callback_query
    user_id = update.effective_user.id

    logger.info(f"[Teacher Payment] User {user_id} activating free subscription")

    try:
        from payment.handlers import handle_free_activation

        # Вызываем основной обработчик бесплатной активации
        result = await handle_free_activation(update, context)

        logger.info(f"[Teacher Payment] Free activation result: {result}")

        # После активации возвращаем пользователя в меню учителя
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"[Teacher Payment] Error in free activation for user {user_id}: {e}", exc_info=True)
        await query.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)
        return ConversationHandler.END


async def handle_pay_one_ruble_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик оплаты 1 рубля (wrapper для teacher режима).
    Перенаправляет на основной обработчик из payment модуля.
    """
    query = update.callback_query
    user_id = update.effective_user.id

    logger.info(f"[Teacher Payment] User {user_id} choosing to pay 1 ruble")

    try:
        from payment.handlers import handle_pay_one_ruble

        # Вызываем основной обработчик оплаты 1 рубля
        result = await handle_pay_one_ruble(update, context)

        logger.info(f"[Teacher Payment] Pay one ruble result: {result}")

        # После выбора оплаты переходим к выбору автопродления
        return TeacherStates.PAYMENT_AUTO_RENEWAL_CHOICE

    except Exception as e:
        logger.error(f"[Teacher Payment] Error in pay one ruble for user {user_id}: {e}", exc_info=True)
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

    # ИСПРАВЛЕНО: Rate limiting для защиты от брутфорса промокодов
    allowed, retry_after = check_operation_limit(user_id, 'use_promo')
    if not allowed:
        await update.message.reply_text(
            f"⏱ <b>Слишком много попыток ввода промокода</b>\n\n"
            f"Пожалуйста, подождите {retry_after} секунд и попробуйте снова.\n\n"
            f"💡 Лимит: 3 попытки в минуту",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад в меню учителя", callback_data="teacher_menu")]
            ]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

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
