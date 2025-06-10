"""Обработчики для задания 19."""

import logging
import os
import json
import random
from typing import Optional, Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import states
from core.ai_evaluator import Task19Evaluator, EvaluationResult
from datetime import datetime
import io
from .evaluator import StrictnessLevel, Task19AIEvaluator

TASK19_STRICTNESS = os.getenv('TASK19_STRICTNESS', 'STRICT').upper()

# Глобальный evaluator с настройками
evaluator = None

logger = logging.getLogger(__name__)

# Глобальное хранилище для данных задания 19
task19_data = {}

# Инициализируем evaluator если еще не создан
global evaluator
if not evaluator:
    try:
        strictness_level = StrictnessLevel[os.getenv('TASK19_STRICTNESS', 'STRICT').upper()]
    except KeyError:
        strictness_level = StrictnessLevel.STRICT
    
    try:
        evaluator = Task19AIEvaluator(strictness=strictness_level)
        logger.info(f"Task19 AI evaluator initialized with {strictness_level.value} strictness")
    except Exception as e:
        logger.warning(f"Failed to initialize AI evaluator: {e}")
        evaluator = None


# Добавить команду для изменения уровня строгости (опционально)
async def set_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка уровня строгости проверки (только для админов)."""
    query = update.callback_query
    await query.answer()
    
    # Проверка прав (добавьте свою логику проверки админов)
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Только для администраторов", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Мягкий", callback_data="t19_strict:lenient")],
        [InlineKeyboardButton("🟡 Стандартный", callback_data="t19_strict:standard")],
        [InlineKeyboardButton("🔴 Строгий (ФИПИ)", callback_data="t19_strict:strict")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]
    ])
    
    current = evaluator.strictness.value if evaluator else "не установлен"
    
    await query.edit_message_text(
        f"⚙️ <b>Настройка строгости проверки</b>\n\n"
        f"Текущий уровень: <b>{current}</b>\n\n"
        "🟢 <b>Мягкий</b> - для начальной тренировки\n"
        "🟡 <b>Стандартный</b> - баланс строгости\n"
        "🔴 <b>Строгий</b> - полное соответствие ФИПИ\n\n"
        "Выберите уровень:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )


async def apply_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Применение выбранного уровня строгости."""
    global evaluator
    
    query = update.callback_query
    await query.answer()
    
    level_str = query.data.split(":")[1].upper()
    
    try:
        new_level = StrictnessLevel[level_str]
        evaluator = Task19AIEvaluator(strictness=new_level)
        
        await query.answer(f"✅ Установлен уровень: {new_level.value}", show_alert=True)
        
        # Возвращаемся в меню
        return await return_to_menu(update, context)
        
    except Exception as e:
        logger.error(f"Error setting strictness: {e}")
        await query.answer("❌ Ошибка изменения настроек", show_alert=True)


async def delete_previous_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, keep_message_id: Optional[int] = None):
    """Удаляет предыдущие сообщения диалога (включая сообщения пользователя)."""
    if not hasattr(context, 'bot') or not context.bot:
        logger.warning("Bot instance not available for message deletion")
        return
    
    # Список ключей с ID сообщений для удаления
    message_keys = [
        'task19_question_msg_id',   # Сообщение с заданием
        'task19_answer_msg_id',     # Сообщение пользователя с ответом
        'task19_result_msg_id',     # Сообщение с результатом проверки
        'task19_thinking_msg_id'    # Сообщение "Анализирую..."
    ]
    
    messages_to_delete = []
    deleted_count = 0
    
    # Собираем ID сообщений для удаления
    for key in message_keys:
        msg_id = context.user_data.get(key)
        if msg_id and msg_id != keep_message_id:
            messages_to_delete.append((key, msg_id))
    
    # Добавляем дополнительные сообщения (если есть)
    extra_messages = context.user_data.get('task19_extra_messages', [])
    for msg_id in extra_messages:
        if msg_id and msg_id != keep_message_id:
            messages_to_delete.append(('extra', msg_id))
    
    # Удаляем сообщения
    for key, msg_id in messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            deleted_count += 1
            logger.debug(f"Deleted {key}: {msg_id}")
        except Exception as e:
            logger.debug(f"Failed to delete {key} {msg_id}: {e}")
    
    # Очищаем контекст (кроме keep_message_id если оно есть в контексте)
    for key in message_keys:
        if context.user_data.get(key) != keep_message_id:
            context.user_data.pop(key, None)
    
    # Очищаем список дополнительных сообщений
    context.user_data['task19_extra_messages'] = []
    
    logger.info(f"Task19: Deleted {deleted_count}/{len(messages_to_delete)} messages")

async def init_task19_data():
    """Инициализация данных для задания 19."""
    global task19_data

    data_file = os.path.join(os.path.dirname(__file__), "task19_topics.json")

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            raw = json.load(f)

        # Преобразуем данные: собираем все темы в единый список
        all_topics = []
        topic_by_id: Dict[int, Dict] = {}
        for block_name, block in raw.get("blocks", {}).items():
            for topic in block.get("topics", []):
                topic["block"] = block_name
                all_topics.append(topic)
                topic_by_id[topic["id"]] = topic

        raw["topics"] = all_topics
        raw["topic_by_id"] = topic_by_id

        task19_data = raw
        logger.info(f"Loaded {len(all_topics)} topics for task19")
    except Exception as e:
        logger.error(f"Failed to load task19 data: {e}")
        task19_data = {"topics": [], "blocks": {}}


async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в задание 19 из главного меню."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📝 <b>Задание 19</b>\n\n"
        "В этом задании нужно привести примеры, иллюстрирующие "
        "различные обществоведческие понятия и явления.\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t19_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t19_theory")],
        [InlineKeyboardButton("🏦 Банк примеров", callback_data="t19_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t19_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

    return states.CHOOSING_MODE


def _build_topic_message(topic: Dict) -> str:
    """Формирует текст сообщения с заданием по теме."""
    return (
        "📝 <b>Задание 19</b>\n\n"
        f"<b>Тема:</b> {topic['title']}\n\n"
        f"<b>Задание:</b> {topic['task_text']}\n\n"
        "<b>Требования:</b>\n"
        "• Приведите три примера\n"
        "• Каждый пример должен быть конкретным\n"
        "• Избегайте абстрактных формулировок\n"
        "• Указывайте детали (имена, даты, места)\n\n"
        "💡 <i>Отправьте ваш ответ одним сообщением</i>"
    )


async def cmd_task19(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task19."""
    text = (
        "📝 <b>Задание 19</b>\n\n"
        "В этом задании нужно привести примеры, иллюстрирующие "
        "различные обществоведческие понятия и явления.\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t19_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t19_theory")],
        [InlineKeyboardButton("🏦 Банк примеров", callback_data="t19_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t19_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE



async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики - выбор темы."""
    query = update.callback_query
    await query.answer()
    
    # Удаляем предыдущие сообщения диалога
    await delete_previous_messages(context, query.message.chat_id)
    
    if not task19_data.get("topics"):
        await query.edit_message_text(
            "❌ Данные заданий не загружены. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]]
            ),
        )
        return states.CHOOSING_MODE

    text = (
        "🎯 <b>Режим практики</b>\n\n"
        "Как вы хотите выбрать тему?"
    )

    kb_buttons = [
        [InlineKeyboardButton("📚 По блокам", callback_data="t19_select_block")],
        [InlineKeyboardButton("🗂️ Все темы списком", callback_data="t19_list_topics")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t19_random_all")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML,
    )

    return states.CHOOSING_MODE


async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока тем."""
    query = update.callback_query
    await query.answer()

    blocks = task19_data.get("blocks", {})
    if not blocks:
        await query.edit_message_text("❌ Блоки не найдены")
        return states.CHOOSING_MODE

    kb = [
        [InlineKeyboardButton(f"📁 {name}", callback_data=f"t19_block:{name}")]
        for name in blocks.keys()
    ]
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="t19_practice")])

    await query.edit_message_text(
        "📚 <b>Выберите блок тем:</b>",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.HTML,
    )
    return states.CHOOSING_BLOCK


async def block_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню внутри выбранного блока."""
    query = update.callback_query
    await query.answer()

    block_name = query.data.split(":", 1)[1]
    context.user_data["selected_block"] = block_name

    kb = [
        [InlineKeyboardButton("📋 Список тем", callback_data="t19_list_topics")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t19_random_block")],
        [InlineKeyboardButton("⬅️ Другой блок", callback_data="t19_select_block")],
        [InlineKeyboardButton("🔙 Назад", callback_data="t19_practice")],
    ]

    await query.edit_message_text(
        f"📁 <b>{block_name}</b>\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.HTML,
    )
    return states.CHOOSING_BLOCK


async def random_topic_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайная тема из всех блоков."""
    query = update.callback_query
    await query.answer()

    topics: List[Dict] = task19_data.get("topics", [])
    if not topics:
        await query.answer("Темы не найдены", show_alert=True)
        return states.CHOOSING_MODE

    topic = random.choice(topics)

    text = _build_topic_message(topic)
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Другая тема", callback_data="t19_practice")]]
    )
    context.user_data["current_topic"] = topic
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    return states.ANSWERING


async def random_topic_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайная тема из выбранного блока."""
    query = update.callback_query
    await query.answer()

    block_name = context.user_data.get("selected_block")
    if not block_name:
        await query.answer("Блок не выбран", show_alert=True)
        return states.CHOOSING_MODE

    topics = [t for t in task19_data.get("topics", []) if t.get("block") == block_name]
    if not topics:
        await query.answer("Темы в блоке не найдены", show_alert=True)
        return states.CHOOSING_BLOCK

    topic = random.choice(topics)
    text = _build_topic_message(topic)
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Другая тема", callback_data=f"t19_block:{block_name}")]]
    )
    context.user_data["current_topic"] = topic
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    return states.ANSWERING


async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список тем (с пагинацией)."""
    query = update.callback_query
    await query.answer()

    page = 0
    if query.data.startswith("t19_list_topics:page:"):
        try:
            page = int(query.data.split(":")[2])
        except ValueError:
            page = 0

    block_name = context.user_data.get("selected_block")

    topics = (
        [t for t in task19_data.get("topics", []) if t.get("block") == block_name]
        if block_name
        else task19_data.get("topics", [])
    )

    if not topics:
        await query.edit_message_text("❌ Темы не найдены")
        return states.CHOOSING_MODE

    ITEMS_PER_PAGE = 8
    total_pages = (len(topics) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE

    kb_rows = [
        [
            InlineKeyboardButton(t["title"], callback_data=f"t19_topic:{t['id']}")
        ]
        for t in topics[start:end]
    ]

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️", callback_data=f"t19_list_topics:page:{page-1}"
            )
        )
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                "➡️", callback_data=f"t19_list_topics:page:{page+1}"
            )
        )
    if nav:
        kb_rows.append(nav)

    if block_name:
        kb_rows.append([InlineKeyboardButton("⬅️ К блоку", callback_data=f"t19_block:{block_name}")])
    else:
        kb_rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="t19_practice")])

    text = "📚 <b>Выберите тему:</b>"
    if block_name:
        text += f"\n<b>Блок:</b> {block_name}"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_rows),
        parse_mode=ParseMode.HTML,
    )

    return states.CHOOSING_TOPIC


async def select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "t19_random":
        topic = random.choice(task19_data['topics'])
    else:
        topic_id = int(query.data.split(':')[1])
        topic = next((t for t in task19_data['topics'] if t['id'] == topic_id), None)
    
    if not topic:
        await query.edit_message_text("❌ Тема не найдена")
        return states.CHOOSING_MODE
    
    # Сохраняем текущую тему
    context.user_data['current_topic'] = topic
    
    text = f"""📝 <b>Задание 19</b>

<b>Тема:</b> {topic['title']}

<b>Задание:</b> {topic['task_text']}

<b>Требования:</b>
• Приведите три примера
• Каждый пример должен быть конкретным
• Избегайте абстрактных формулировок
• Указывайте детали (имена, даты, места)

💡 <i>Отправьте ваш ответ одним сообщением</i>"""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Выбрать другую тему", callback_data="t19_practice")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING

async def choose_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора темы."""
    query = update.callback_query
    await query.answer()
    
    # Удаляем все предыдущие сообщения перед показом нового задания
    await delete_previous_messages(context, query.message.chat_id)
    
    if query.data == "t19_random":
        topic = random.choice(task19_data['topics'])
    else:
        topic_id = int(query.data.split(':')[1])
        topic = next((t for t in task19_data['topics'] if t['id'] == topic_id), None)
    
    if not topic:
        await query.message.chat.send_message(
            "❌ Тема не найдена",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t19_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Сохраняем текущую тему
    context.user_data['current_topic'] = topic
    
    text = f"""📝 <b>Задание 19</b>

<b>Тема:</b> {topic['title']}

<b>Задание:</b> {topic['task_text']}

<b>Требования:</b>
• Приведите три примера
• Каждый пример должен быть конкретным
• Избегайте абстрактных формулировок
• Указывайте детали (имена, даты, места)

💡 <i>Отправьте ваш ответ одним сообщением</i>"""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Выбрать другую тему", callback_data="t19_practice")
    ]])
    
    # Отправляем новое сообщение
    sent_msg = await query.message.chat.send_message(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    # Сохраняем ID сообщения с заданием
    context.user_data['task19_question_msg_id'] = sent_msg.message_id
    
    return states.ANSWERING

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа пользователя."""
    user_answer = update.message.text
    topic = context.user_data.get('current_topic')
    
    # Сохраняем ID сообщения с ответом пользователя
    context.user_data['task19_answer_msg_id'] = update.message.message_id
    
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 К заданиям", callback_data="t19_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Показываем сообщение о проверке
    thinking_msg = await update.message.reply_text(
        "🤔 Анализирую ваш ответ..."
    )
    
    # Сохраняем ID сообщения "Анализирую..."
    context.user_data['task19_thinking_msg_id'] = thinking_msg.message_id
    
    result: Optional[EvaluationResult] = None

    try:
        # Проверяем наличие evaluator
        if not evaluator:
            # Простая проверка без AI
            examples_count = len([line for line in user_answer.split('\n') if line.strip()])
            score = min(examples_count, 3) if examples_count <= 3 else 0
            result = EvaluationResult(
                scores={"К1": score},
                total_score=score,
                max_score=3,
                feedback="",
                detailed_analysis={},
                suggestions=[],
                factual_errors=[],
            )
            feedback = f"📊 <b>Результаты проверки</b>\n\n"
            feedback += f"<b>Тема:</b> {topic['title']}\n"
            feedback += f"<b>Примеров найдено:</b> {examples_count}\n\n"

            if examples_count >= 3:
                feedback += "✅ Вы привели достаточное количество примеров.\n"
            else:
                feedback += "❌ Необходимо привести три примера.\n"

            feedback += "\n⚠️ <i>AI-проверка недоступна. Обратитесь к преподавателю для детальной оценки.</i>"
        else:
            # AI-проверка
            result = await evaluator.evaluate(
                answer=user_answer,
                topic=topic['title'],
                task_text=topic['task_text'],
                key_points=topic.get('key_points', [])
            )
            
            # Формируем отзыв
            feedback = f"📊 <b>Результаты проверки</b>\n\n"
            feedback += f"<b>Тема:</b> {topic['title']}\n"
            feedback += f"<b>Оценка:</b> {result.total_score}/{result.max_score} баллов\n\n"
        
        if result.feedback:
            feedback += f"<b>Комментарий:</b>\n{result.feedback}\n\n"
        
        if result.suggestions:
            feedback += f"<b>Рекомендации:</b>\n"
            for suggestion in result.suggestions:
                feedback += f"• {suggestion}\n"
        
        # Сохраняем результат
        if 'task19_results' not in context.user_data:
            context.user_data['task19_results'] = []
        
        context.user_data['task19_results'].append({
            'topic': topic['title'],
            'score': result.total_score,
            'max_score': result.max_score,
            'timestamp': datetime.now().isoformat()  # Добавить эту строку
        })
        
        # Кнопки для действий после проверки
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Новое задание", callback_data="t19_new_topic"),
                InlineKeyboardButton("🔁 Попробовать снова", callback_data="t19_retry")
            ],
            [
                InlineKeyboardButton("📋 К заданиям", callback_data="t19_menu"),
                InlineKeyboardButton("📊 Мой прогресс", callback_data="t19_progress")
            ],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ])
        
        # Удаляем сообщение "Анализирую..."
        try:
            await thinking_msg.delete()
        except Exception as e:
            logger.debug(f"Failed to delete thinking message: {e}")
        
        # Отправляем результат
        result_msg = await update.message.reply_text(
            feedback,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        # Сохраняем ID сообщения с результатом
        context.user_data['task19_result_msg_id'] = result_msg.message_id
        
    except Exception as e:
        logger.error(f"Ошибка при проверке ответа: {e}", exc_info=True)
        
        # Fallback оценка
        examples_count = len([line for line in user_answer.split('\n') if line.strip() and len(line.strip()) > 20])
        
        feedback = f"📊 <b>Результаты проверки</b>\n\n"
        feedback += f"<b>Тема:</b> {topic['title']}\n"
        feedback += f"<b>Примеров найдено:</b> {examples_count}/3\n\n"
        
        if examples_count >= 3:
            feedback += "✅ Количество примеров соответствует требованиям.\n"
        else:
            feedback += "❌ Необходимо привести три развернутых примера.\n"
        
        feedback += "\n⚠️ <i>Произошла ошибка при AI-проверке. Обратитесь к преподавателю для детальной оценки.</i>"
        
        # Кнопки
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Новое задание", callback_data="t19_new_topic"),
                InlineKeyboardButton("🔁 Попробовать снова", callback_data="t19_retry")
            ],
            [
                InlineKeyboardButton("📋 К заданиям", callback_data="t19_menu"),
                InlineKeyboardButton("📊 Мой прогресс", callback_data="t19_progress")
            ],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ])
        
        # Удаляем сообщение "Анализирую..."
        try:
            await thinking_msg.delete()
        except Exception as e:
            logger.debug(f"Failed to delete thinking message: {e}")
        
        # Отправляем результат
        result_msg = await update.message.reply_text(
            feedback,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        # Сохраняем ID сообщения с результатом
        context.user_data['task19_result_msg_id'] = result_msg.message_id
    
    return states.CHOOSING_MODE

async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ теории и советов."""
    query = update.callback_query
    await query.answer()
    
    text = """📚 <b>Теория по заданию 19</b>

<b>Структура хорошего примера:</b>

1️⃣ <b>Конкретность</b>
❌ Плохо: "Человек нарушил закон"
✅ Хорошо: "Водитель Иванов превысил скорость на 40 км/ч на трассе М-4"

2️⃣ <b>Детализация</b>
• Указывайте имена, даты, места
• Описывайте конкретные действия
• Приводите результаты/последствия

3️⃣ <b>Соответствие теме</b>
• Пример должен точно иллюстрировать понятие
• Избегайте двусмысленности
• Проверяйте логическую связь

<b>Типичные ошибки:</b>
🔸 Абстрактные формулировки
🔸 Повтор одного примера разными словами
🔸 Примеры не по теме
🔸 Отсутствие конкретики

<b>Совет:</b> Используйте примеры из СМИ, истории, литературы или личного опыта."""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE


async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ банка примеров."""
    query = update.callback_query
    await query.answer()
    
    # Показываем первую тему с примерами
    if task19_data.get('topics'):
        topic = task19_data['topics'][0]  # Для демонстрации берем первую тему
        
        text = f"📚 <b>Банк примеров</b>\n\n"
        text += f"<b>Тема:</b> {topic['title']}\n"
        text += f"<b>Задание:</b> {topic['task_text']}\n\n"
        text += "<b>Эталонные примеры:</b>\n\n"
        
        for i, example in enumerate(topic.get('example_answers', []), 1):
            text += f"{i}. <b>{example['type']}</b>\n"
            text += f"   {example['example']}\n\n"
        
        text += "💡 <i>Обратите внимание на структуру и конкретность примеров!</i>"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➡️ Следующая тема", callback_data="t19_bank_next:1")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]
        ])
    else:
        text = "📚 <b>Банк примеров</b>\n\nБанк примеров пуст."
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
        ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def bank_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по банку примеров."""
    query = update.callback_query
    await query.answer()
    
    current_idx = int(query.data.split(":")[1])
    topics = task19_data.get('topics', [])
    
    if current_idx >= len(topics):
        current_idx = 0  # Возвращаемся к первой теме
    
    topic = topics[current_idx]
    
    text = f"📚 <b>Банк примеров</b> ({current_idx + 1}/{len(topics)})\n\n"
    text += f"<b>Тема:</b> {topic['title']}\n"
    text += f"<b>Задание:</b> {topic['task_text']}\n\n"
    text += "<b>Эталонные примеры:</b>\n\n"
    
    for i, example in enumerate(topic.get('example_answers', []), 1):
        text += f"{i}. <b>{example['type']}</b>\n"
        text += f"   {example['example']}\n\n"
    
    # Навигация
    kb_buttons = []
    nav_row = []
    
    if current_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"t19_bank_next:{current_idx-1}"))
    
    nav_row.append(InlineKeyboardButton(f"{current_idx+1}/{len(topics)}", callback_data="noop"))
    
    if current_idx < len(topics) - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"t19_bank_next:{current_idx+1}"))
    
    kb_buttons.append(nav_row)
    kb_buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t19_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE


async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прогресса пользователя."""
    query = update.callback_query
    await query.answer()
    
    results = context.user_data.get('task19_results', [])
    
    if not results:
        text = "📊 <b>Ваш прогресс</b>\n\nВы еще не решали задания."
    else:
        total_attempts = len(results)
        total_score = sum(r['score'] for r in results)
        max_possible = sum(r['max_score'] for r in results)
        avg_score = total_score / total_attempts
        
        # Визуальный прогресс-бар
        progress_percent = int(total_score / max_possible * 100) if max_possible > 0 else 0
        filled = "█" * (progress_percent // 10)
        empty = "░" * (10 - progress_percent // 10)
        progress_bar = f"{filled}{empty}"
        
        text = f"""📊 <b>Ваш прогресс по заданию 19</b>

📈 Прогресс: {progress_bar} {progress_percent}%
📝 Решено заданий: {total_attempts}
⭐ Средний балл: {avg_score:.1f}/3
🏆 Общий результат: {total_score}/{max_possible}

<b>Последние попытки:</b>"""
        
        for result in results[-5:]:
            score_emoji = "🟢" if result['score'] == 3 else "🟡" if result['score'] >= 2 else "🔴"
            text += f"\n{score_emoji} {result['topic']}: {result['score']}/3"
        
        # Рекомендации
        if avg_score < 2:
            text += "\n\n💡 <b>Совет:</b> Изучите теорию и примеры эталонных ответов."
        elif avg_score < 2.5:
            text += "\n\n💡 <b>Совет:</b> Обратите внимание на конкретизацию примеров."
        else:
            text += "\n\n🎉 <b>Отлично!</b> Вы хорошо справляетесь с заданием 19!"
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE


async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню."""
    from core.plugin_loader import build_main_menu
    
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👋 Выберите раздел для изучения:",
        reply_markup=build_main_menu()
    )
    return ConversationHandler.END


async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 19."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📝 <b>Задание 19</b>\n\n"
        "В этом задании нужно привести примеры, иллюстрирующие "
        "различные обществоведческие понятия и явления.\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t19_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t19_theory")],
        [InlineKeyboardButton("🏦 Банк примеров", callback_data="t19_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t19_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после показа результата."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "t19_new_topic":
        # Удаляем все сообщения перед показом списка тем
        await delete_previous_messages(context, query.message.chat_id)
        
        # Показываем меню выбора темы
        return await practice_mode(update, context)
    
    elif query.data == "t19_retry":
        # Удаляем все сообщения и показываем то же задание заново
        await delete_previous_messages(context, query.message.chat_id)
        
        topic = context.user_data.get('current_topic')
        if topic:
            text = _build_topic_message(topic)
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Выбрать другую тему", callback_data="t19_practice")
            ]])
            
            msg = await query.message.chat.send_message(
                text, 
                reply_markup=kb, 
                parse_mode=ParseMode.HTML
            )
            
            # Сохраняем ID нового сообщения
            context.user_data['task19_question_msg_id'] = msg.message_id
            
            return states.ANSWERING
        else:
            await query.message.chat.send_message(
                "❌ Ошибка: тема не найдена",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📝 К заданиям", callback_data="t19_menu")
                ]])
            )
            return states.CHOOSING_MODE
    
    elif query.data == "t19_menu":
        # Удаляем все сообщения и показываем главное меню задания
        await delete_previous_messages(context, query.message.chat_id)
        return await return_to_menu(update, context)
    
    elif query.data == "t19_progress":
        # Показываем прогресс (не удаляем сообщения)
        return await show_progress(update, context)

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    await update.message.reply_text("Действие отменено.")
    return await cmd_task19(update, context)

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик для неактивных кнопок."""
    query = update.callback_query
    await query.answer()
    # Ничего не делаем, просто отвечаем на callback

async def reset_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс результатов пользователя."""
    query = update.callback_query
    await query.answer()
    
    # Проверяем, есть ли подтверждение
    if context.user_data.get('confirm_reset_task19'):
        # Сбрасываем результаты
        context.user_data['task19_results'] = []
        context.user_data.pop('confirm_reset_task19', None)
        
        await query.answer("✅ Результаты сброшены", show_alert=True)
        
        # Возвращаемся в меню
        return await return_to_menu(update, context)
    else:
        # Запрашиваем подтверждение
        context.user_data['confirm_reset_task19'] = True
        
        text = """⚠️ <b>Подтверждение сброса</b>

Вы действительно хотите сбросить все результаты по заданию 19?

Это действие нельзя отменить!"""
        
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("❌ Да, сбросить", callback_data="t19_reset_confirm"),
                InlineKeyboardButton("✅ Отмена", callback_data="t19_menu")
            ]
        ])
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return states.CHOOSING_MODE


# Добавить в меню "Мой прогресс" кнопку сброса:
async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прогресса пользователя."""
    query = update.callback_query
    await query.answer()
    
    results = context.user_data.get('task19_results', [])
    
    if not results:
        text = "📊 <b>Ваш прогресс</b>\n\nВы еще не решали задания."
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
        ]])
    else:
        total_attempts = len(results)
        total_score = sum(r['score'] for r in results)
        max_possible = sum(r['max_score'] for r in results)
        avg_score = total_score / total_attempts
        
        # Визуальный прогресс-бар
        progress_percent = int(total_score / max_possible * 100) if max_possible > 0 else 0
        filled = "█" * (progress_percent // 10)
        empty = "░" * (10 - progress_percent // 10)
        progress_bar = f"{filled}{empty}"
        
        text = f"""📊 <b>Ваш прогресс по заданию 19</b>

📈 Прогресс: {progress_bar} {progress_percent}%
📝 Решено заданий: {total_attempts}
⭐ Средний балл: {avg_score:.1f}/3
🏆 Общий результат: {total_score}/{max_possible}

<b>Последние попытки:</b>"""
        
        for result in results[-5:]:
            score_emoji = "🟢" if result['score'] == 3 else "🟡" if result['score'] >= 2 else "🔴"
            text += f"\n{score_emoji} {result['topic']}: {result['score']}/3"
        
        # Рекомендации
        if avg_score < 2:
            text += "\n\n💡 <b>Совет:</b> Изучите теорию и примеры эталонных ответов."
        elif avg_score < 2.5:
            text += "\n\n💡 <b>Совет:</b> Обратите внимание на конкретизацию примеров."
        else:
            text += "\n\n🎉 <b>Отлично!</b> Вы хорошо справляетесь с заданием 19!"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Детальная статистика", callback_data="t19_detailed_progress")],
            [InlineKeyboardButton("📤 Экспорт результатов", callback_data="t19_export")],
            [InlineKeyboardButton("🔄 Сбросить результаты", callback_data="t19_reset_confirm")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]
        ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def cmd_task19_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task19_settings для быстрого доступа к настройкам."""
    current_level = evaluator.strictness if evaluator else StrictnessLevel.STRICT
    
    text = f"""⚙️ <b>Быстрые настройки задания 19</b>

Текущий уровень проверки: <b>{current_level.value}</b>

Используйте кнопки ниже для изменения:"""
    
    kb_buttons = []
    for level in StrictnessLevel:
        emoji = "✅" if level == current_level else ""
        kb_buttons.append([
            InlineKeyboardButton(
                f"{emoji} {level.value}",
                callback_data=f"t19_set_strictness:{level.name}"
            )
        ])
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

# Добавить в handlers.py:

async def bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск темы в банке примеров."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔍 <b>Поиск в банке примеров</b>\n\n"
        "Отправьте название темы или ключевые слова для поиска:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="t19_examples")
        ]]),
        parse_mode=ParseMode.HTML
    )
    
    context.user_data['waiting_for_bank_search'] = True
    return states.SEARCHING


async def handle_bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поискового запроса в банке примеров."""
    if not context.user_data.get('waiting_for_bank_search'):
        return
    
    search_query = update.message.text.lower()
    context.user_data['waiting_for_bank_search'] = False
    
    # Ищем подходящие темы
    matching_topics = []
    for idx, topic in enumerate(task19_data.get('topics', [])):
        if search_query in topic['title'].lower() or search_query in topic.get('task_text', '').lower():
            matching_topics.append((idx, topic))
    
    if not matching_topics:
        await update.message.reply_text(
            "❌ Темы не найдены. Попробуйте другой запрос.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 Искать снова", callback_data="t19_bank_search"),
                InlineKeyboardButton("⬅️ Назад", callback_data="t19_examples")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Показываем первую найденную тему
    await update.message.reply_text("✅ Найдено тем: " + str(len(matching_topics)))
    
    # Создаем новое сообщение с результатом
    msg = await update.message.reply_text("Загрузка...")
    await show_examples_for_topic_message(msg, context, matching_topics[0][0])
    
    return states.CHOOSING_MODE


async def show_examples_for_topic_message(message, context: ContextTypes.DEFAULT_TYPE, topic_idx: int):
    """Показывает примеры для темы (для обычных сообщений, не callback)."""
    topics = task19_data.get('topics', [])
    
    if not topics or topic_idx >= len(topics):
        await message.edit_text("❌ Тема не найдена")
        return
    
    topic = topics[topic_idx]
    context.user_data['bank_current_idx'] = topic_idx
    
    text = f"""🏦 <b>Банк примеров</b>

<b>Тема:</b> {topic['title']}

<b>Эталонные примеры:</b>

{generate_examples_for_topic(topic)}

💡 <b>Обратите внимание:</b>
• Каждый пример содержит конкретные детали
• Примеры взяты из разных сфер жизни
• Четко показана связь с темой задания"""
    
    # Навигация
    kb_buttons = []
    nav_row = []
    
    if topic_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"t19_bank_nav:{topic_idx-1}"))
    
    nav_row.append(InlineKeyboardButton(f"{topic_idx+1}/{len(topics)}", callback_data="noop"))
    
    if topic_idx < len(topics) - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"t19_bank_nav:{topic_idx+1}"))
    
    kb_buttons.append(nav_row)
    kb_buttons.append([InlineKeyboardButton("🔍 Поиск темы", callback_data="t19_bank_search")])
    kb_buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t19_menu")])
    
    await message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )


def generate_examples_for_topic(topic: Dict) -> str:
    """Генерирует примеры для конкретной темы."""
    # Здесь можно добавить логику генерации примеров на основе темы
    # Пока используем универсальные примеры
    
    if "экономик" in topic['title'].lower():
        return """1️⃣ <b>Пример из бизнеса:</b>
Компания "Wildberries" в 2023 году открыла собственные пункты выдачи в регионах России, что позволило сократить сроки доставки с 5-7 до 1-2 дней и увеличить выручку на 40%.

2️⃣ <b>Пример из госсектора:</b>
ЦБ РФ в июле 2023 года повысил ключевую ставку до 12%, чтобы сдержать инфляцию. Это привело к росту ставок по депозитам до 15% годовых и снижению спроса на ипотеку на 30%.

3️⃣ <b>Пример из повседневной жизни:</b>
Семья Ивановых из Москвы перешла на покупки в дискаунтерах "Пятерочка" и "Магнит" вместо "Азбуки Вкуса", что позволило им экономить 15 тыс. рублей в месяц на продуктах."""
    
    elif "полити" in topic['title'].lower():
        return """1️⃣ <b>Пример из федеральной политики:</b>
В сентябре 2023 года в России прошли выборы губернаторов в 21 регионе. Явка составила в среднем 35%, что на 5% ниже предыдущих выборов.

2️⃣ <b>Пример из международных отношений:</b>
В мае 2023 года Президент РФ посетил Китай, где были подписаны соглашения о строительстве газопровода "Сила Сибири-2" мощностью 50 млрд м³ в год.

3️⃣ <b>Пример из местной политики:</b>
Депутаты Мосгордумы в 2023 году приняли закон о льготной аренде помещений для социальных предпринимателей - ставка снижена на 50% для 500 организаций."""
    
    else:
        return """1️⃣ <b>Пример из образования:</b>
Московский школьник Иван Петров в 2023 году набрал 310 баллов на ЕГЭ и поступил на бюджет в МГИМО. Он готовился 2 года с репетиторами, тратя 50 тыс. рублей в месяц.

2️⃣ <b>Пример из социальной сферы:</b>
В Санкт-Петербурге волонтеры фонда "Ночлежка" ежедневно кормят 300 бездомных. За 2023 год они раздали более 100 тысяч порций горячей еды.

3️⃣ <b>Пример из культуры:</b>
Фильм "Челюсти" режиссера А. Учителя собрал в российском прокате 1,2 млрд рублей за первый месяц, став самым кассовым российским фильмом 2023 года."""


# Оптимизированная загрузка данных с кэшированием
_topics_cache = None
_topics_cache_time = None

async def init_task19_data():
    """Инициализация данных для задания 19 с кэшированием."""
    global task19_data, _topics_cache, _topics_cache_time
    
    # Проверяем кэш (обновляем раз в час)
    if _topics_cache and _topics_cache_time:
        if (datetime.now() - _topics_cache_time).seconds < 3600:
            task19_data = _topics_cache
            logger.info("Loaded task19 data from cache")
            return
    
    data_file = os.path.join(os.path.dirname(__file__), "task19_topics.json")
    
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        
        # Преобразуем данные: собираем все темы в единый список
        all_topics = []
        topic_by_id = {}
        topics_by_block = {}
        
        for block_name, block in raw.get("blocks", {}).items():
            topics_by_block[block_name] = []
            for topic in block.get("topics", []):
                topic["block"] = block_name
                all_topics.append(topic)
                topic_by_id[topic["id"]] = topic
                topics_by_block[block_name].append(topic)
        
        raw["topics"] = all_topics
        raw["topic_by_id"] = topic_by_id
        raw["topics_by_block"] = topics_by_block
        
        task19_data = raw
        _topics_cache = raw
        _topics_cache_time = datetime.now()
        
        logger.info(f"Loaded {len(all_topics)} topics for task19")
    except Exception as e:
        logger.error(f"Failed to load task19 data: {e}")
        task19_data = {"topics": [], "blocks": {}, "topics_by_block": {}}

async def cmd_task19_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task19_settings для быстрого доступа к настройкам."""
    current_level = evaluator.strictness if evaluator else StrictnessLevel.STRICT
    
    text = f"""⚙️ <b>Быстрые настройки задания 19</b>

Текущий уровень проверки: <b>{current_level.value}</b>

Используйте кнопки ниже для изменения:"""
    
    kb_buttons = []
    for level in StrictnessLevel:
        emoji = "✅" if level == current_level else ""
        kb_buttons.append([
            InlineKeyboardButton(
                f"{emoji} {level.value}",
                callback_data=f"t19_set_strictness:{level.name}"
            )
        ])
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 19."""
    query = update.callback_query
    await query.answer()
    
    # Получаем статистику для отображения
    results = context.user_data.get('task19_results', [])
    attempts = len(results)
    avg_score = sum(r['score'] for r in results) / attempts if attempts > 0 else 0
    
    text = (
        "📝 <b>Задание 19</b>\n\n"
        "В этом задании нужно привести примеры, иллюстрирующие "
        "различные обществоведческие понятия и явления.\n\n"
    )
    
    # Добавляем краткую статистику если есть
    if attempts > 0:
        text += f"📊 Ваш прогресс: {attempts} попыток, средний балл {avg_score:.1f}/3\n\n"
    
    text += "Выберите режим работы:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t19_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t19_theory")],
        [InlineKeyboardButton("🏦 Банк примеров", callback_data="t19_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t19_progress")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="t19_settings")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def cmd_task19(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task19."""
    # Получаем статистику для отображения
    results = context.user_data.get('task19_results', [])
    attempts = len(results)
    avg_score = sum(r['score'] for r in results) / attempts if attempts > 0 else 0
    
    text = (
        "📝 <b>Задание 19</b>\n\n"
        "В этом задании нужно привести примеры, иллюстрирующие "
        "различные обществоведческие понятия и явления.\n\n"
    )
    
    # Добавляем краткую статистику если есть
    if attempts > 0:
        text += f"📊 Ваш прогресс: {attempts} попыток, средний балл {avg_score:.1f}/3\n\n"
    
    text += "Выберите режим работы:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t19_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t19_theory")],
        [InlineKeyboardButton("🏦 Банк примеров", callback_data="t19_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t19_progress")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="t19_settings")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def export_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт результатов в файл."""
    query = update.callback_query
    await query.answer()
    
    results = context.user_data.get('task19_results', [])
    
    if not results:
        await query.answer("Нет результатов для экспорта", show_alert=True)
        return states.CHOOSING_MODE
    
    # Создаем текст для экспорта
    export_text = "РЕЗУЛЬТАТЫ ВЫПОЛНЕНИЯ ЗАДАНИЯ 19\n"
    export_text += "=" * 50 + "\n\n"
    export_text += f"Дата экспорта: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
    export_text += f"Пользователь: @{query.from_user.username or 'unknown'}\n\n"
    
    # Общая статистика
    total_attempts = len(results)
    total_score = sum(r['score'] for r in results)
    max_possible = sum(r['max_score'] for r in results)
    avg_score = total_score / total_attempts if total_attempts > 0 else 0
    
    export_text += "ОБЩАЯ СТАТИСТИКА\n"
    export_text += "-" * 30 + "\n"
    export_text += f"Выполнено заданий: {total_attempts}\n"
    export_text += f"Средний балл: {avg_score:.1f}/3\n"
    export_text += f"Общий результат: {total_score}/{max_possible}\n\n"
    
    # Детальные результаты
    export_text += "ДЕТАЛЬНЫЕ РЕЗУЛЬТАТЫ\n"
    export_text += "-" * 30 + "\n\n"
    
    for i, result in enumerate(results, 1):
        export_text += f"{i}. Тема: {result['topic']}\n"
        export_text += f"   Балл: {result['score']}/{result['max_score']}\n"
        if 'timestamp' in result:
            export_text += f"   Дата: {result['timestamp']}\n"
        export_text += "\n"
    
    # Анализ по блокам
    blocks_stats = {}
    for result in results:
        topic_name = result['topic']
        for topic in task19_data.get('topics', []):
            if topic['title'] == topic_name:
                block = topic.get('block', 'Другое')
                if block not in blocks_stats:
                    blocks_stats[block] = []
                blocks_stats[block].append(result['score'])
                break
    
    if blocks_stats:
        export_text += "\nАНАЛИЗ ПО БЛОКАМ\n"
        export_text += "-" * 30 + "\n\n"
        
        for block, scores in blocks_stats.items():
            avg = sum(scores) / len(scores)
            export_text += f"{block}:\n"
            export_text += f"  Попыток: {len(scores)}\n"
            export_text += f"  Средний балл: {avg:.1f}/3\n\n"
    
    # Рекомендации
    export_text += "\nРЕКОМЕНДАЦИИ\n"
    export_text += "-" * 30 + "\n"
    
    if avg_score < 2:
        export_text += "• Изучите теорию по заданию 19\n"
        export_text += "• Обратите внимание на конкретизацию примеров\n"
        export_text += "• Используйте банк примеров для изучения эталонов\n"
    elif avg_score < 2.5:
        export_text += "• Хороший результат! Продолжайте практиковаться\n"
        export_text += "• Обратите внимание на детализацию примеров\n"
    else:
        export_text += "• Отличный результат!\n"
        export_text += "• Вы готовы к выполнению задания 19 на экзамене\n"
    
    # Отправляем файл
    import io
    file_buffer = io.BytesIO(export_text.encode('utf-8'))
    file_buffer.name = f'task19_results_{query.from_user.id}.txt'
    
    await query.message.reply_document(
        document=file_buffer,
        filename=file_buffer.name,
        caption="📊 Ваши результаты по заданию 19"
    )
    
    return states.CHOOSING_MODE

async def detailed_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ детального прогресса по блокам."""
    query = update.callback_query
    await query.answer()
    
    results = context.user_data.get('task19_results', [])
    
    # Группируем результаты по блокам
    blocks_stats = {}
    for result in results:
        topic_name = result['topic']
        # Находим блок для темы
        for topic in task19_data.get('topics', []):
            if topic['title'] == topic_name:
                block = topic.get('block', 'Другое')
                if block not in blocks_stats:
                    blocks_stats[block] = {
                        'attempts': 0,
                        'total_score': 0,
                        'topics': set()
                    }
                blocks_stats[block]['attempts'] += 1
                blocks_stats[block]['total_score'] += result['score']
                blocks_stats[block]['topics'].add(topic_name)
                break
    
    text = "📊 <b>Детальная статистика по блокам</b>\n\n"
    
    if not blocks_stats:
        text += "Вы еще не решали задания."
    else:
        # Сортируем блоки по количеству попыток
        sorted_blocks = sorted(blocks_stats.items(), key=lambda x: x[1]['attempts'], reverse=True)
        
        for block_name, stats in sorted_blocks:
            avg_score = stats['total_score'] / stats['attempts']
            
            # Визуальная оценка
            if avg_score >= 2.5:
                emoji = "🟢"
                assessment = "отлично"
            elif avg_score >= 2:
                emoji = "🟡"
                assessment = "хорошо"
            else:
                emoji = "🔴"
                assessment = "требует внимания"
            
            text += f"{emoji} <b>{block_name}</b>\n"
            text += f"📝 Попыток: {stats['attempts']}\n"
            text += f"⭐ Средний балл: {avg_score:.1f}/3 ({assessment})\n"
            text += f"📚 Изучено тем: {len(stats['topics'])}\n\n"
    
    # Рекомендации по блокам
    if blocks_stats:
        weak_blocks = [block for block, stats in blocks_stats.items() 
                      if stats['total_score'] / stats['attempts'] < 2]
        
        if weak_blocks:
            text += "💡 <b>Рекомендации:</b>\n"
            text += f"Обратите внимание на блоки: {', '.join(weak_blocks)}\n"
            text += "Изучите теорию и примеры по этим темам."
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Общая статистика", callback_data="t19_progress")],
        [InlineKeyboardButton("📤 Экспорт результатов", callback_data="t19_export")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def settings_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки проверки."""
    query = update.callback_query
    await query.answer()
    
    current_level = evaluator.strictness if evaluator else StrictnessLevel.STRICT
    
    text = f"""⚙️ <b>Настройки проверки</b>

<b>Текущий уровень:</b> {current_level.value}

<b>Описание уровней:</b>

🟢 <b>Базовый</b>
• Проверка наличия 3 примеров
• Базовая проверка соответствия теме
• Подходит для начинающих

🟡 <b>Стандартный</b>
• Проверка развернутости примеров
• Выявление очевидных ошибок
• Рекомендуется для подготовки

🔴 <b>Строгий</b> (рекомендуется)
• Детальная проверка фактов
• Проверка соответствия законодательству РФ
• Выявление всех типов ошибок

🔥 <b>Экспертный</b>
• Максимальная строгость
• Проверка актуальности данных
• Как на реальном экзамене"""
    
    kb_buttons = []
    for level in StrictnessLevel:
        emoji = "✅" if level == current_level else ""
        kb_buttons.append([
            InlineKeyboardButton(
                f"{emoji} {level.value}",
                callback_data=f"t19_set_strictness:{level.name}"
            )
        ])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE


async def set_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка уровня строгости."""
    global evaluator
    
    query = update.callback_query
    await query.answer()
    
    level_str = query.data.split(":")[1].upper()
    
    try:
        new_level = StrictnessLevel[level_str]
        evaluator = Task19AIEvaluator(strictness=new_level)
        
        await query.answer(f"✅ Установлен уровень: {new_level.value}", show_alert=True)
        
        # Возвращаемся в настройки
        return await settings_mode(update, context)
        
    except Exception as e:
        logger.error(f"Error setting strictness: {e}")
        await query.answer("❌ Ошибка изменения настроек", show_alert=True)
        return states.CHOOSING_MODE
