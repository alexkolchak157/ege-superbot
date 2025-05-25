import logging
from typing import List, Dict, Any, Optional

from telegram import Update, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
)

from . import db
from . import utils
from . import keyboards

from .keyboards import get_initial_choice_keyboard, get_mistakes_nav_keyboard
from .states import (
    CHOOSING_INITIAL_ACTION,
    CHOOSING_BLOCK,
    CHOOSING_MODE,
    CHOOSING_TOPIC,
    CHOOSING_EXAM_NUMBER,
    ANSWERING,
    CHOOSING_NEXT_ACTION,
    REVIEWING_MISTAKES,
    QuizState,
)

# --- Вспомогательная функция: отправка вопроса из режима ошибок ---
async def send_mistake_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    data = context.user_data
    mistake_ids: List[str] = data.get("mistake_ids", [])
    current_index: int = data.get("current_mistake_index", 0)
    user_id = update.effective_user.id

    # Завершение, если ошибок нет
    if not mistake_ids or current_index >= len(mistake_ids):
        await update.message.reply_text("🎉 Вы проработали все ошибки! Отличная работа!", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return ConversationHandler.END

    question_id = mistake_ids[current_index]
    question_data = utils.find_question_by_id(question_id)

    # Вопрос не найден — пропустить
    if not question_data:
        await update.message.reply_text(f"Не удалось найти данные для вопроса (ID: {question_id}). Пропускаем.", reply_markup=ReplyKeyboardRemove())
        await db.delete_mistake(user_id, question_id)
        mistake_ids = [mid for mid in mistake_ids if mid != question_id]
        context.user_data["mistake_ids"] = mistake_ids
        # Индекс не увеличиваем — "перепрыгнем" к текущему (или end, если всё)
        return await send_mistake_question(update, context)

    # Получаем тип вопроса и ответ
    question_type = utils.get_question_type(question_data)
    correct_answer = str(question_data.get("answer", ""))

    if question_type == "unknown" or correct_answer is None:
        await update.message.reply_text(f"Проблема с вопросом ID {question_id}. Пропускаем.")
        await db.delete_mistake(user_id, question_id)
        mistake_ids = [mid for mid in mistake_ids if mid != question_id]
        context.user_data["mistake_ids"] = mistake_ids
        return await send_mistake_question(update, context)

    # Сохраняем в user_data
    context.user_data.update(
        current_mistake_question_id=question_id,
        current_mistake_correct_answer=correct_answer,
        current_mistake_question_type=question_type,
    )

    # Формируем текст вопроса
    question_text_raw = question_data.get("question", "Текст вопроса отсутствует.")
    block = question_data.get("block", "N/A")
    topic = question_data.get("topic", "N/A")
    topic_display_name = utils.TOPIC_NAMES.get(topic, topic)
    header = f"🔧 <b>Работа над ошибками ({current_index + 1} из {len(mistake_ids)})</b>\n"
    header += f"📚 Блок: <b>{block}</b>, 🏷️ Тема: <b>{topic}. {topic_display_name}</b>\n" + "➖"*10 + "\n\n"

    parts = question_text_raw.split('\n', 1)
    instruction = parts[0].strip()
    options_part = parts[1].strip() if len(parts) > 1 else ""
    formatted_text = header + f"❓ <b>{instruction}</b>\n\n"
    formatted_options, first_column_letters = utils.format_question_options(options_part, question_type)
    if formatted_options:
        formatted_text += formatted_options + "\n"

    # Подсказка для ввода
    if question_type == "matching" and first_column_letters:
        letters_str = " ".join(first_column_letters)
        prompt = f"\n{letters_str}\n✍️ Введите {len(first_column_letters)} цифр ответа без пробелов (например, 12345):"
    elif question_type == "multiple_choice":
        prompt = "\n✍️ Введите цифры верных ответов без пробелов (например, 135):"
    elif question_type == "single_choice":
        prompt = "\n✍️ Введите одну цифру верного ответа:"
    elif question_type == "sequence":
        prompt = "\n✍️ Введите цифры в правильной последовательности без пробелов (например, 312):"
    else:
        prompt = "\n✍️ Введите ваш ответ:"
    formatted_text += prompt

    await update.message.reply_text(formatted_text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    return REVIEWING_MISTAKES

# --- Обработчик команды /mistakes ---
async def cmd_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    mistake_ids = await db.get_mistake_ids(user_id)
    if not mistake_ids:
        await update.message.reply_text("👍 У вас нет ошибок для повторения!")
        return ConversationHandler.END
    context.user_data["mistake_ids"] = list(mistake_ids)
    context.user_data["current_mistake_index"] = 0
    await update.message.reply_text(f"Начинаем работу над ошибками. Всего найдено: {len(mistake_ids)}.", reply_markup=ReplyKeyboardRemove())
    return await send_mistake_question(update, context)

# --- Обработчик ответа в режиме ошибок ---
async def handle_mistake_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_answer_raw = update.message.text
    data = context.user_data
    correct_answer = data.get("current_mistake_correct_answer")
    question_id = data.get("current_mistake_question_id")
    question_type = data.get("current_mistake_question_type")
    mistake_ids: List[str] = data.get("mistake_ids", [])
    current_index: int = data.get("current_mistake_index", 0)

    if not correct_answer or not question_id or not question_type:
        await update.message.reply_text("Ошибка состояния 😕. Пожалуйста, начните сначала с /start")
        context.user_data.clear()
        return ConversationHandler.END

    # Проверка формата
    if question_type in ["single_choice", "multiple_choice", "matching", "sequence"]:
        cleaned_input = user_answer_raw.strip().replace(" ", "").replace(",", "")
        if not cleaned_input.isdigit():
            await update.message.reply_text("Пожалуйста, введите ответ, используя только цифры.")
            return REVIEWING_MISTAKES

    is_correct = utils.normalize_answer(user_answer_raw, question_type) == utils.normalize_answer(correct_answer, question_type)

    # Собираем клавиатуру
    current_question_data = utils.find_question_by_id(question_id)
    explanation = current_question_data.get("explanation") if current_question_data else None
    buttons = []
    if explanation:
        buttons.append([InlineKeyboardButton("💡 Пояснение", callback_data="show_explanation")])
    buttons.append([InlineKeyboardButton("➡️ След. ошибка", callback_data="next_mistake")])
    buttons.append([InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_mistake")])
    buttons.append([InlineKeyboardButton("❌ Закончить", callback_data="exit_mistakes")])
    kb = InlineKeyboardMarkup(buttons)

    if is_correct:
        feedback_text = utils.get_random_correct_phrase() + " Ошибка исправлена."
        await db.delete_mistake(user_id, question_id)
        if 0 <= current_index < len(mistake_ids) and mistake_ids[current_index] == question_id:
            mistake_ids.pop(current_index)
        context.user_data["mistake_ids"] = mistake_ids
    else:
        feedback_text = f"{utils.get_random_incorrect_phrase()}\nПравильный ответ: <b>{correct_answer}</b>"
        context.user_data["current_mistake_index"] = current_index + 1
    await update.message.reply_text(feedback_text, reply_markup=kb, parse_mode="HTML")
    return REVIEWING_MISTAKES

# --- Обработка кнопки пояснения ---
async def cq_mistake_show_explanation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    question_id = context.user_data.get("current_mistake_question_id")
    if not question_id:
        await query.message.reply_text("Ошибка, вопрос не найден.")
        return REVIEWING_MISTAKES
    question_data = utils.find_question_by_id(question_id)
    explanation = question_data.get("explanation") if question_data else None
    if explanation:
        await query.message.reply_text(f"💬 <b>Пояснение к вопросу</b> (ID: <code>{question_id}</code>)\n\n{explanation}", parse_mode="HTML")
    else:
        await query.message.reply_text("К этому вопросу пока нет пояснения.")
    return REVIEWING_MISTAKES

# --- Навигация по ошибкам (следующий, пропуск, выход) ---
async def cq_next_mistake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["current_mistake_index"] = context.user_data.get("current_mistake_index", 0)
    return await send_mistake_question(query, context)

async def cq_skip_mistake(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Вопрос пропущен")
    context.user_data["current_mistake_index"] = context.user_data.get("current_mistake_index", 0) + 1
    return await send_mistake_question(query, context)

async def cq_exit_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    kb = get_initial_choice_keyboard()
    await query.message.reply_text("Выход из режима работы над ошибками.\nВыберите режим:", reply_markup=kb)
    return ConversationHandler.END

# --- ConversationHandler для режима ошибок ---
def register_mistakes_handlers(app):
    conv = ConversationHandler(
        entry_points=[CommandHandler("mistakes", cmd_mistakes)],
        states={
            REVIEWING_MISTAKES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_mistake_answer),
                CallbackQueryHandler(cq_mistake_show_explanation, pattern="^show_explanation$"),
                CallbackQueryHandler(cq_next_mistake, pattern="^next_mistake$"),
                CallbackQueryHandler(cq_skip_mistake, pattern="^skip_mistake$"),
                CallbackQueryHandler(cq_exit_mistakes, pattern="^exit_mistakes$"),
            ]
        },
        fallbacks=[],
        allow_reentry=True,
    )
    app.add_handler(conv)
