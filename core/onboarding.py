"""
Интерактивный onboarding для новых пользователей.

Цель: Превратить 77% bounced пользователей в активных.

Сценарий:
1. Приветствие + объяснение что такое бот
2. 3 простых вопроса из тестовой части (принудительно)
3. Демо AI-проверки задания 24/25
4. Предложение trial за 1₽
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from telegram.constants import ParseMode
from datetime import datetime
from core import db

logger = logging.getLogger(__name__)

# Состояния onboarding
ONBOARDING_WELCOME = 0
ONBOARDING_QUESTION_1 = 1
ONBOARDING_QUESTION_2 = 2
ONBOARDING_QUESTION_3 = 3
ONBOARDING_AI_DEMO = 4
ONBOARDING_TRIAL_OFFER = 5

# Простые демо-вопросы для onboarding
DEMO_QUESTIONS = [
    {
        "id": "demo_1",
        "question": "🎯 <b>Вопрос 1 из 3</b>\n\n<b>Что такое социализация?</b>",
        "options": [
            "A) Процесс усвоения социальных норм",
            "B) Общение с друзьями",
            "C) Поиск работы",
            "D) Учеба в школе"
        ],
        "correct": 0,
        "explanation": "✅ <b>Правильно!</b>\n\nСоциализация — это процесс усвоения индивидом социальных норм, ценностей и моделей поведения."
    },
    {
        "id": "demo_2",
        "question": "🎯 <b>Вопрос 2 из 3</b>\n\n<b>К какой сфере общества относятся банки?</b>",
        "options": [
            "A) Политическая",
            "B) Экономическая",
            "C) Социальная",
            "D) Духовная"
        ],
        "correct": 1,
        "explanation": "✅ <b>Правильно!</b>\n\nБанки относятся к экономической сфере — они управляют финансами и кредитами."
    },
    {
        "id": "demo_3",
        "question": "🎯 <b>Вопрос 3 из 3</b>\n\n<b>Что НЕ является признаком государства?</b>",
        "options": [
            "A) Территория",
            "B) Суверенитет",
            "C) Общий язык",
            "D) Налоги"
        ],
        "correct": 2,
        "explanation": "✅ <b>Правильно!</b>\n\nОбщий язык не обязателен для государства. Например, в Швейцарии 4 государственных языка."
    }
]


async def should_start_onboarding(user_id: int) -> bool:
    """
    Проверяет, нужен ли onboarding пользователю.

    Критерии:
    - Пользователь новый (< 1 дня с регистрации)
    - Не решил ни одного вопроса
    - Не проходил onboarding ранее
    """
    try:
        # Проверяем, проходил ли уже onboarding
        user_data = await db.get_user_data(user_id)
        if user_data and user_data.get('onboarding_completed'):
            return False

        # Проверяем количество ответов
        conn = await db.get_connection()
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM answered_questions WHERE user_id = ?",
            (user_id,)
        )
        answer_count = (await cursor.fetchone())[0]

        # Если уже решал вопросы - onboarding не нужен
        if answer_count > 0:
            return False

        # Проверяем дату регистрации
        cursor = await conn.execute(
            "SELECT first_seen FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()

        if row and row[0]:
            first_seen = datetime.fromisoformat(row[0])
            days_since_registration = (datetime.now() - first_seen).days

            # Onboarding только для совсем новых (< 7 дней)
            return days_since_registration < 7

        return True  # Новый пользователь

    except Exception as e:
        logger.error(f"Error checking onboarding status for user {user_id}: {e}")
        return False


async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало onboarding процесса."""
    user = update.effective_user
    user_name = user.first_name or "друг"

    # Сохраняем метку начала onboarding
    context.user_data['onboarding_started'] = datetime.now().isoformat()
    context.user_data['onboarding_correct_answers'] = 0

    welcome_text = f"""👋 <b>Привет, {user_name}!</b>

🎓 Я — твой ИИ-репетитор по обществознанию.

<b>За 2 минуты я покажу тебе как:</b>
✅ Решать тестовую часть ЕГЭ
✅ Получать проверку от ИИ как от эксперта ФИПИ
✅ Готовиться эффективно и бесплатно

📊 <b>Прямо сейчас решим 3 простых вопроса</b>
Не переживай — это займет меньше минуты!

<i>Нажми "Поехали!" когда будешь готов</i>
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Поехали!", callback_data="onboarding_start")],
        [InlineKeyboardButton("Пропустить обучение", callback_data="onboarding_skip")]
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            welcome_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            welcome_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    return ONBOARDING_WELCOME


async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE, question_num: int):
    """Показывает вопрос из onboarding."""
    query = update.callback_query
    await query.answer()

    question_data = DEMO_QUESTIONS[question_num]
    context.user_data['current_question'] = question_num

    # Формируем текст с вариантами
    text = question_data['question'] + "\n\n"

    # Создаем кнопки для ответов
    keyboard = []
    for i, option in enumerate(question_data['options']):
        keyboard.append([
            InlineKeyboardButton(
                option,
                callback_data=f"onboarding_answer_{question_num}_{i}"
            )
        ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

    # Возвращаем соответствующее состояние
    return ONBOARDING_QUESTION_1 + question_num


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа на вопрос."""
    query = update.callback_query
    await query.answer()

    # Парсим callback_data
    _, _, question_num_str, answer_str = query.data.split('_')
    question_num = int(question_num_str)
    answer = int(answer_str)

    question_data = DEMO_QUESTIONS[question_num]
    is_correct = answer == question_data['correct']

    if is_correct:
        context.user_data['onboarding_correct_answers'] = \
            context.user_data.get('onboarding_correct_answers', 0) + 1

    # Показываем объяснение
    text = question_data['explanation']

    if question_num < 2:
        # Еще есть вопросы
        text += f"\n\n📊 <b>Правильных ответов: {context.user_data['onboarding_correct_answers']}/{question_num + 1}</b>"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➡️ Следующий вопрос", callback_data=f"onboarding_next_{question_num + 1}")]
        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        return ONBOARDING_QUESTION_1 + question_num
    else:
        # Все вопросы решены - переходим к AI demo
        correct_count = context.user_data.get('onboarding_correct_answers', 0)

        text += f"\n\n🎉 <b>Отлично! Ты решил все 3 вопроса!</b>"
        text += f"\n📊 Правильных: {correct_count}/3"

        if correct_count == 3:
            text += "\n\n⭐ <b>Идеальный результат!</b> У тебя отличный потенциал!"
        elif correct_count >= 2:
            text += "\n\n👍 <b>Хорошо!</b> Ещё немного практики — и будешь профи!"
        else:
            text += "\n\n💪 <b>Неплохо для начала!</b> Практика поможет улучшить результат!"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Покажи что умеет ИИ", callback_data="onboarding_ai_demo")]
        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        return ONBOARDING_AI_DEMO


async def start_first_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает первый вопрос onboarding."""
    return await show_question(update, context, 0)


async def show_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к следующему вопросу."""
    query = update.callback_query
    question_num = int(query.data.split('_')[-1])

    return await show_question(update, context, question_num)


async def show_ai_demo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает демо AI-проверки."""
    query = update.callback_query
    await query.answer()

    demo_text = """🤖 <b>ИИ-проверка — твой секретный инструмент</b>

Задания второй части (19-25) проверяет не просто программа, а <b>искусственный интеллект</b> обученный на критериях ФИПИ.

<b>Вот реальный пример:</b>

📝 <b>Задание 24: Составить план по теме "Семья"</b>

❌ <b>Ответ ученика (2 балла):</b>
1. Что такое семья
2. Виды семей
3. Функции семьи

🤖 <b>Оценка ИИ:</b>
"<i>План слишком общий. Не хватает конкретизации и примеров. По критериям ФИПИ — 2 из 4 баллов.</i>"

✅ <b>После улучшения (4 балла):</b>
1. Семья как социальный институт
   а) Определение семьи
   б) Брак как основа семьи
2. Типы семейных структур
   а) Нуклеарная семья
   б) Расширенная семья
3. Функции семьи в обществе
   а) Репродуктивная функция
   б) Социализация детей
   в) Экономическая поддержка

💎 <b>Результат: +2 балла на ЕГЭ!</b>

<b>Попробуй прямо сейчас:</b>
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Активировать пробный период (1₽)", callback_data="onboarding_trial")],
        [InlineKeyboardButton("🆓 Продолжить с бесплатным доступом", callback_data="onboarding_complete")]
    ])

    await query.edit_message_text(
        demo_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return ONBOARDING_TRIAL_OFFER


async def handle_trial_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора trial."""
    query = update.callback_query
    await query.answer()

    trial_text = """🎁 <b>Пробный период за 1 рубль</b>

<b>Что получишь на 7 дней:</b>
✅ Безлимитные ИИ-проверки заданий 19-25
✅ Персональные рекомендации по каждому ответу
✅ Эталонные примеры ответов
✅ Доступ ко всем тренировочным модулям

💰 <b>Стоимость:</b> всего 1₽ (вместо 249₽)

⏰ <b>Почему так дёшево?</b>
Мы хотим, чтобы ты попробовал и убедился в качестве. После пробного периода — от 249₽/мес.

🔒 <b>Безопасно:</b> оплата через Тинькофф

<b>Активировать пробный период?</b>
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Оплатить 1₽", callback_data="subscribe_trial_7days")],
        [InlineKeyboardButton("⬅️ Назад к бесплатному", callback_data="onboarding_complete")]
    ])

    await query.edit_message_text(
        trial_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return ONBOARDING_TRIAL_OFFER


async def complete_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение onboarding."""
    query = update.callback_query
    await query.answer("🎉 Отлично! Теперь ты готов к подготовке!")

    user_id = update.effective_user.id

    # Сохраняем метку завершения onboarding
    try:
        conn = await db.get_connection()
        await conn.execute(
            """UPDATE users
               SET onboarding_completed = 1,
                   onboarding_completed_at = datetime('now')
               WHERE user_id = ?""",
            (user_id,)
        )
        await conn.commit()

        # Трекинг для аналитики
        await db.track_funnel_event(user_id, 'onboarding_completed', {
            'correct_answers': context.user_data.get('onboarding_correct_answers', 0),
            'duration_seconds': (
                datetime.now() - datetime.fromisoformat(context.user_data.get('onboarding_started', datetime.now().isoformat()))
            ).seconds
        })

    except Exception as e:
        logger.error(f"Error completing onboarding for user {user_id}: {e}")

    completion_text = """🎓 <b>Обучение завершено!</b>

Теперь ты готов к подготовке! Вот что доступно:

🆓 <b>БЕСПЛАТНО навсегда:</b>
• Тестовая часть (задания 1-16)
• 3 ИИ-проверки в день для заданий 19-25
• Трекинг прогресса

💎 <b>ПОДПИСКА (от 249₽/мес):</b>
• Безлимитные ИИ-проверки заданий 19-25
• Подробный разбор каждого ответа
• Эталонные примеры решений

👇 <b>Выбери раздел:</b>
"""

    # Получаем главное меню
    from core.app import show_main_menu_with_access
    keyboard = await show_main_menu_with_access(context, user_id)

    await query.edit_message_text(
        completion_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    # Очищаем данные onboarding
    context.user_data.pop('onboarding_started', None)
    context.user_data.pop('onboarding_correct_answers', None)
    context.user_data.pop('current_question', None)

    return ConversationHandler.END


async def skip_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск onboarding."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Отмечаем, что пользователь пропустил
    try:
        conn = await db.get_connection()
        await conn.execute(
            """UPDATE users
               SET onboarding_completed = 1,
                   onboarding_skipped = 1,
                   onboarding_completed_at = datetime('now')
               WHERE user_id = ?""",
            (user_id,)
        )
        await conn.commit()

        # Трекинг
        await db.track_funnel_event(user_id, 'onboarding_skipped')

    except Exception as e:
        logger.error(f"Error skipping onboarding for user {user_id}: {e}")

    skip_text = """⏭️ <b>Обучение пропущено</b>

Ничего страшного! Ты всегда можешь вернуться к нему через /start

👇 <b>Выбери раздел для подготовки:</b>
"""

    from core.app import show_main_menu_with_access
    keyboard = await show_main_menu_with_access(context, user_id)

    await query.edit_message_text(
        skip_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return ConversationHandler.END


async def skip_onboarding_before_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск onboarding до начала ConversationHandler."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Отмечаем, что пользователь пропустил
    try:
        conn = await db.get_connection()
        await conn.execute(
            """UPDATE users
               SET onboarding_completed = 1,
                   onboarding_skipped = 1,
                   onboarding_completed_at = datetime('now')
               WHERE user_id = ?""",
            (user_id,)
        )
        await conn.commit()

        # Трекинг
        await db.track_funnel_event(user_id, 'onboarding_skipped')

    except Exception as e:
        logger.error(f"Error skipping onboarding for user {user_id}: {e}")

    skip_text = """⏭️ <b>Обучение пропущено</b>

Ничего страшного! Ты всегда можешь вернуться к нему через /start

👇 <b>Выбери раздел для подготовки:</b>
"""

    from core.app import show_main_menu_with_access
    keyboard = await show_main_menu_with_access(context, user_id)

    await query.edit_message_text(
        skip_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


def get_onboarding_handler():
    """Возвращает ConversationHandler для onboarding."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_onboarding, pattern="^start_onboarding$")
        ],
        states={
            ONBOARDING_WELCOME: [
                CallbackQueryHandler(start_first_question, pattern="^onboarding_start$"),
                CallbackQueryHandler(skip_onboarding, pattern="^onboarding_skip$")
            ],
            ONBOARDING_QUESTION_1: [
                CallbackQueryHandler(handle_answer, pattern="^onboarding_answer_"),
                CallbackQueryHandler(show_next_question, pattern="^onboarding_next_")
            ],
            ONBOARDING_QUESTION_2: [
                CallbackQueryHandler(handle_answer, pattern="^onboarding_answer_"),
                CallbackQueryHandler(show_next_question, pattern="^onboarding_next_")
            ],
            ONBOARDING_QUESTION_3: [
                CallbackQueryHandler(handle_answer, pattern="^onboarding_answer_")
            ],
            ONBOARDING_AI_DEMO: [
                CallbackQueryHandler(show_ai_demo, pattern="^onboarding_ai_demo$"),
                CallbackQueryHandler(complete_onboarding, pattern="^onboarding_complete$")
            ],
            ONBOARDING_TRIAL_OFFER: [
                CallbackQueryHandler(handle_trial_offer, pattern="^onboarding_trial$"),
                CallbackQueryHandler(complete_onboarding, pattern="^onboarding_complete$")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", skip_onboarding)
        ],
        name="onboarding",
        persistent=True
    )
