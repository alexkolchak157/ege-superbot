# Начало файла task25/handlers.py
import logging
import os
import json
import random
from typing import Optional, Dict, List
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from core import states
from core.plugin_loader import build_main_menu

logger = logging.getLogger(__name__)

# Глобальные переменные
task25_data = {}
evaluator = None
topic_selector = None

# Импорты внутренних модулей ПОСЛЕ определения переменных
try:
    from .evaluator import Task25AIEvaluator, StrictnessLevel, EvaluationResult, AI_EVALUATOR_AVAILABLE
except ImportError as e:
    logger.error(f"Failed to import evaluator: {e}")
    AI_EVALUATOR_AVAILABLE = False
    StrictnessLevel = None
    EvaluationResult = None

try:
    from .cache import cache
except ImportError as e:
    logger.error(f"Failed to import cache: {e}")
    cache = None

try:
    from .utils import TopicSelector
except ImportError as e:
    logger.error(f"Failed to import utils: {e}")
    TopicSelector = None


async def init_task25_data():
    """Инициализация данных для задания 25."""
    global task25_data, evaluator, topic_selector
    
    # Проверяем кэш
    if cache:
        cached_data = await cache.get('task25_data')
        if cached_data:
            task25_data = cached_data
            topic_selector = TopicSelector(task25_data['topics']) if TopicSelector else None
            logger.info("Loaded task25 data from cache")
            return
    
    # Загружаем из файла
    data_file = os.path.join(os.path.dirname(__file__), "task25_topics.json")
    
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        
        # Проверяем формат данных
        all_topics = []
        topic_by_id = {}
        topics_by_block = {}
        blocks = {}
        
        # Если это список тем
        if isinstance(raw, list):
            for topic in raw:
                if isinstance(topic, dict):
                    # Генерируем ID если его нет
                    if 'id' not in topic:
                        topic['id'] = f"topic_{len(all_topics) + 1}"
                    
                    # Определяем блок если его нет
                    if 'block' not in topic:
                        # Пытаемся определить блок по ключевым словам в теме
                        topic['block'] = _determine_block(topic.get('title', ''))
                    
                    block_name = topic['block']
                    
                    # Добавляем в общий список
                    all_topics.append(topic)
                    topic_by_id[topic['id']] = topic
                    
                    # Группируем по блокам
                    if block_name not in topics_by_block:
                        topics_by_block[block_name] = []
                        blocks[block_name] = {"name": block_name, "topics": []}
                    
                    topics_by_block[block_name].append(topic)
                    blocks[block_name]["topics"].append(topic)
        
        # Если это объект с полем blocks (новый формат)
        elif isinstance(raw, dict) and 'blocks' in raw:
            for block_name, block in raw.get("blocks", {}).items():
                topics_by_block[block_name] = []
                blocks[block_name] = block
                
                for topic in block.get("topics", []):
                    if 'id' not in topic:
                        topic['id'] = f"topic_{len(all_topics) + 1}"
                    
                    topic["block"] = block_name
                    all_topics.append(topic)
                    topic_by_id[topic["id"]] = topic
                    topics_by_block[block_name].append(topic)
        
        # Если это объект с полем topics (альтернативный формат)
        elif isinstance(raw, dict) and 'topics' in raw:
            for topic in raw.get('topics', []):
                if 'id' not in topic:
                    topic['id'] = f"topic_{len(all_topics) + 1}"
                
                if 'block' not in topic:
                    topic['block'] = _determine_block(topic.get('title', ''))
                
                block_name = topic['block']
                all_topics.append(topic)
                topic_by_id[topic['id']] = topic
                
                if block_name not in topics_by_block:
                    topics_by_block[block_name] = []
                    blocks[block_name] = {"name": block_name, "topics": []}
                
                topics_by_block[block_name].append(topic)
        
        # Если блоков не создано, создаём дефолтный
        if not blocks:
            blocks = {"Общие темы": {"name": "Общие темы", "topics": all_topics}}
            topics_by_block = {"Общие темы": all_topics}
            
            # Обновляем блок у всех тем
            for topic in all_topics:
                topic['block'] = "Общие темы"
        
        task25_data = {
            "topics": all_topics,
            "topic_by_id": topic_by_id,
            "topics_by_block": topics_by_block,
            "blocks": blocks
        }
        
        # Создаём селектор если модуль доступен
        if TopicSelector:
            topic_selector = TopicSelector(all_topics)
        
        logger.info(f"Loaded {len(all_topics)} topics for task25")
        logger.info(f"Blocks: {list(topics_by_block.keys())}")
        
        # Сохраняем в кэш
        if cache:
            await cache.set('task25_data', task25_data)
            
    except Exception as e:
        logger.error(f"Failed to load task25 data: {e}", exc_info=True)
        task25_data = {"topics": [], "blocks": {}, "topics_by_block": {}}
        topic_selector = None
    
    # Инициализируем AI evaluator
    if AI_EVALUATOR_AVAILABLE:
        try:
            strictness_level = StrictnessLevel[os.getenv('TASK25_STRICTNESS', 'STANDARD').upper()]
            logger.info(f"Using strictness level: {strictness_level.value}")
        except (KeyError, AttributeError):
            strictness_level = StrictnessLevel.STANDARD if StrictnessLevel else None
            logger.info("Using default strictness level: STANDARD")
        
        if strictness_level:
            try:
                evaluator = Task25AIEvaluator(strictness=strictness_level)
                logger.info(f"Task25 AI evaluator initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize AI evaluator: {e}", exc_info=True)
                evaluator = None
    else:
        logger.warning("AI evaluator not available for task25")
        evaluator = None


def _determine_block(title: str) -> str:
    """Определяет блок темы по ключевым словам в заголовке."""
    title_lower = title.lower()
    
    # Ключевые слова для каждого блока
    block_keywords = {
        "Человек и общество": ["человек", "общество", "личность", "социализация", "культура", "мировоззрение"],
        "Экономика": ["экономика", "рынок", "спрос", "предложение", "деньги", "банк", "предприятие", "бизнес"],
        "Социальные отношения": ["семья", "социальная", "группа", "страта", "мобильность", "конфликт"],
        "Политика": ["политика", "власть", "государство", "демократия", "выборы", "партия", "президент"],
        "Право": ["право", "закон", "конституция", "суд", "преступление", "правонарушение", "юридическая"]
    }
    
    # Проверяем каждый блок
    for block, keywords in block_keywords.items():
        for keyword in keywords:
            if keyword in title_lower:
                return block
    
    # Если не удалось определить - возвращаем общий блок
    return "Общие темы"

async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в задание 25 из главного меню."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📝 <b>Задание 25 - Развёрнутый ответ</b>\n\n"
        "Задание проверяет умение:\n"
        "• Обосновывать теоретические положения\n"
        "• Отвечать на конкретные вопросы\n"
        "• Приводить развёрнутые примеры\n\n"
        "Максимальный балл: <b>6</b>\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t25_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t25_theory")],
        [InlineKeyboardButton("🏦 Банк ответов", callback_data="t25_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t25_progress")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="t25_settings")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики."""
    query = update.callback_query
    await query.answer()
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Выбрать блок", callback_data="t25_select_block")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t25_random_all")],
        [InlineKeyboardButton("📋 Список всех тем", callback_data="t25_list_topics")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        "💪 <b>Режим практики</b>\n\n"
        "Выберите способ выбора темы:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ теории и советов."""
    query = update.callback_query
    await query.answer()
    
    text = """📚 <b>Теория и советы по заданию 25</b>

<b>Структура задания:</b>
Задание 25 состоит из трёх частей:
1️⃣ <b>Обоснование</b> (2 балла)
2️⃣ <b>Ответ на вопрос</b> (1 балл)
3️⃣ <b>Примеры</b> (3 балла)

<b>Часть 1 - Обоснование:</b>
• Несколько связанных предложений
• Опора на теорию обществознания
• Причинно-следственные связи
• Использование терминов

<b>Часть 2 - Ответ на вопрос:</b>
• Точный и конкретный ответ
• Все элементы из вопроса
• Российская специфика (если требуется)

<b>Часть 3 - Примеры:</b>
• Три развёрнутых примера
• Конкретные детали (имена, даты, места)
• Разные аспекты темы
• Актуальность для РФ

<b>💡 Советы:</b>
• Читайте задание целиком перед ответом
• Структурируйте ответ по частям
• Используйте нумерацию
• Проверяйте соответствие требованиям

<b>⚠️ Частые ошибки:</b>
• Игнорирование одной из частей
• Абстрактные примеры
• Фактические ошибки
• Несоответствие российским реалиям"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока тем."""
    query = update.callback_query
    await query.answer()
    
    blocks = list(task25_data.get("blocks", {}).keys())
    
    if not blocks:
        await query.edit_message_text(
            "❌ Блоки тем не найдены",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    text = "📚 <b>Выберите блок тем:</b>"
    
    kb_buttons = []
    for block in blocks:
        topics_count = len(task25_data["topics_by_block"].get(block, []))
        kb_buttons.append([
            InlineKeyboardButton(
                f"{block} ({topics_count} тем)",
                callback_data=f"t25_block:{block}"
            )
        ])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_BLOCK


async def block_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбранного блока."""
    query = update.callback_query
    await query.answer()
    
    block_name = query.data.split(":", 1)[1]
    context.user_data["selected_block"] = block_name
    
    topics = task25_data.get("topics_by_block", {}).get(block_name, [])
    
    text = f"📚 <b>Блок: {block_name}</b>\n"
    text += f"Доступно тем: {len(topics)}\n\n"
    text += "Выберите действие:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Список тем", callback_data=f"t25_list_topics:page:0")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t25_random_block")],
        [InlineKeyboardButton("⬅️ К блокам", callback_data="t25_select_block")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_BLOCK


def _build_topic_message(topic: Dict) -> str:
    """Формирует текст сообщения с заданием по теме."""
    return (
        "📝 <b>Задание 25</b>\n\n"
        f"<b>Тема:</b> {topic['title']}\n"
        f"<b>Блок:</b> {topic['block']}\n\n"
        f"<b>Задание:</b>\n{topic['task_text']}\n\n"
        "<b>Требования к ответу:</b>\n"
        "1️⃣ Обоснование (2 балла)\n"
        "2️⃣ Ответ на вопрос (1 балл)\n"
        "3️⃣ Три примера (3 балла)\n\n"
        "💡 <i>Отправьте развёрнутый ответ одним сообщением</i>"
    )


async def random_topic_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайная тема из всех."""
    query = update.callback_query
    await query.answer()
    
    topics = task25_data.get("topics", [])
    if not topics:
        await query.answer("Темы не найдены", show_alert=True)
        return states.CHOOSING_MODE
    
    topic = random.choice(topics)
    context.user_data['current_topic'] = topic
    
    text = _build_topic_message(topic)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Другая тема", callback_data="t25_random_all")],
        [InlineKeyboardButton("⬅️ К выбору", callback_data="t25_practice")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа пользователя."""
    user_answer = update.message.text
    topic = context.user_data.get('current_topic')
    user_id = update.effective_user.id
    
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 К заданиям", callback_data="t25_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Показываем сообщение о проверке
    thinking_msg = await update.message.reply_text(
        "🤔 Анализирую ваш ответ..."
    )
    
    result = None
    
    try:
        # Проверяем наличие evaluator
        if evaluator and AI_EVALUATOR_AVAILABLE:
            logger.info(f"Using AI evaluator for user {user_id}")
            result = await evaluator.evaluate(
                answer=user_answer,
                topic=topic,
                user_id=user_id
            )
        else:
            logger.warning("AI evaluator not available, using basic evaluation")
            # Базовая проверка без AI
            parts = user_answer.split('\n\n')
            
            feedback = f"📊 <b>Результаты проверки</b>\n\n"
            feedback += f"<b>Тема:</b> {topic['title']}\n"
            feedback += f"<b>Частей в ответе:</b> {len(parts)}\n\n"
            
            if len(parts) >= 3:
                feedback += "✅ Структура ответа соответствует требованиям.\n"
                feedback += "📌 <b>Предварительная оценка:</b> 3-4 балла\n\n"
            else:
                feedback += "❌ Необходимо три части: обоснование, ответ, примеры.\n"
                feedback += "📌 <b>Предварительная оценка:</b> 0-2 балла\n\n"
            
            feedback += "⚠️ <i>AI-проверка недоступна. Обратитесь к преподавателю для детальной оценки.</i>"
            
            # Показываем эталонный ответ
            if 'example_answers' in topic:
                feedback += "\n\n📚 <b>Эталонный ответ:</b>\n\n"
                
                example = topic['example_answers']
                if 'part1' in example:
                    feedback += f"<b>1. Обоснование:</b>\n{example['part1']['answer']}\n\n"
                if 'part2' in example:
                    feedback += f"<b>2. Ответ на вопрос:</b>\n{example['part2']['answer']}\n\n"
                if 'part3' in example:
                    feedback += "<b>3. Примеры:</b>\n"
                    for i, ex in enumerate(example['part3'], 1):
                        feedback += f"{i}) <i>{ex['type']}:</i> {ex['example']}\n"
    
    except Exception as e:
        logger.error(f"Error during evaluation: {e}", exc_info=True)
        feedback = (
            "❌ Произошла ошибка при проверке.\n"
            "Попробуйте ещё раз или обратитесь к администратору."
        )
    
    # Удаляем сообщение о проверке
    try:
        await thinking_msg.delete()
    except:
        pass
    
    # Формируем итоговое сообщение
    if result and isinstance(result, EvaluationResult):
        feedback = _format_evaluation_result(result, topic)
    
    # Сохраняем результат
    if 'practice_stats' not in context.user_data:
        context.user_data['practice_stats'] = {}
    
    topic_id = topic['id']
    if topic_id not in context.user_data['practice_stats']:
        context.user_data['practice_stats'][topic_id] = {
            'attempts': 0,
            'scores': []
        }
    
    context.user_data['practice_stats'][topic_id]['attempts'] += 1
    if result:
        context.user_data['practice_stats'][topic_id]['scores'].append(
            result.total_score if hasattr(result, 'total_score') else 0
        )
    
    # Кнопки действий
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Попробовать ещё раз", callback_data="t25_retry"),
            InlineKeyboardButton("➡️ Новая тема", callback_data="t25_new_topic")
        ],
        [
            InlineKeyboardButton("📊 Мой прогресс", callback_data="t25_progress"),
            InlineKeyboardButton("📝 В меню", callback_data="t25_menu")
        ]
    ])
    
    await update.message.reply_text(
        feedback,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_FEEDBACK


def _format_evaluation_result(result: EvaluationResult, topic: Dict) -> str:
    """Форматирует результат проверки."""
    feedback = f"📊 <b>Результаты проверки</b>\n\n"
    feedback += f"<b>Тема:</b> {topic['title']}\n\n"
    
    # Баллы по критериям
    feedback += "<b>Баллы по критериям:</b>\n"
    if hasattr(result, 'scores') and result.scores:
        for criterion, score in result.scores.items():
            max_score = 2 if criterion == "К1" else 1 if criterion == "К2" else 3
            feedback += f"{criterion}: {score}/{max_score}\n"
    
    feedback += f"\n<b>Итого:</b> {result.total_score}/{result.max_score} баллов\n\n"
    
    # Обратная связь
    if hasattr(result, 'feedback') and result.feedback:
        feedback += f"<b>Комментарий:</b>\n{result.feedback}\n\n"
    
    # Предложения по улучшению
    if hasattr(result, 'suggestions') and result.suggestions:
        feedback += "<b>Рекомендации:</b>\n"
        for suggestion in result.suggestions:
            feedback += f"• {suggestion}\n"
    
    return feedback


async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после получения результата."""
    query = update.callback_query
    await query.answer()
    
    action = query.data.split("_")[1]
    
    if action == "retry":
        # Повторяем то же задание
        topic = context.user_data.get('current_topic')
        if topic:
            text = _build_topic_message(topic)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Отмена", callback_data="t25_practice")]
            ])
            await query.edit_message_text(
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            return states.ANSWERING
    
    elif action == "new":
        # Выбираем новую тему
        return await random_topic_all(update, context)
    
    return states.CHOOSING_MODE


# Остальные обработчики...
async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Банк эталонных ответов."""
    query = update.callback_query
    await query.answer()
    
    # Начинаем с первой темы
    await show_example_topic(query, context, 0)
    return states.CHOOSING_MODE


async def show_example_topic(query, context: ContextTypes.DEFAULT_TYPE, topic_idx: int):
    """Показывает эталонный ответ для темы."""
    topics = task25_data.get('topics', [])
    
    if not topics or topic_idx >= len(topics):
        await query.edit_message_text("❌ Темы не найдены")
        return
    
    topic = topics[topic_idx]
    context.user_data['bank_current_idx'] = topic_idx
    
    text = f"🏦 <b>Банк эталонных ответов</b>\n\n"
    text += f"<b>Тема:</b> {topic['title']}\n"
    text += f"<b>Блок:</b> {topic['block']}\n\n"
    text += f"<b>Задание:</b>\n{topic['task_text']}\n\n"
    
    if 'example_answers' in topic:
        text += "<b>📚 Эталонный ответ:</b>\n\n"
        
        example = topic['example_answers']
        
        # Часть 1 - Обоснование
        if 'part1' in example:
            text += f"<b>1. Обоснование:</b>\n"
            text += f"{example['part1']['answer']}\n\n"
        
        # Часть 2 - Ответ на вопрос
        if 'part2' in example:
            text += f"<b>2. Ответ на вопрос:</b>\n"
            text += f"{example['part2']['answer']}\n\n"
        
        # Часть 3 - Примеры
        if 'part3' in example:
            text += "<b>3. Примеры:</b>\n"
            for i, ex in enumerate(example['part3'], 1):
                text += f"\n{i}) <i>{ex['type']}:</i>\n"
                text += f"{ex['example']}\n"
    
    # Навигация
    kb_buttons = []
    nav_row = []
    
    if topic_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"t25_bank_nav:{topic_idx-1}"))
    
    nav_row.append(InlineKeyboardButton(f"{topic_idx+1}/{len(topics)}", callback_data="noop"))
    
    if topic_idx < len(topics) - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"t25_bank_nav:{topic_idx+1}"))
    
    kb_buttons.append(nav_row)
    kb_buttons.append([InlineKeyboardButton("🔍 Поиск темы", callback_data="t25_bank_search")])
    kb_buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t25_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )


async def bank_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по банку примеров."""
    query = update.callback_query
    await query.answer()
    
    topic_idx = int(query.data.split(":")[1])
    await show_example_topic(query, context, topic_idx)
    return states.CHOOSING_MODE


async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прогресса пользователя."""
    query = update.callback_query
    await query.answer()
    
    stats = context.user_data.get('practice_stats', {})
    
    if not stats:
        text = "📊 <b>Ваш прогресс</b>\n\n"
        text += "Вы ещё не решали задания 25.\n"
        text += "Начните практику прямо сейчас!"
    else:
        text = "📊 <b>Ваш прогресс по заданию 25</b>\n\n"
        
        total_attempts = sum(s['attempts'] for s in stats.values())
        total_topics = len(stats)
        
        all_scores = []
        for topic_stats in stats.values():
            all_scores.extend(topic_stats.get('scores', []))
        
        if all_scores:
            avg_score = sum(all_scores) / len(all_scores)
            max_achieved = max(all_scores)
            text += f"📈 <b>Общая статистика:</b>\n"
            text += f"• Решено тем: {total_topics}\n"
            text += f"• Всего попыток: {total_attempts}\n"
            text += f"• Средний балл: {avg_score:.1f}/6\n"
            text += f"• Лучший результат: {max_achieved}/6\n\n"
            
            # Прогресс по блокам
            block_stats = {}
            for topic_id, topic_stat in stats.items():
                topic = task25_data.get('topic_by_id', {}).get(int(topic_id))
                if topic:
                    block = topic.get('block', 'Другое')
                    if block not in block_stats:
                        block_stats[block] = {'topics': 0, 'scores': []}
                    block_stats[block]['topics'] += 1
                    block_stats[block]['scores'].extend(topic_stat.get('scores', []))
            
            if block_stats:
                text += "📚 <b>По блокам:</b>\n"
                for block, data in block_stats.items():
                    if data['scores']:
                        avg = sum(data['scores']) / len(data['scores'])
                        text += f"• {block}: {data['topics']} тем, средний балл {avg:.1f}\n"
        else:
            text += "Начните решать задания, чтобы увидеть статистику!\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Подробная статистика", callback_data="t25_detailed_progress")],
        [InlineKeyboardButton("🎯 К практике", callback_data="t25_practice")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def settings_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки модуля."""
    query = update.callback_query
    await query.answer()
    
    current_strictness = "Не установлен"
    if evaluator and hasattr(evaluator, 'strictness'):
        current_strictness = evaluator.strictness.value
    
    text = f"""⚙️ <b>Настройки задания 25</b>

<b>Текущие настройки:</b>
• Уровень проверки: {current_strictness}
• AI-проверка: {'✅ Включена' if AI_EVALUATOR_AVAILABLE else '❌ Выключена'}

<b>Уровни проверки:</b>
🟢 <b>Мягкий</b> - для начального обучения
🟡 <b>Стандартный</b> - оптимальный баланс
🔴 <b>Строгий</b> - как на реальном ЕГЭ
🟣 <b>Экспертный</b> - максимальная строгость"""
    
    kb_buttons = []
    
    if AI_EVALUATOR_AVAILABLE and StrictnessLevel:
        kb_buttons.extend([
            [InlineKeyboardButton("🟢 Мягкий", callback_data="t25_strictness:lenient")],
            [InlineKeyboardButton("🟡 Стандартный", callback_data="t25_strictness:standard")],
            [InlineKeyboardButton("🔴 Строгий", callback_data="t25_strictness:strict")],
            [InlineKeyboardButton("🟣 Экспертный", callback_data="t25_strictness:expert")]
        ])
    
    kb_buttons.extend([
        [InlineKeyboardButton("🗑 Сбросить прогресс", callback_data="t25_reset_progress")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


# Вспомогательные функции
async def cmd_task25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task25."""
    text = (
        "📝 <b>Задание 25 - Развёрнутый ответ</b>\n\n"
        "Используйте меню ниже для навигации:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t25_practice")],
        [InlineKeyboardButton("📚 Теория", callback_data="t25_theory")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    await update.message.reply_text(
        "Действие отменено. Используйте /task25 для продолжения."
    )
    return ConversationHandler.END


async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 25."""
    return await entry_from_menu(update, context)


async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👋 Что хотите потренировать?",
        reply_markup=build_main_menu()
    )
    
    return ConversationHandler.END


async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик."""
    query = update.callback_query
    await query.answer()
    return None


# Дополнительные обработчики...
async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка тем с пагинацией."""
    # Реализация пагинации...
    pass


async def random_topic_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайная тема из выбранного блока."""
    # Реализация...
    pass


async def bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск в банке ответов."""
    # Реализация...
    pass


async def handle_bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поискового запроса."""
    # Реализация...
    pass


async def handle_settings_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий в настройках."""
    # Реализация...
    pass


async def set_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка уровня строгости."""
    # Реализация...
    pass


async def show_block_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика по блокам."""
    # Реализация...
    pass


async def detailed_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальный прогресс."""
    # Реализация...
    pass

def _format_evaluation_result(result: EvaluationResult, topic: Dict) -> str:
    """Форматирует результат проверки для отображения пользователю."""
    
    # Заголовок с темой
    formatted = f"📊 <b>Результаты проверки</b>\n\n"
    formatted += f"<b>Тема:</b> {topic.get('title', 'Не указана')}\n"
    formatted += f"{'─' * 30}\n\n"
    
    # Если есть основная обратная связь от AI, используем её
    if hasattr(result, 'feedback') and result.feedback:
        formatted += result.feedback
    else:
        # Иначе форматируем вручную
        scores = result.scores if hasattr(result, 'scores') else {}
        
        # К1 - Обоснование
        k1_score = scores.get('k1', 0)
        formatted += f"<b>К1 (Обоснование):</b> {k1_score}/2\n"
        if k1_score == 2:
            formatted += "✅ Развёрнутое обоснование с опорой на теорию\n"
        elif k1_score == 1:
            formatted += "⚠️ Обоснование есть, но недостаточно развёрнутое\n"
        else:
            formatted += "❌ Обоснование отсутствует или неверное\n"
        
        # К2 - Ответ на вопрос
        k2_score = scores.get('k2', 0)
        formatted += f"\n<b>К2 (Ответ на вопрос):</b> {k2_score}/1\n"
        if k2_score == 1:
            formatted += "✅ Дан правильный и полный ответ\n"
        else:
            formatted += "❌ Ответ неверный или отсутствует\n"
        
        # К3 - Примеры
        k3_score = scores.get('k3', 0)
        formatted += f"\n<b>К3 (Примеры):</b> {k3_score}/3\n"
        if k3_score == 3:
            formatted += "✅ Приведены три корректных развёрнутых примера\n"
        elif k3_score > 0:
            formatted += f"⚠️ Засчитано примеров: {k3_score}\n"
        else:
            formatted += "❌ Корректные примеры отсутствуют\n"
        
        # Итоговый балл
        total = result.total_score if hasattr(result, 'total_score') else sum(scores.values())
        formatted += f"\n{'─' * 30}\n"
        formatted += f"<b>Итого:</b> {total}/6 баллов\n"
    
    # Добавляем эмодзи в зависимости от результата
    total = result.total_score if hasattr(result, 'total_score') else 0
    if total >= 5:
        formatted += "\n🎉 Отличный результат!"
    elif total >= 3:
        formatted += "\n👍 Хороший результат!"
    elif total >= 1:
        formatted += "\n💪 Есть над чем поработать!"
    else:
        formatted += "\n📚 Рекомендуем изучить теорию и примеры!"
    
    # Показываем эталонный ответ, если результат низкий
    if total < 4 and 'example_answers' in topic:
        formatted += "\n\n" + _format_example_answer(topic)
    
    return formatted


def _format_example_answer(topic: Dict) -> str:
    """Форматирует эталонный ответ для показа."""
    example = topic.get('example_answers', {})
    if not example:
        return ""
    
    formatted = "📚 <b>Эталонный ответ:</b>\n\n"
    
    # Часть 1 - Обоснование
    if 'part1' in example:
        formatted += f"<b>1. Обоснование:</b>\n"
        formatted += f"{example['part1'].get('answer', '')}\n\n"
    
    # Часть 2 - Ответ на вопрос
    if 'part2' in example:
        formatted += f"<b>2. Ответ на вопрос:</b>\n"
        formatted += f"{example['part2'].get('answer', '')}\n\n"
    
    # Часть 3 - Примеры
    if 'part3' in example:
        formatted += "<b>3. Примеры:</b>\n"
        for i, ex in enumerate(example['part3'], 1):
            ex_type = ex.get('type', 'Пример')
            ex_text = ex.get('example', '')
            formatted += f"{i}) <i>{ex_type}:</i> {ex_text}\n"
    
    return formatted


async def handle_strictness_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик изменения уровня строгости."""
    query = update.callback_query
    await query.answer()
    
    # Парсим уровень из callback_data
    _, level_str = query.data.split(':')
    
    global evaluator
    
    try:
        # Определяем новый уровень
        new_level = StrictnessLevel[level_str.upper()]
        
        # Пересоздаём evaluator с новым уровнем
        if AI_EVALUATOR_AVAILABLE:
            evaluator = Task25AIEvaluator(strictness=new_level)
            
            await query.answer(f"✅ Установлен уровень: {new_level.value}", show_alert=True)
            logger.info(f"Changed strictness level to {new_level.value}")
        else:
            await query.answer("❌ AI-проверка недоступна", show_alert=True)
            
    except Exception as e:
        logger.error(f"Error changing strictness: {e}")
        await query.answer("❌ Ошибка при изменении настроек", show_alert=True)
    
    # Возвращаемся в меню настроек
    return await show_settings(update, context)


async def handle_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает прогресс пользователя."""
    query = update.callback_query
    await query.answer()
    
    stats = context.user_data.get('practice_stats', {})
    
    if not stats:
        text = "📊 <b>Ваш прогресс</b>\n\n"
        text += "Вы ещё не решали задания. Начните практику!"
    else:
        text = "📊 <b>Ваш прогресс</b>\n\n"
        
        total_attempts = 0
        total_score = 0
        topics_tried = 0
        
        for topic_id, topic_stats in stats.items():
            if topic_stats['attempts'] > 0:
                topics_tried += 1
                total_attempts += topic_stats['attempts']
                if topic_stats['scores']:
                    # Берём лучший результат по теме
                    best_score = max(topic_stats['scores'])
                    total_score += best_score
        
        if topics_tried > 0:
            avg_score = total_score / topics_tried
            text += f"<b>Тем изучено:</b> {topics_tried}\n"
            text += f"<b>Всего попыток:</b> {total_attempts}\n"
            text += f"<b>Средний балл:</b> {avg_score:.1f}/6\n\n"
            
            # Детализация по темам
            text += "<b>По темам:</b>\n"
            for topic_id, topic_stats in stats.items():
                if topic_stats['attempts'] > 0:
                    topic = task25_data.get('topic_by_id', {}).get(topic_id, {})
                    topic_title = topic.get('title', 'Неизвестная тема')[:30]
                    
                    if topic_stats['scores']:
                        best = max(topic_stats['scores'])
                        last = topic_stats['scores'][-1]
                        text += f"• {topic_title}: {best}/6 (попыток: {topic_stats['attempts']})\n"
        else:
            text += "Начните практику для отслеживания прогресса!"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def handle_reset_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс прогресса пользователя."""
    query = update.callback_query
    
    # Очищаем статистику
    context.user_data['practice_stats'] = {}
    
    await query.answer("✅ Прогресс сброшен", show_alert=True)
    
    # Возвращаемся в настройки
    return await show_settings(update, context)

async def choose_practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор режима практики."""
    query = update.callback_query
    await query.answer()
    
    text = "💪 <b>Режим практики</b>\n\nВыберите способ выбора темы:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t25_random")],
        [InlineKeyboardButton("📚 По блокам", callback_data="t25_by_block")],
        [InlineKeyboardButton("📈 По сложности", callback_data="t25_by_difficulty")],
        [InlineKeyboardButton("🎯 Рекомендованная", callback_data="t25_recommended")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def handle_random_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор случайной темы."""
    query = update.callback_query
    await query.answer()
    
    if topic_selector:
        user_id = update.effective_user.id
        topic = topic_selector.get_random_topic(user_id)
    else:
        # Fallback - простой случайный выбор
        if task25_data.get('topics'):
            topic = random.choice(task25_data['topics'])
        else:
            topic = None
    
    if not topic:
        await query.answer("❌ Темы не найдены", show_alert=True)
        return states.CHOOSING_MODE
    
    # Сохраняем тему
    context.user_data['current_topic'] = topic
    
    # Форматируем и показываем
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>",
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_ANSWER


async def choose_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока для практики."""
    query = update.callback_query
    await query.answer()
    
    blocks = list(task25_data.get("blocks", {}).keys())
    
    if not blocks:
        await query.edit_message_text(
            "❌ Блоки тем не найдены",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    text = "📚 <b>Выберите блок тем:</b>"
    
    kb_buttons = []
    for block in blocks:
        topics_count = len(task25_data["topics_by_block"].get(block, []))
        kb_buttons.append([
            InlineKeyboardButton(
                f"{block} ({topics_count} тем)",
                callback_data=f"t25_block:{block}"
            )
        ])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def handle_by_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор темы по сложности."""
    query = update.callback_query
    await query.answer()
    
    text = "📊 <b>Выберите уровень сложности:</b>"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Лёгкий", callback_data="t25_diff:easy")],
        [InlineKeyboardButton("🟡 Средний", callback_data="t25_diff:medium")],
        [InlineKeyboardButton("🔴 Сложный", callback_data="t25_diff:hard")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def handle_difficulty_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбранной сложности."""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем уровень сложности
    _, difficulty = query.data.split(':')
    
    if topic_selector:
        user_id = update.effective_user.id
        topic = topic_selector.get_topic_by_difficulty(user_id, difficulty)
    else:
        # Fallback
        topics = [t for t in task25_data.get('topics', []) 
                 if t.get('difficulty', 'medium') == difficulty]
        topic = random.choice(topics) if topics else None
    
    if not topic:
        await query.answer(f"❌ Нет тем уровня {difficulty}", show_alert=True)
        return states.CHOOSING_MODE
    
    # Сохраняем тему
    context.user_data['current_topic'] = topic
    
    # Показываем тему
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>",
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_ANSWER


async def handle_recommended(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор рекомендованной темы."""
    query = update.callback_query
    await query.answer()
    
    user_stats = context.user_data.get('practice_stats', {})
    
    if topic_selector and user_stats:
        user_id = update.effective_user.id
        topic = topic_selector.get_recommended_topic(user_id, user_stats)
    else:
        # Если нет статистики - даём случайную тему средней сложности
        topics = [t for t in task25_data.get('topics', []) 
                 if t.get('difficulty', 'medium') == 'medium']
        topic = random.choice(topics) if topics else None
    
    if not topic:
        await query.answer("❌ Не удалось подобрать тему", show_alert=True)
        return states.CHOOSING_MODE
    
    # Сохраняем тему
    context.user_data['current_topic'] = topic
    
    # Показываем с пояснением
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    recommendation_text = "🎯 <b>Рекомендованная тема</b>\n"
    if user_stats:
        recommendation_text += "<i>Выбрана на основе вашей статистики</i>\n\n"
    else:
        recommendation_text += "<i>Начните с темы средней сложности</i>\n\n"
    
    await query.edit_message_text(
        recommendation_text + topic_text + "\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>",
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_ANSWER


# Обновлённая функция регистрации обработчиков
def register_task25_handlers(app):
    """Регистрация всех обработчиков задания 25."""
    from telegram.ext import CommandHandler, CallbackQueryHandler, MessageHandler, filters
    
    # Команды
    app.add_handler(CommandHandler("task25", cmd_task25))
    
    # Основное меню
    app.add_handler(CallbackQueryHandler(entry_from_menu, pattern="^t25_menu$"))
    app.add_handler(CallbackQueryHandler(choose_practice_mode, pattern="^t25_practice$"))
    app.add_handler(CallbackQueryHandler(show_theory, pattern="^t25_theory$"))
    app.add_handler(CallbackQueryHandler(show_settings, pattern="^t25_settings$"))
    
    # Выбор темы
    app.add_handler(CallbackQueryHandler(handle_random_topic, pattern="^t25_random$"))
    app.add_handler(CallbackQueryHandler(choose_block, pattern="^t25_by_block$"))
    app.add_handler(CallbackQueryHandler(handle_by_difficulty, pattern="^t25_by_difficulty$"))
    app.add_handler(CallbackQueryHandler(handle_recommended, pattern="^t25_recommended$"))
    
    # Обработка выбора
    app.add_handler(CallbackQueryHandler(handle_topic_by_block, pattern="^t25_block:"))
    app.add_handler(CallbackQueryHandler(handle_difficulty_selected, pattern="^t25_diff:"))
    
    # После ответа
    app.add_handler(CallbackQueryHandler(handle_retry, pattern="^t25_retry$"))
    app.add_handler(CallbackQueryHandler(handle_new_topic, pattern="^t25_new_topic$"))
    app.add_handler(CallbackQueryHandler(handle_progress, pattern="^t25_progress$"))
    
    # Настройки
    app.add_handler(CallbackQueryHandler(handle_strictness_change, pattern="^t25_strictness:"))
    app.add_handler(CallbackQueryHandler(handle_reset_progress, pattern="^t25_reset_progress$"))
    
    # Обработчик текстовых ответов (для любого состояния AWAITING_ANSWER)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_answer
    ), group=1)  # Используем группу для приоритета
    
    # Возврат в главное меню
    app.add_handler(CallbackQueryHandler(back_to_main_menu, pattern="^to_main_menu$"))