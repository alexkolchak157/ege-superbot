# features/test_part/quiz_handlers.py
from . import db
from . import utils
from . import keyboards
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import MessageHandler, filters
from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler, ContextTypes
)
from .states import (
    CHOOSING_INITIAL_ACTION,
    CHOOSING_BLOCK,
    CHOOSING_MODE,
    CHOOSING_TOPIC,
    CHOOSING_EXAM_NUMBER,
    ANSWERING,
    CHOOSING_NEXT_ACTION,
    REVIEWING_MISTAKES,
)

from .loader import QUESTIONS_DATA, AVAILABLE_BLOCKS

# --- Начало квиза (/quiz) ---
async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
    await update.message.reply_text(
        "Выберите блок тем для начала теста:",
        reply_markup=kb
    )
    return CHOOSING_BLOCK

async def entry_from_main_menu(update, context):
    """Вход из глобального меню («Тестовая часть»)."""
    q = update.callback_query
    await q.answer()

    from . import keyboards
    kb = keyboards.get_initial_choice_keyboard()

    try:
        # редактируем сообщение только если текст или клавиатура отличаются
        if q.message.text != "Выберите режим:" or q.message.reply_markup != kb:
            await q.message.edit_text("Выберите режим:", reply_markup=kb)
    except BadRequest as e:
        # игнорируем единственный «безобидный» случай
        if not str(e).startswith("Message is not modified"):
            raise

    return CHOOSING_MODE

# --- Выбор блока ---
async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_block = query.data.replace("block:", "")
    if selected_block not in AVAILABLE_BLOCKS:
        await query.answer("Некорректный блок.", show_alert=True)
        return CHOOSING_BLOCK

    context.user_data['selected_block'] = selected_block
    kb = keyboards.get_mode_keyboard(selected_block)
    await query.edit_message_text(
        f"Блок '{selected_block}' выбран. Выберите режим для этого блока:",
        reply_markup=kb
    )
    return CHOOSING_MODE

# --- Режим: случайный вопрос из блока ---
async def select_mode_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_block = context.user_data.get('selected_block')
    if not selected_block or selected_block not in QUESTIONS_DATA:
        kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
        await query.edit_message_text("Произошла ошибка. Выберите блок заново:", reply_markup=kb)
        return CHOOSING_BLOCK

    questions_in_block = []
    for topic_questions in QUESTIONS_DATA[selected_block].values():
        questions_in_block.extend(topic_questions)

    if not questions_in_block:
        kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
        await query.edit_message_text("В этом блоке пока нет вопросов. Выберите другой блок:", reply_markup=kb)
        return CHOOSING_BLOCK

    await query.edit_message_text("⏳ Загружаю случайный вопрос из блока...")
    question_data = await utils.choose_question(query.from_user.id, questions_in_block)
    if question_data:
        await utils.send_question(update, context, question_data, last_mode="random")
        # Здесь можно вернуть состояние ANSWERING, когда обработаем ответ пользователя
        # return ANSWERING
        # Пока оставим None для следующего шага
        return None
    else:
        kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
        await query.message.reply_text(
            f"Вы ответили на все вопросы в блоке '{selected_block}'! 🎉\nВыберите другой блок или режим:",
            reply_markup=kb
        )
        return CHOOSING_BLOCK

# --- Регистрация хэндлеров для ConversationHandler ---
def register_quiz_handlers(app):
    quiz_conv = ConversationHandler(
        entry_points=[
            CommandHandler("quiz", start_quiz),
            # ⬇️ новый entry – реагирует на кнопку из главного меню
            CallbackQueryHandler(entry_from_main_menu,
                                 pattern=r"^choose_test_part$"),
        ],
        states={
            CHOOSING_BLOCK: [
                CallbackQueryHandler(select_block, pattern=r'^block:.+')
            ],
            CHOOSING_MODE: [
                CallbackQueryHandler(select_mode_random, pattern=r'^mode:random$'),
                CallbackQueryHandler(select_mode_topic, pattern=r'^mode:choose_topic$'),
                CallbackQueryHandler(select_mode_exam_number, pattern=r'^mode:choose_exam_num$'),
            ],
            CHOOSING_TOPIC: [
                CallbackQueryHandler(select_topic, pattern=r'^topic:.+')
            ],
            CHOOSING_EXAM_NUMBER: [
                CallbackQueryHandler(select_exam_number, pattern=r'^examnum:\d+$')
            ],
            ANSWERING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer)
            ],
            CHOOSING_NEXT_ACTION: [
                CallbackQueryHandler(handle_next_action, pattern="^(next_random|next_topic|change_topic|to_menu)$"),
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cmd_cancel),
            CallbackQueryHandler(to_menu, pattern="^to_menu$"),
        ],
        allow_reentry=True
    )
    app.add_handler(quiz_conv, group=1)

# Выбор режима "по теме"
async def select_mode_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_block = context.user_data.get('selected_block')
    if not selected_block or selected_block not in QUESTIONS_DATA:
        kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
        await query.edit_message_text("Произошла ошибка. Выберите блок заново:", reply_markup=kb)
        return CHOOSING_BLOCK

    topic_codes = list(QUESTIONS_DATA.get(selected_block, {}).keys())
    topics_sorted = sorted(topic_codes, key=utils.sort_key_topic_code)
    kb = keyboards.get_topics_keyboard(selected_block, topics_sorted)
    await query.edit_message_text(
        "Выберите тему:",
        reply_markup=kb
    )
    return CHOOSING_TOPIC
async def select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected_topic = query.data.replace("topic:", "")
    selected_block = context.user_data.get('selected_block')
    if not selected_block or selected_block not in QUESTIONS_DATA:
        kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
        await query.edit_message_text("Ошибка выбора блока. Начните заново:", reply_markup=kb)
        return CHOOSING_BLOCK
    if selected_topic not in QUESTIONS_DATA[selected_block]:
        kb = keyboards.get_topics_keyboard(selected_block, sorted(list(QUESTIONS_DATA[selected_block].keys()), key=utils.sort_key_topic_code))
        await query.edit_message_text("Ошибка выбора темы. Выберите из списка:", reply_markup=kb)
        return CHOOSING_TOPIC

    questions_in_topic = QUESTIONS_DATA[selected_block][selected_topic]
    await query.edit_message_text(f"⏳ Загружаю вопрос по теме {selected_topic}...")
    question_data = await utils.choose_question(query.from_user.id, questions_in_topic)
    if question_data:
        await utils.send_question(update, context, question_data, last_mode="topic")
        # return ANSWERING  # если реализуешь обработку ответов
        return None
    else:
        kb = keyboards.get_topics_keyboard(selected_block, sorted(list(QUESTIONS_DATA[selected_block].keys()), key=utils.sort_key_topic_code))
        await query.message.reply_text(
            f"Вы ответили на все вопросы в теме {selected_topic}! 🎉\nВыберите другую тему:",
            reply_markup=kb
        )
        return CHOOSING_TOPIC
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_answer = update.message.text.strip()
    question_data = context.user_data.get('current_question')
    last_mode = context.user_data.get('last_mode', 'random')

    # Проверка, что есть вопрос
    if not question_data:
        await update.message.reply_text("Что-то пошло не так. Попробуйте начать заново с /quiz.")
        return ConversationHandler.END

    # Получаем правильный ответ и тип
    correct_answer = str(question_data.get("answer", "")).strip()
    question_type = utils.get_question_type(question_data)
    norm_user = utils.normalize_answer(user_answer, question_type)
    norm_correct = utils.normalize_answer(correct_answer, question_type)
    is_correct = norm_user == norm_correct

    # Фидбек пользователю
    if is_correct:
        await update.message.reply_text(utils.get_random_correct_phrase())
        # Обновляем streak, прогресс, убираем вопрос из mistakes и т.д.
        await db.update_correct_streak(user_id)
        await db.update_daily_streak(user_id)
        await db.mark_answered_question(user_id, question_data["id"])
        await db.delete_mistake(user_id, question_data["id"])
    else:
        await update.message.reply_text(
            utils.get_random_incorrect_phrase() +
            f"\nПравильный ответ: {correct_answer}"
        )
        await db.reset_correct_streak(user_id)
        await db.add_mistake(user_id, question_data["id"])

    # После ответа предлагаем следующий шаг (выбрать "ещё", "другую тему", "в меню" и т.д.)
    kb = keyboards.get_after_answer_keyboard(last_mode)
    await update.message.reply_text("Что дальше?", reply_markup=kb)
    return CHOOSING_NEXT_ACTION

async def handle_next_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    last_mode = context.user_data.get("last_mode", "random")
    selected_block = context.user_data.get("selected_block")
    selected_topic = None

    # Для mode: topic сохраняй выбранную тему
    if last_mode == "topic":
        selected_topic = context.user_data.get("current_question", {}).get("topic")

    data = query.data
    # "Ещё случайный вопрос"
    if data == "next_random":
        # Повторяем режим случайного в текущем блоке
        questions_in_block = []
        for topic_questions in QUESTIONS_DATA[selected_block].values():
            questions_in_block.extend(topic_questions)
        question_data = await utils.choose_question(query.from_user.id, questions_in_block)
        if question_data:
            await utils.send_question(update, context, question_data, last_mode="random")
            return ANSWERING
        else:
            kb = keyboards.get_blocks_keyboard(AVAILABLE_BLOCKS)
            await query.message.reply_text(
                f"В этом блоке закончились вопросы! Выберите другой блок:",
                reply_markup=kb
            )
            return CHOOSING_BLOCK

    # "Ещё по теме"
    elif data == "next_topic" and selected_block and selected_topic:
        questions_in_topic = QUESTIONS_DATA[selected_block][selected_topic]
        question_data = await utils.choose_question(query.from_user.id, questions_in_topic)
        if question_data:
            await utils.send_question(update, context, question_data, last_mode="topic")
            return ANSWERING
        else:
            kb = keyboards.get_topics_keyboard(selected_block, sorted(list(QUESTIONS_DATA[selected_block].keys()), key=utils.sort_key_topic_code))
            await query.message.reply_text(
                f"В теме закончились вопросы! Выберите другую тему:",
                reply_markup=kb
            )
            return CHOOSING_TOPIC

    # "Другая тема"
    elif data == "change_topic" and selected_block:
        topics_sorted = sorted(QUESTIONS_DATA[selected_block].keys(), key=utils.sort_key_topic_code)
        kb = keyboards.get_topics_keyboard(selected_block, topics_sorted)
        await query.message.reply_text(
            "Выберите тему:",
            reply_markup=kb
        )
        return CHOOSING_TOPIC

    # "Главное меню"
    elif data == "to_menu":
        kb = keyboards.get_initial_choice_keyboard()
        await query.message.reply_text(
            "Главное меню. Выберите режим:",
            reply_markup=kb
        )
        return CHOOSING_BLOCK  # Или CHOOSING_INITIAL_ACTION, если у тебя реализовано это состояние

    else:
        await query.answer("Неизвестное действие. Начните сначала с /quiz.", show_alert=True)
        return ConversationHandler.END

async def select_mode_exam_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Собираем все уникальные номера
    all_nums = set()
    for block in QUESTIONS_DATA.values():
        for topic_qs in block.values():
            for q in topic_qs:
                num = q.get("exam_number")
                if isinstance(num, int):
                    all_nums.add(num)
    if not all_nums:
        await query.answer("В базе нет вопросов с номерами ЕГЭ.", show_alert=True)
        return CHOOSING_MODE
    kb = keyboards.get_exam_number_keyboard(sorted(all_nums))
    await query.edit_message_text(
        "Выберите номер задания ЕГЭ:", reply_markup=kb
    )
    return CHOOSING_EXAM_NUMBER

async def select_exam_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    num = query.data.replace("examnum:", "")
    try:
        exam_number = int(num)
    except ValueError:
        await query.answer("Некорректный номер.", show_alert=True)
        return CHOOSING_EXAM_NUMBER

    # Собираем все вопросы с этим номером
    questions_with_num = []
    for block in QUESTIONS_DATA.values():
        for topic_qs in block.values():
            for q in topic_qs:
                if q.get("exam_number") == exam_number:
                    questions_with_num.append(q)
    if not questions_with_num:
        await query.answer("Нет вопросов с этим номером.", show_alert=True)
        return CHOOSING_EXAM_NUMBER

    await query.edit_message_text(f"⏳ Загружаю вопрос №{exam_number}…")
    question_data = await utils.choose_question(query.from_user.id, questions_with_num)
    if question_data:
        await utils.send_question(update, context, question_data, last_mode="exam_number")
        return ANSWERING
    else:
        await query.message.reply_text(
            f"Вы ответили на все вопросы с этим номером! Выберите другой:",
            reply_markup=keyboards.get_exam_number_keyboard(sorted(set(
                q.get("exam_number") for block in QUESTIONS_DATA.values() for topic in block.values() for q in topic if isinstance(q.get("exam_number"), int)
            )))
        )
        return CHOOSING_EXAM_NUMBER

async def to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query if update.callback_query else None
    kb = keyboards.get_initial_choice_keyboard()
    if query:
        await query.answer()
        await query.message.edit_text("Главное меню. Выберите режим:", reply_markup=kb)
    else:
        await update.message.reply_text("Главное меню. Выберите режим:", reply_markup=kb)
    return CHOOSING_BLOCK  # Или CHOOSING_INITIAL_ACTION, если меню отдельное

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = keyboards.get_initial_choice_keyboard()
    if update.message:
        await update.message.reply_text(
            "Текущее действие отменено. Выберите режим:",
            reply_markup=kb
        )
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.message.edit_text(
            "Текущее действие отменено. Выберите режим:",
            reply_markup=kb
        )
    return CHOOSING_BLOCK  # Или CHOOSING_INITIAL_ACTION

__all__ = [
    'register_quiz_handlers',
    # другие публичные функции, если потребуется
]
