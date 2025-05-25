import random
import re
import logging
from typing import List, Tuple, Dict, Any, Optional, Set

from telegram import Update
from telegram.ext import ContextTypes

from .config import REQUIRED_CHANNEL
from .import db
from .import keyboards

try:
    from .topic_data import TOPIC_NAMES
except ImportError:
    logging.error("Не найден файл topic_data.py или словарь TOPIC_NAMES в нем.")
    TOPIC_NAMES = {}

from .loader import QUESTIONS_DATA

# --- Фразы и эмодзи ---
CORRECT_ANSWERS_PHRASES = [
    "✅ Правильно!", "✅ Отлично!", "✅ Верно!", "✅ Так держать!", "✅ Превосходно!"
]
INCORRECT_ANSWERS_PHRASES = [
    "❌ Увы, неверно.", "❌ Ошибка.", "❌ Неправильно.", "❌ Стоит повторить.", "❌ Не совсем так."
]
DIGIT_EMOJIS = {
    '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣', '5': '5️⃣',
    '6': '6️⃣', '7': '7️⃣', '8': '8️⃣', '9': '9️⃣', '0': '0️⃣'
}

def get_random_correct_phrase() -> str:
    return random.choice(CORRECT_ANSWERS_PHRASES)

def get_random_incorrect_phrase() -> str:
    return random.choice(INCORRECT_ANSWERS_PHRASES)

def normalize_answer(answer: str, question_type: str) -> str:
    processed_answer = answer.strip().replace(" ", "").replace(",", "")
    if not processed_answer:
        return ""
    answer_digits = "".join(filter(str.isdigit, processed_answer))
    if not answer_digits:
        if question_type not in ["matching", "sequence", "single_choice", "multiple_choice"]:
            return processed_answer
        return ""
    if question_type == "multiple_choice":
        return "".join(sorted(list(set(answer_digits))))
    elif question_type in ["matching", "sequence", "single_choice"]:
        return answer_digits
    else:
        return processed_answer

def get_question_type(question_data: Optional[Dict[str, Any]]) -> str:
    if not question_data:
        return "unknown"
    q_type = question_data.get("type")
    if isinstance(q_type, str) and q_type in [
        "single_choice", "multiple_choice", "matching", "sequence", "text_input"
    ]:
        return q_type
    q_id = question_data.get('id', 'N/A')
    logging.warning(f"Поле 'type' отсутствует или некорректно для вопроса ID: {q_id}. Укажите тип в JSON.")
    return "unknown"

def find_question_by_id(question_id: str) -> Optional[Dict[str, Any]]:
    if not question_id or not QUESTIONS_DATA:
        return None
    for block_data in QUESTIONS_DATA.values():
        for topic_questions in block_data.values():
            for question in topic_questions:
                if isinstance(question, dict) and question.get("id") == question_id:
                    return question
    logging.warning(f"Вопрос с ID {question_id} не найден в QUESTIONS_DATA.")
    return None

async def choose_question(user_id: int, questions: list[dict]) -> Optional[Dict[str, Any]]:
    logging.debug(f"[User: {user_id}] Entering choose_question. Total questions in selection: {len(questions)}")
    if not questions:
        logging.warning(f"[User: {user_id}] choose_question: Empty question list received.")
        return None
    answered_ids: Set[str] = set()
    try:
        answered_ids = await db.get_answered_question_ids(user_id)
        logging.debug(f"[User: {user_id}] Fetched answered IDs: {len(answered_ids)}")
    except Exception as e:
        logging.exception(f"[User: {user_id}] Error fetching answered IDs: {e}")
        return None
    available_questions = [
        q for q in questions
        if isinstance(q, dict) and q.get("id") and q.get("id") not in answered_ids
    ]
    logging.debug(f"[User: {user_id}] Available (unanswered) questions: {len(available_questions)}")
    if not available_questions:
        all_question_ids_in_selection = {q.get("id") for q in questions if isinstance(q, dict) and q.get("id")}
        if all_question_ids_in_selection:
            logging.info(f"[User: {user_id}] No unanswered questions found in selection. Resetting answered history.")
            try:
                await db.reset_answered_questions(user_id)
                available_questions = [q for q in questions if isinstance(q, dict) and q.get("id")]
                if not available_questions:
                    logging.warning(f"[User: {user_id}] Still no available questions after reset.")
                    return None
                logging.info(f"[User: {user_id}] Answered history reset. Available questions now: {len(available_questions)}")
            except Exception as reset_err:
                logging.exception(f"[User: {user_id}] Failed to reset answered questions: {reset_err}")
                return None
        else:
            logging.warning(f"[User: {user_id}] Initial question selection was empty or contained no valid IDs.")
            return None
    valid_available_questions = []
    for q in available_questions:
        q_type_check = get_question_type(q)
        q_id = q.get('id')
        q_answer = q.get('answer')
        if not q_id or q_answer is None:
            logging.warning(f"Invalid base structure (missing id or answer) for question: {q}. Skipping.")
            continue
        if q_type_check == "matching":
            if q.get("instruction") and isinstance(q.get("column1_options"), dict) and isinstance(q.get("column2_options"), dict):
                valid_available_questions.append(q)
            else:
                logging.warning(f"Invalid structure for matching question ID {q_id}. Skipping.")
        elif q_type_check in ["single_choice", "multiple_choice", "sequence", "text_input"]:
            if q.get("question"):
                valid_available_questions.append(q)
            else:
                logging.warning(f"Invalid structure for non-matching question ID {q_id} (missing 'question'). Skipping.")
        else:
            logging.warning(f"Unknown question type for ID {q_id}. Skipping.")
    logging.debug(f"[User: {user_id}] Valid available questions (structure checked): {len(valid_available_questions)}")
    if not valid_available_questions:
        logging.warning(f"[User: {user_id}] No VALID available questions found after structure check. Check questions.json. Returning None.")
        return None
    chosen_question = random.choice(valid_available_questions)
    logging.info(f"[User: {user_id}] Chosen question ID: {chosen_question.get('id')}")
    return chosen_question

def format_question_options(options_part: str, question_type: str) -> Tuple[str, Optional[List[str]]]:
    formatted_builder = []
    first_column_letters = None
    if question_type == "matching":
        logging.error("format_question_options called with matching type. Should be handled by send_question.")
        return "", None
    lines = options_part.strip().splitlines()
    logging.debug(f"--- format_question_options start (not matching) --- type: {question_type}")
    inside_code_block = False
    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            if not inside_code_block:
                formatted_builder.append("")
            continue
        if line_strip.startswith("```"):
            inside_code_block = not inside_code_block
            formatted_builder.append(line)
            continue
        if inside_code_block:
            formatted_builder.append(line)
            continue
        match_digit = re.match(r'^(\d+)[\)\.]?\s*(.*)', line_strip)
        if match_digit:
            digit = match_digit.group(1)
            marker = DIGIT_EMOJIS.get(digit, f"{digit}.")
            text_content = match_digit.group(2).strip()
            formatted_builder.append(f"{marker} `{text_content}`")
            if question_type in ["single_choice", "multiple_choice", "sequence"]:
                formatted_builder.append("")
        else:
            if line_strip:
                formatted_builder.append(f"`{line_strip}`")
    logging.debug(f"--- format_question_options end (not matching) ---")
    result_text = "\n".join(formatted_builder).strip()
    return result_text, first_column_letters

async def has_active_subscription(user_id):
    if await db.check_user_vip(user_id):
        return True
    subscription = await db.get_user_subscription(user_id)
    if subscription:
        status, end_date = subscription
        if status == 'premium' and end_date:
            from datetime import datetime
            return datetime.now() < datetime.fromisoformat(end_date)
    return False

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE, question_data: dict, last_mode: str):
    """PTB: Отправляет текст вопроса пользователю, форматирует и сохраняет данные в context.user_data."""
    user_id = update.effective_user.id

    # Сохраняем данные вопроса в context.user_data
    context.user_data['current_question'] = question_data
    context.user_data['last_mode'] = last_mode

    # 1. Извлечение и проверка данных вопроса
    question_id = question_data.get("id")
    correct_answer = question_data.get("answer")
    block = question_data.get("block", "N/A")
    topic = question_data.get("topic", "N/A")
    exam_number = question_data.get("exam_number")
    difficulty = question_data.get("difficulty")
    question_type = get_question_type(question_data)
    explanation = question_data.get("explanation")

    if not question_id or correct_answer is None or question_type == "unknown":
        from keyboards import get_initial_choice_keyboard
        text_to_send = "Произошла ошибка с вопросом 😕 (не найден ID, ответ или тип). Выберите режим заново."
        kb = get_initial_choice_keyboard()
        if update.callback_query:
            await update.callback_query.edit_message_text(text_to_send, reply_markup=kb)
        elif update.message:
            await update.message.reply_text(text_to_send, reply_markup=kb)
        context.user_data.clear()
        return

    topic_display_name = TOPIC_NAMES.get(topic, topic)
    header = f"📚 Блок: **{block}**\n🏷️ Тема: **{topic}. {topic_display_name}**\n"
    if exam_number is not None and difficulty:
        difficulty_map = {"Б": "Базовый", "П": "Повышенный", "В": "Высокий"}
        header += f"🔢 Задание ЕГЭ: **№{exam_number}** (Уровень: {difficulty_map.get(difficulty, difficulty)})\n"
    header += "➖➖➖➖➖➖➖➖➖➖\n\n"
    formatted_text = ""
    prompt = ""
    num_letters = 0

    if question_type == "matching":
        instruction = question_data.get("instruction", "Установите соответствие.")
        col1_hdr = question_data.get("column1_header", "СТОЛБЕЦ 1")
        col1_opts = question_data.get("column1_options", {})
        col2_hdr = question_data.get("column2_header", "СТОЛБЕЦ 2")
        col2_opts = question_data.get("column2_options", {})
        if not col1_opts or not col2_opts:
            if update.message:
                await update.message.reply_text("Ошибка в структуре вопроса matching. Сообщите администратору.")
            elif update.callback_query:
                await update.callback_query.edit_message_text("Ошибка в структуре вопроса matching. Сообщите администратору.")
            context.user_data.clear()
            return
        formatted_text = header + f"❓ **{instruction}**\n\n"
        letters_list = sorted(col1_opts.keys())
        num_letters = len(letters_list)
        formatted_text += f"**{col1_hdr.upper()}**\n"
        for letter in letters_list:
            option_text = col1_opts.get(letter, "Текст отсутствует")
            formatted_text += f"**{letter})** `{option_text}`\n"
        formatted_text += f"\n**{col2_hdr.upper()}**\n"
        digit_keys_sorted = sorted(col2_opts.keys(), key=int)
        for digit in digit_keys_sorted:
            option_text = col2_opts.get(digit, "Текст отсутствует")
            marker = DIGIT_EMOJIS.get(digit, f"{digit}.")
            formatted_text += f"{marker} `{option_text}`\n"
        if num_letters > 0:
            prompt = f"\n\n➖➖➖➖➖➖➖➖➖➖\n✍️ Введите **{num_letters}** цифр ответа без пробелов:"
        else:
            prompt = f"\n\n➖➖➖➖➖➖➖➖➖➖\n✍️ Введите цифры ответа без пробелов:"
            logging.error(f"Num_letters is 0 for matching question ID: {question_id}")
    else:
        question_text_raw = question_data.get("question")
        if not question_text_raw:
            if update.message:
                await update.message.reply_text("Ошибка в структуре вопроса. Сообщите администратору.")
            elif update.callback_query:
                await update.callback_query.edit_message_text("Ошибка в структуре вопроса. Сообщите администратору.")
            context.user_data.clear()
            return
        parts = question_text_raw.split('\n', 1)
        instruction = parts[0].strip()
        options_part = parts[1] if len(parts) > 1 else ""
        formatted_options, _ = format_question_options(options_part, question_type)
        formatted_text = header + f"❓ **{instruction}**\n\n" + formatted_options
        if question_type == "multiple_choice":
            prompt = "\n\n➖➖➖➖➖➖➖➖➖➖\n✍️ Введите цифры верных ответов без пробелов:"
        elif question_type == "single_choice":
            prompt = "\n\n➖➖➖➖➖➖➖➖➖➖\n✍️ Введите одну цифру верного ответа:"
        elif question_type == "sequence":
            prompt = "\n\n➖➖➖➖➖➖➖➖➖➖\n✍️ Введите цифры в правильной последовательности без пробелов:"
        else:
            prompt = "\n\n➖➖➖➖➖➖➖➖➖➖\n✍️ Введите ваш ответ:"
    formatted_text += prompt

    # Отправка сообщения
    parse_mode_to_use = "Markdown"
    if update.callback_query:
        await update.callback_query.edit_message_text(formatted_text, parse_mode=parse_mode_to_use, reply_markup=None)
    elif update.message:
        await update.message.reply_text(formatted_text, parse_mode=parse_mode_to_use)
    # context.user_data уже обновлён

async def check_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет подписку пользователя на канал через PTB."""
    if not REQUIRED_CHANNEL:
        logging.warning("REQUIRED_CHANNEL не указан в config.py, проверка подписки отключена.")
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        else:
            logging.info(f"User {user_id} НЕ ПОДПИСАН на {REQUIRED_CHANNEL} (статус: {member.status})")
            return False
    except Exception as e:
        logging.exception(f"Ошибка при проверке подписки user {user_id} на {REQUIRED_CHANNEL}: {e}")
        return False
