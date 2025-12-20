"""
Обработчики для быстрой проверки работ (Quick Check).

Функционал для онлайн-школ: проверка работ, не назначенных через бота.
"""

import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from ..states import TeacherStates
from ..models import QuickCheckTaskType
from ..services import quick_check_service
from ..utils.rate_limiter import check_operation_limit

logger = logging.getLogger(__name__)


# ============================================
# Главное меню быстрой проверки
# ============================================

async def quick_check_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Главное меню быстрой проверки"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем квоту учителя
    quota = await quick_check_service.get_or_create_quota(user_id)

    if not quota:
        await query.message.edit_text(
            "❌ Ошибка получения квоты. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="teacher_menu")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.TEACHER_MENU

    # Получаем краткую статистику
    stats = await quick_check_service.get_quick_check_stats(user_id, days=30)

    text = (
        "🔍 <b>Быстрая проверка работ</b>\n\n"
        "Проверяйте работы учеников с помощью AI, даже если задание "
        "не было создано в боте.\n\n"
        f"📊 <b>Ваша квота:</b>\n"
        f"├ Доступно: <b>{quota.remaining_checks}</b> проверок\n"
        f"├ Использовано: {quota.used_this_month}/{quota.monthly_limit}\n"
    )

    if quota.bonus_checks > 0:
        text += f"└ Бонусных: {quota.bonus_checks}\n"
    else:
        text += "└ До конца периода: " + quota.current_period_end.strftime("%d.%m.%Y") + "\n"

    text += f"\n📈 <b>За последние 30 дней:</b>\n"
    text += f"└ Проверено: {stats['total_checks']} работ\n"

    keyboard = [
        [InlineKeyboardButton("✅ Проверить одну работу", callback_data="qc_check_single")],
        [InlineKeyboardButton("📚 Массовая проверка", callback_data="qc_check_bulk")],
        [InlineKeyboardButton("📜 История проверок", callback_data="qc_history")],
        [InlineKeyboardButton("📊 Статистика", callback_data="qc_stats")],
        [InlineKeyboardButton("◀️ В меню учителя", callback_data="teacher_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_MENU


# ============================================
# Одиночная проверка
# ============================================

async def start_single_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало одиночной проверки - выбор типа задания"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Проверяем квоту
    quota = await quick_check_service.get_or_create_quota(user_id)
    if not quota or not quota.can_check:
        await query.message.edit_text(
            "❌ <b>Квота исчерпана</b>\n\n"
            f"Вы использовали все доступные проверки ({quota.monthly_limit if quota else 0}).\n\n"
            "💡 Обновите подписку или дождитесь начала нового периода.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.QUICK_CHECK_MENU

    text = (
        "🔍 <b>Проверка одной работы</b>\n\n"
        "Выберите тип задания для проверки:"
    )

    keyboard = [
        [InlineKeyboardButton("💡 Задание 19", callback_data="qc_type_task19")],
        [InlineKeyboardButton("⚙️ Задание 20", callback_data="qc_type_task20")],
        [InlineKeyboardButton("📊 Задание 24", callback_data="qc_type_task24")],
        [InlineKeyboardButton("💻 Задание 25", callback_data="qc_type_task25")],
        [InlineKeyboardButton("📝 Произвольное задание", callback_data="qc_type_custom")],
        [InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_SELECT_TYPE


async def select_task_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора типа задания"""
    query = update.callback_query
    await query.answer()

    # Извлекаем тип из callback_data
    task_type_str = query.data.replace("qc_type_", "")
    task_type = QuickCheckTaskType(task_type_str)

    # Сохраняем в контекст
    context.user_data['qc_task_type'] = task_type
    context.user_data['qc_mode'] = 'single'  # одиночная проверка

    task_names = {
        QuickCheckTaskType.TASK19: "💡 Задание 19 (рекурсивные алгоритмы)",
        QuickCheckTaskType.TASK20: "⚙️ Задание 20 (игры и стратегии)",
        QuickCheckTaskType.TASK24: "📊 Задание 24 (обработка файлов)",
        QuickCheckTaskType.TASK25: "💻 Задание 25 (программирование)",
        QuickCheckTaskType.CUSTOM: "📝 Произвольное задание"
    }

    text = (
        f"✏️ <b>{task_names[task_type]}</b>\n\n"
        "Введите условие задания текстом.\n\n"
        "Например:\n"
        "<i>«Дан файл с числами. Найдите количество пар чисел, "
        "сумма которых делится на 7»</i>\n\n"
        "💡 Можно скопировать текст задания откуда угодно."
    )

    keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_ENTER_CONDITION


async def process_task_condition(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка введенного условия задания"""
    user_id = update.effective_user.id
    condition = update.message.text.strip()

    # Валидация
    if len(condition) < 10:
        await update.message.reply_text(
            "❌ Условие задания слишком короткое. Минимум 10 символов.\n\n"
            "Попробуйте еще раз или /cancel для отмены."
        )
        return TeacherStates.QUICK_CHECK_ENTER_CONDITION

    if len(condition) > 5000:
        await update.message.reply_text(
            "❌ Условие задания слишком длинное. Максимум 5000 символов.\n\n"
            "Попробуйте сократить или /cancel для отмены."
        )
        return TeacherStates.QUICK_CHECK_ENTER_CONDITION

    # Сохраняем условие
    context.user_data['qc_condition'] = condition

    task_type = context.user_data.get('qc_task_type')
    mode = context.user_data.get('qc_mode', 'single')

    if mode == 'single':
        # Одиночная проверка - запрашиваем ответ ученика
        text = (
            "✅ Условие сохранено!\n\n"
            "Теперь введите <b>ответ ученика</b> на это задание.\n\n"
            "💡 Можно вставить ответ как текстом, так и числом."
        )

        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return TeacherStates.QUICK_CHECK_ENTER_ANSWER

    else:
        # Массовая проверка - запрашиваем ответы построчно
        text = (
            "✅ Условие сохранено!\n\n"
            "Теперь введите <b>ответы учеников</b> построчно.\n\n"
            "Каждая строка = ответ одного ученика.\n\n"
            "<b>Пример:</b>\n"
            "<code>145\n"
            "152\n"
            "148</code>\n\n"
            "Максимум 50 ответов за раз."
        )

        keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK


async def process_single_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ответа ученика и запуск проверки"""
    user_id = update.effective_user.id
    answer = update.message.text.strip()

    # Валидация
    if len(answer) < 1:
        await update.message.reply_text(
            "❌ Ответ не может быть пустым.\n\n"
            "Попробуйте еще раз или /cancel для отмены."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWER

    if len(answer) > 5000:
        await update.message.reply_text(
            "❌ Ответ слишком длинный. Максимум 5000 символов.\n\n"
            "Попробуйте сократить или /cancel для отмены."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWER

    # Извлекаем данные из контекста
    task_type = context.user_data.get('qc_task_type')
    condition = context.user_data.get('qc_condition')

    # Отправляем сообщение о начале проверки
    checking_msg = await update.message.reply_text(
        "⏳ Проверяю ответ с помощью AI...\n\n"
        "Это может занять несколько секунд."
    )

    # Проверяем и списываем квоту
    success, quota = await quick_check_service.check_and_use_quota(user_id, count=1)
    if not success:
        await checking_msg.edit_text(
            "❌ <b>Квота исчерпана</b>\n\n"
            "Не удалось выполнить проверку.",
            parse_mode='HTML'
        )
        return TeacherStates.QUICK_CHECK_MENU

    try:
        # Вызываем AI для проверки
        from teacher_mode.services.ai_homework_evaluator import evaluate_homework_answer

        # Создаем минимальный question_data для evaluator
        question_data = {
            'title': f'{task_type.value} - быстрая проверка',
            'task_text': condition
        }

        is_correct, ai_feedback = await evaluate_homework_answer(
            task_module=task_type.value,
            question_data=question_data,
            user_answer=answer,
            user_id=user_id
        )

        # Сохраняем проверку в БД
        quick_check = await quick_check_service.create_quick_check(
            teacher_id=user_id,
            task_type=task_type,
            task_condition=condition,
            student_answer=answer,
            ai_feedback=ai_feedback,
            is_correct=is_correct
        )

        # Формируем результат
        result_emoji = "✅" if is_correct else "❌"
        result_text = "Правильно" if is_correct else "Неправильно"

        text = (
            f"{result_emoji} <b>Результат проверки: {result_text}</b>\n\n"
            f"<b>Тип задания:</b> {task_type.value}\n\n"
            f"<b>Условие:</b>\n{condition[:200]}{'...' if len(condition) > 200 else ''}\n\n"
            f"<b>Ответ ученика:</b>\n<code>{answer[:200]}</code>\n\n"
            f"<b>🤖 AI обратная связь:</b>\n{ai_feedback}\n\n"
            f"💡 Осталось проверок: {quota.remaining_checks - 1}"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Проверить еще", callback_data="qc_check_single")],
            [InlineKeyboardButton("📊 Статистика", callback_data="qc_stats")],
            [InlineKeyboardButton("◀️ В меню", callback_data="quick_check_menu")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await checking_msg.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

        # Очищаем контекст
        context.user_data.pop('qc_task_type', None)
        context.user_data.pop('qc_condition', None)
        context.user_data.pop('qc_mode', None)

        return TeacherStates.QUICK_CHECK_MENU

    except Exception as e:
        logger.error(f"Error checking answer: {e}")

        await checking_msg.edit_text(
            "❌ <b>Ошибка при проверке</b>\n\n"
            "Произошла ошибка при обработке ответа. Попробуйте позже.\n\n"
            "Квота не была списана.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ В меню", callback_data="quick_check_menu")
            ]]),
            parse_mode='HTML'
        )

        # Возвращаем квоту
        await quick_check_service.add_bonus_checks(user_id, 1)

        return TeacherStates.QUICK_CHECK_MENU


# ============================================
# Массовая проверка
# ============================================

async def start_bulk_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало массовой проверки"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Проверяем квоту (минимум 2 проверки для массовой)
    quota = await quick_check_service.get_or_create_quota(user_id)
    if not quota or quota.remaining_checks < 2:
        await query.message.edit_text(
            "❌ <b>Недостаточно квоты</b>\n\n"
            f"Для массовой проверки нужно минимум 2 проверки.\n"
            f"Доступно: {quota.remaining_checks if quota else 0}\n\n"
            "💡 Используйте одиночную проверку или обновите подписку.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")
            ]]),
            parse_mode='HTML'
        )
        return TeacherStates.QUICK_CHECK_MENU

    text = (
        "📚 <b>Массовая проверка</b>\n\n"
        "Проверка нескольких ответов на одно задание.\n\n"
        "Выберите тип задания:"
    )

    keyboard = [
        [InlineKeyboardButton("💡 Задание 19", callback_data="qc_bulk_task19")],
        [InlineKeyboardButton("⚙️ Задание 20", callback_data="qc_bulk_task20")],
        [InlineKeyboardButton("📊 Задание 24", callback_data="qc_bulk_task24")],
        [InlineKeyboardButton("💻 Задание 25", callback_data="qc_bulk_task25")],
        [InlineKeyboardButton("📝 Произвольное", callback_data="qc_bulk_custom")],
        [InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_SELECT_TYPE


async def select_bulk_task_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора типа для массовой проверки"""
    query = update.callback_query
    await query.answer()

    task_type_str = query.data.replace("qc_bulk_", "")
    task_type = QuickCheckTaskType(task_type_str)

    context.user_data['qc_task_type'] = task_type
    context.user_data['qc_mode'] = 'bulk'

    task_names = {
        QuickCheckTaskType.TASK19: "💡 Задание 19",
        QuickCheckTaskType.TASK20: "⚙️ Задание 20",
        QuickCheckTaskType.TASK24: "📊 Задание 24",
        QuickCheckTaskType.TASK25: "💻 Задание 25",
        QuickCheckTaskType.CUSTOM: "📝 Произвольное"
    }

    text = (
        f"✏️ <b>{task_names[task_type]}</b>\n\n"
        "Введите условие задания текстом.\n\n"
        "Это условие будет общим для всех ответов."
    )

    keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data="quick_check_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_ENTER_CONDITION


async def process_bulk_answers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка массового ввода ответов"""
    user_id = update.effective_user.id
    answers_text = update.message.text.strip()

    # Разбиваем на строки
    answers = [line.strip() for line in answers_text.split('\n') if line.strip()]

    if len(answers) == 0:
        await update.message.reply_text(
            "❌ Не найдено ни одного ответа.\n\n"
            "Введите ответы построчно или /cancel для отмены."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK

    if len(answers) > 50:
        await update.message.reply_text(
            f"❌ Слишком много ответов ({len(answers)}).\n\n"
            "Максимум 50 ответов за раз. Попробуйте разбить на несколько запросов."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK

    # Проверяем квоту
    quota = await quick_check_service.get_or_create_quota(user_id)
    if not quota or quota.remaining_checks < len(answers):
        await update.message.reply_text(
            f"❌ Недостаточно квоты\n\n"
            f"Нужно: {len(answers)} проверок\n"
            f"Доступно: {quota.remaining_checks if quota else 0}\n\n"
            "Сократите количество ответов или обновите подписку."
        )
        return TeacherStates.QUICK_CHECK_ENTER_ANSWERS_BULK

    # Извлекаем данные
    task_type = context.user_data.get('qc_task_type')
    condition = context.user_data.get('qc_condition')

    checking_msg = await update.message.reply_text(
        f"⏳ Проверяю {len(answers)} ответов...\n\n"
        "Это может занять некоторое время."
    )

    try:
        from teacher_mode.services.ai_homework_evaluator import evaluate_homework_answer

        results = []
        correct_count = 0

        for i, answer in enumerate(answers):
            # Списываем квоту
            success, _ = await quick_check_service.check_and_use_quota(user_id, count=1)
            if not success:
                break

            # Проверяем ответ
            question_data = {
                'title': f'{task_type.value} - массовая проверка',
                'task_text': condition
            }

            is_correct, ai_feedback = await evaluate_homework_answer(
                task_module=task_type.value,
                question_data=question_data,
                user_answer=answer,
                user_id=user_id
            )

            # Сохраняем в БД
            await quick_check_service.create_quick_check(
                teacher_id=user_id,
                task_type=task_type,
                task_condition=condition,
                student_answer=answer,
                ai_feedback=ai_feedback,
                is_correct=is_correct
            )

            results.append({
                'answer': answer,
                'is_correct': is_correct,
                'feedback': ai_feedback
            })

            if is_correct:
                correct_count += 1

            # Обновляем прогресс
            if (i + 1) % 5 == 0:
                await checking_msg.edit_text(
                    f"⏳ Проверено {i + 1}/{len(answers)}..."
                )

        # Формируем результат
        accuracy = (correct_count / len(results) * 100) if results else 0

        text = (
            f"✅ <b>Массовая проверка завершена!</b>\n\n"
            f"📊 Проверено: {len(results)} ответов\n"
            f"✅ Правильных: {correct_count}\n"
            f"❌ Неправильных: {len(results) - correct_count}\n"
            f"📈 Точность: {accuracy:.1f}%\n\n"
            f"<b>Детализация:</b>\n\n"
        )

        # Показываем первые 10 результатов
        for i, result in enumerate(results[:10]):
            emoji = "✅" if result['is_correct'] else "❌"
            answer_preview = result['answer'][:30]
            text += f"{i+1}. {emoji} <code>{answer_preview}</code>\n"

        if len(results) > 10:
            text += f"\n... и еще {len(results) - 10} результатов\n"

        text += f"\n💡 Все результаты сохранены в истории."

        keyboard = [
            [InlineKeyboardButton("📜 Посмотреть историю", callback_data="qc_history")],
            [InlineKeyboardButton("📚 Еще массовая", callback_data="qc_check_bulk")],
            [InlineKeyboardButton("◀️ В меню", callback_data="quick_check_menu")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await checking_msg.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

        # Очищаем контекст
        context.user_data.pop('qc_task_type', None)
        context.user_data.pop('qc_condition', None)
        context.user_data.pop('qc_mode', None)

        return TeacherStates.QUICK_CHECK_MENU

    except Exception as e:
        logger.error(f"Error in bulk check: {e}")

        await checking_msg.edit_text(
            "❌ Ошибка при массовой проверке.\n\n"
            "Частично проверенные ответы сохранены.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ В меню", callback_data="quick_check_menu")
            ]]),
            parse_mode='HTML'
        )

        return TeacherStates.QUICK_CHECK_MENU


# ============================================
# История и статистика
# ============================================

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показ истории проверок"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем последние 10 проверок
    checks = await quick_check_service.get_teacher_quick_checks(
        teacher_id=user_id,
        limit=10,
        offset=0
    )

    if not checks:
        text = (
            "📜 <b>История проверок</b>\n\n"
            "У вас пока нет проверенных работ.\n\n"
            "Начните с кнопки «Проверить работу» в главном меню."
        )
    else:
        text = "📜 <b>История проверок (последние 10)</b>\n\n"

        for i, check in enumerate(checks):
            emoji = "✅" if check.is_correct else "❌"
            condition_preview = check.task_condition[:40]
            answer_preview = check.student_answer[:30]
            date = check.created_at.strftime("%d.%m %H:%M")

            text += (
                f"{i+1}. {emoji} {check.task_type.value}\n"
                f"   ├ {condition_preview}...\n"
                f"   ├ Ответ: <code>{answer_preview}</code>\n"
                f"   └ {date}\n\n"
            )

    keyboard = [
        [InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_MENU


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показ статистики проверок"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Получаем статистику
    stats = await quick_check_service.get_quick_check_stats(user_id, days=30)
    quota = stats.get('quota')

    text = (
        "📊 <b>Статистика проверок</b>\n\n"
        f"<b>За последние 30 дней:</b>\n"
        f"├ Всего проверок: {stats['total_checks']}\n"
        f"├ Правильных: {stats['correct_count']}\n"
        f"└ Точность: {stats['accuracy_rate']:.1f}%\n\n"
    )

    if quota:
        text += (
            f"<b>Квота:</b>\n"
            f"├ Месячный лимит: {quota['monthly_limit']}\n"
            f"├ Использовано: {quota['used_this_month']}\n"
            f"├ Осталось: {quota['remaining']}\n"
        )

        if quota['bonus_checks'] > 0:
            text += f"└ Бонусных: {quota['bonus_checks']}\n"

    if stats['task_distribution']:
        text += "\n<b>Распределение по типам:</b>\n"
        for task_type, count in stats['task_distribution'].items():
            text += f"├ {task_type}: {count}\n"

    keyboard = [
        [InlineKeyboardButton("◀️ Назад", callback_data="quick_check_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    return TeacherStates.QUICK_CHECK_MENU

