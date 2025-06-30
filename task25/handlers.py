import logging
import os
import json
import random
from typing import Optional, Dict, List
from datetime import datetime
from core.document_processor import DocumentHandlerMixin
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
from core.admin_tools import admin_manager
from core import states
from core.plugin_loader import build_main_menu
from core.universal_ui import UniversalUIComponents, AdaptiveKeyboards, MessageFormatter
from core.states import ANSWERING_PARTS, CHOOSING_BLOCK_T25
from core.ui_helpers import (
    show_thinking_animation,
    show_extended_thinking_animation,  # Добавить
    show_streak_notification,
    get_personalized_greeting,
    get_motivational_message,
    create_visual_progress
)
from core.error_handler import safe_handler, auto_answer_callback
from core.state_validator import validate_state_transition, state_validator
from telegram.ext import ConversationHandler

logger = logging.getLogger(__name__)

# Глобальные переменные
task25_data = {}
topic_selector = None
evaluator = None

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
            # Проверяем, что данные действительно загружены и корректны
            if (isinstance(cached_data, dict) and 
                'topics' in cached_data and 
                cached_data['topics']):  # Проверяем, что topics не пустой
                
                task25_data = cached_data
                if TopicSelector:
                    topic_selector = TopicSelector(task25_data['topics'])
                logger.info(f"Loaded task25 data from cache: {len(task25_data['topics'])} topics")
                
                # Инициализируем evaluator после загрузки данных
                _init_evaluator()
                return
            else:
                logger.warning("Cached data is invalid, loading from file")
                # Удаляем невалидный кэш
                await cache.delete('task25_data')
    
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
        
        # Если данные не пустые, формируем итоговую структуру
        if all_topics:
            # Добавляем темы без блока в "Общие темы"
            for topic in all_topics:
                if not topic.get('block'):
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
            
            # Сохраняем в кэш только если данные валидны
            if cache and all_topics:
                await cache.set('task25_data', task25_data, ttl=86400)  # 24 часа
        else:
            logger.error("No topics found in data file")
            task25_data = {"topics": [], "blocks": {}, "topics_by_block": {}}
            
    except Exception as e:
        logger.error(f"Failed to load task25 data: {e}", exc_info=True)
        task25_data = {"topics": [], "blocks": {}, "topics_by_block": {}}
        topic_selector = None
    
    # Инициализируем AI evaluator
    _init_evaluator()


def _init_evaluator():
    """Инициализация AI evaluator."""
    global evaluator
    
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

@safe_handler()
@validate_state_transition({ConversationHandler.END, None})
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в задание 25 из главного меню."""
    query = update.callback_query

    results = context.user_data.get('task25_results', [])
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(set(r.get('topic_id') for r in results)) / 100 * 100) if results else 0
    }

    greeting = get_personalized_greeting(user_stats)
    text = greeting + (
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

@safe_handler()
async def list_by_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ тем по уровню сложности с пагинацией."""
    query = update.callback_query
    
    # Парсим callback_data: t25_list_by_diff:easy
    parts = query.data.split(':')
    difficulty = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0
    
    # Фильтруем темы по сложности
    all_topics = task25_data.get('topics', [])
    topics = [t for t in all_topics if t.get('difficulty', 'medium') == difficulty]
    
    if not topics:
        return states.CHOOSING_MODE
    
    # Пагинация - 10 тем на страницу
    items_per_page = 10
    total_pages = (len(topics) + items_per_page - 1) // items_per_page
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(topics))
    
    # Названия уровней
    difficulty_names = {
        'easy': '🟢 Легкие темы',
        'medium': '🟡 Средние темы',
        'hard': '🔴 Сложные темы'
    }
    
    # Формируем текст
    text = f"<b>{difficulty_names.get(difficulty, 'Темы')}</b>\n"
    text += f"Страница {page + 1} из {total_pages}\n\n"
    
    # Получаем прогресс пользователя
    user_stats = context.user_data.get('task25_stats', {})
    completed_topics = set(user_stats.get('topics_completed', []))
    
    # Список тем на текущей странице
    buttons = []
    for i in range(start_idx, end_idx):
        topic = topics[i]
        topic_id = topic.get('id')
        
        # Определяем эмодзи статуса
        if topic_id in completed_topics:
            status = "✅"
        else:
            status = "📝"
        
        # Блок темы
        block = topic.get('block', 'Общие')
        
        # Сокращаем название если слишком длинное
        title = topic.get('title', 'Без названия')
        if len(title) > 30:
            title = title[:27] + "..."
        
        button_text = f"{status} {title}"
        buttons.append([InlineKeyboardButton(
            button_text,
            callback_data=f"t25_topic:{topic_id}"
        )])
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"t25_list_by_diff:{difficulty}:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"t25_list_by_diff:{difficulty}:{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("⬅️ К уровням", callback_data="t25_all_topics_list")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики."""
    query = update.callback_query
    
    # Очищаем контекст выбранного блока
    context.user_data.pop('selected_block', None)
    
    text = (
        "💪 <b>Режим практики</b>\n\n"
        "Выберите способ выбора темы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t25_random_all")],
        [InlineKeyboardButton("📚 Выбрать блок", callback_data="t25_select_block")],
        [InlineKeyboardButton("📋 Список всех тем", callback_data="t25_all_topics_list")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим теории и советов."""
    query = update.callback_query
    
    text = (
        "📚 <b>Теория по заданию 25</b>\n\n"
        "<b>Структура ответа:</b>\n"
        "1️⃣ <b>Обоснование (К1)</b> - 2 балла\n"
        "• Несколько предложений с теоретической аргументацией\n"
        "• Объяснение причинно-следственных связей\n"
        "• Опора на обществоведческие знания\n\n"
        
        "2️⃣ <b>Ответ на вопрос (К2)</b> - 1 балл\n"
        "• Чёткий и конкретный ответ\n"
        "• Полное соответствие поставленному вопросу\n\n"
        
        "3️⃣ <b>Примеры (К3)</b> - 3 балла\n"
        "• Три развёрнутых примера (по 1 баллу)\n"
        "• Конкретные ситуации из жизни РФ\n"
        "• Детали: имена, даты, места\n\n"
        
        "<b>💡 Советы:</b>\n"
        "• Внимательно читайте все части задания\n"
        "• Следите за логикой изложения\n"
        "• Используйте термины корректно\n"
        "• Проверяйте фактическую точность"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Примеры ответов", callback_data="t25_example_answers")],
        [InlineKeyboardButton("⚠️ Типичные ошибки", callback_data="t25_common_mistakes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_BLOCK})
async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока тем с улучшенным отображением."""
    query = update.callback_query
    
    blocks = task25_data.get("topics_by_block", {})
    
    text = "📚 <b>Выберите блок:</b>\n\n"
    buttons = []
    
    # Получаем статистику пользователя
    user_stats = context.user_data.get('task25_stats', {})
    completed_topics = set(user_stats.get('topics_completed', []))
    
    # Добавляем общую статистику
    total_topics = sum(len(topics) for topics in blocks.values())
    total_completed = len(completed_topics)
    
    text += f"📊 Общий прогресс: {total_completed}/{total_topics} тем\n\n"
    
    for block_name, topics in blocks.items():
        # Статистика по блоку
        completed_in_block = len([t for t in topics if t.get('id') in completed_topics])
        total_in_block = len(topics)
        
        # Эмодзи прогресса
        if completed_in_block == 0:
            emoji = "⚪"
        elif completed_in_block == total_in_block:
            emoji = "✅"
        else:
            percentage = (completed_in_block / total_in_block) * 100
            if percentage >= 50:
                emoji = "🟡"
            else:
                emoji = "🔵"
        
        button_text = f"{emoji} {block_name} (выполнено: {completed_in_block}/{total_in_block})"
        buttons.append([InlineKeyboardButton(button_text, callback_data=f"t25_block:{block_name}")])
    
    buttons.append([InlineKeyboardButton("🎲 Случайная тема", callback_data="t25_random_all")])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def another_topic_from_current(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Другая тема из текущего контекста (блок или все)."""
    query = update.callback_query
    
    # Проверяем, откуда пришел пользователь
    selected_block = context.user_data.get("selected_block")
    
    if selected_block:
        # Если был выбран блок, показываем случайную из блока
        return await random_topic_block(update, context)
    else:
        # Иначе случайную из всех
        return await random_topic_all(update, context)

@safe_handler()
async def block_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню конкретного блока."""
    query = update.callback_query
    
    block_name = query.data.split(":", 1)[1]
    context.user_data["selected_block"] = block_name
    
    topics = task25_data.get("topics_by_block", {}).get(block_name, [])
    
    # Статистика по блоку
    user_stats = context.user_data.get('task25_stats', {})
    completed_topics = set(user_stats.get('topics_completed', []))
    completed_in_block = len([t for t in topics if t.get('id') in completed_topics])
    
    text = f"📚 <b>Блок: {block_name}</b>\n"
    text += f"✅ Выполнено: {completed_in_block}/{len(topics)} тем\n\n"
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
    
    return states.CHOOSING_BLOCK_T25


def _build_topic_message(topic: Dict) -> str:
    """Формирует текст сообщения с заданием по теме."""
    text = "📝 <b>Задание 25</b>\n\n"
    
    # Информация о теме
    text += f"<b>Тема:</b> {topic.get('title', 'Не указана')}\n"
    text += f"<b>Блок:</b> {topic.get('block', 'Не указан')}\n"
    
    # Сложность
    if 'difficulty' in topic:
        diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(topic['difficulty'], "⚪")
        diff_text = {"easy": "Лёгкая", "medium": "Средняя", "hard": "Сложная"}.get(topic['difficulty'], topic['difficulty'])
        text += f"<b>Сложность:</b> {diff_emoji} {diff_text}\n"
    
    text += "\n"
    
    # Текст задания
    if 'parts' in topic:
        parts = topic['parts']
        text += "<b>Ваше задание:</b>\n\n"
        
        if 'part1' in parts:
            text += f"<b>1.</b> {parts['part1']}\n\n"
        
        if 'part2' in parts:
            text += f"<b>2.</b> {parts['part2']}\n\n"
        
        if 'part3' in parts:
            text += f"<b>3.</b> {parts['part3']}\n\n"
    else:
        text += f"<b>Задание:</b>\n{topic.get('task_text', 'Текст задания не указан')}\n\n"
    
    # Требования
    text += "📋 <b>Требования к ответу:</b>\n"
    text += "1️⃣ Развёрнутое обоснование (2 балла)\n"
    text += "2️⃣ Точный ответ на вопрос (1 балл)\n"
    text += "3️⃣ Три конкретных примера (3 балла)\n\n"
    
    text += "💡 <i>Отправьте развёрнутый ответ одним сообщением</i>"
    
    return text


@safe_handler()
async def random_topic_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайная тема из всех с правильными кнопками."""
    query = update.callback_query
    
    topics = task25_data.get("topics", [])
    if not topics:
        return states.CHOOSING_MODE
    
    # Приоритет непройденным темам
    user_stats = context.user_data.get('task25_stats', {})
    completed = set(user_stats.get('topics_completed', []))
    
    uncompleted = [t for t in topics if t.get('id') not in completed]
    topic_pool = uncompleted if uncompleted else topics
    
    topic = random.choice(topic_pool)
    context.user_data['current_topic'] = topic
    
    # Очищаем выбранный блок, так как выбрана случайная тема из всех
    context.user_data.pop('selected_block', None)
    
    text = _build_topic_message(topic)
    
    # Проверяем режим ответа
    settings = context.user_data.get('task25_settings', {})
    
    if settings.get('answer_mode') == 'parts':
        # Начинаем режим по частям
        context.user_data['current_part'] = 1
        context.user_data['part_answers'] = {}
        
        parts = topic.get('parts', {})
        part1_text = parts.get('part1', '')
        
        text = (
            f"📝 <b>Режим ответа по частям</b>\n\n"
            f"<b>Тема:</b> {topic['title']}\n\n"
            f"<b>Часть 1: Обоснование (2 балла)</b>\n\n"
            f"{part1_text}\n\n"
            f"💡 <i>Отправьте ваше обоснование</i>"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="t25_practice")]
        ])
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return ANSWERING_PARTS
    else:
        # Стандартный режим
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Другая тема", callback_data="t25_another_topic")],
            [InlineKeyboardButton("⬅️ К выбору", callback_data="t25_practice")]
        ])
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return states.ANSWERING

def _get_fallback_feedback(user_answer: str, topic: Dict) -> str:
    """Формирует базовую обратную связь без AI."""
    score = _estimate_score(user_answer)
    
    text = f"📊 <b>Результаты проверки</b>\n\n"
    text += f"<b>Тема:</b> {topic.get('title', 'Не указана')}\n"
    text += f"{'─' * 30}\n\n"
    
    # Примерная оценка
    text += f"<b>Предварительная оценка:</b> {score}/6 баллов\n\n"
    
    if score >= 5:
        text += "✅ Ваш ответ выглядит полным и развёрнутым.\n"
    elif score >= 3:
        text += "⚡ Ответ содержит основные элементы, но может быть улучшен.\n"
    else:
        text += "📝 Рекомендуется дополнить ответ.\n"
    
    text += "\n<b>Общие рекомендации:</b>\n"
    text += "• Убедитесь, что есть теоретическое обоснование\n"
    text += "• Проверьте наличие ответа на поставленный вопрос\n"
    text += "• Приведите 3 примера из разных источников\n"
    text += "\n⚠️ <i>Это предварительная оценка. Для точной проверки обратитесь к преподавателю.</i>"
    
    return text

async def safe_handle_answer_task25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Безопасная обработка ответа на задание 25."""
    
    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ В меню", callback_data="t25_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Проверяем наличие текста из документа
    if 'document_text' in context.user_data:
        user_answer = context.user_data.pop('document_text')
        logger.info("Using text from document")
    else:
        user_answer = update.message.text.strip()
        logger.info("Using text from message")
    
    # Проверяем минимальную длину
    if len(user_answer) < 100:
        await update.message.reply_text(
            "❌ Ответ слишком короткий. Задание 25 требует развёрнутого ответа с обоснованием и примерами.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отменить", callback_data="t25_menu")
            ]])
        )
        return states.ANSWERING
    
    # Показываем анимацию обработки
    thinking_msg = await show_thinking_animation(
        update.message,
        "Анализирую ваш ответ"
    )
    
    try:
        # Инициализируем evaluator если нужно
        global evaluator
        if evaluator is None and AI_EVALUATOR_AVAILABLE:
            try:
                strictness = StrictnessLevel.STANDARD
                evaluator = Task25AIEvaluator(strictness=strictness)
                logger.info("Task25 evaluator initialized")
            except Exception as e:
                logger.error(f"Failed to initialize evaluator: {e}")
                evaluator = None
        
        # Оцениваем ответ
        if evaluator and AI_EVALUATOR_AVAILABLE:
            try:
                result = await evaluator.evaluate(
                    answer=user_answer,
                    topic=topic,
                    user_id=update.effective_user.id
                )
                
                # Форматируем результат
                if hasattr(result, 'format_feedback'):
                    feedback_text = result.format_feedback()
                else:
                    feedback_text = _format_evaluation_result(result, topic)
                
                score = result.total_score
                
            except Exception as e:
                logger.error(f"Evaluation error: {e}")
                # Fallback оценка
                feedback_text = _get_fallback_feedback(user_answer, topic)
                score = _estimate_score(user_answer)
        else:
            # Простая оценка без AI
            feedback_text = _get_fallback_feedback(user_answer, topic)
            score = _estimate_score(user_answer)
        
        # Удаляем анимацию
        await thinking_msg.delete()
        
        # Сохраняем результат
        result_data = {
            'topic': topic['title'],
            'topic_id': topic.get('id'),
            'block': topic.get('block', 'Общее'),
            'score': score,
            'max_score': 6,
            'timestamp': datetime.now().isoformat()
        }
        
        if 'task25_results' not in context.user_data:
            context.user_data['task25_results'] = []
        context.user_data['task25_results'].append(result_data)
        
        # Обновляем серию правильных ответов
        if score >= 5:  # Считаем хорошим результатом 5+ баллов
            context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
            
            # Показываем уведомление о серии
            if context.user_data['correct_streak'] % 3 == 0:
                await show_streak_notification(
                    update.message,
                    context.user_data['correct_streak']
                )
        else:
            context.user_data['correct_streak'] = 0
        
        # Кнопки действий
        kb = AdaptiveKeyboards.create_result_keyboard(
            score=score,
            max_score=6,
            module_code="t25"
        )
        
        # Отправляем результат
        await update.message.reply_text(
            feedback_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        # Меняем состояние на AWAITING_FEEDBACK для обработки дальнейших действий
        return states.AWAITING_FEEDBACK
        
    except Exception as e:
        logger.error(f"Error in handle_answer: {e}")
        await thinking_msg.delete()
        await update.message.reply_text(
            "❌ Произошла ошибка при проверке. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Попробовать снова", callback_data="t25_retry"),
                InlineKeyboardButton("📝 В меню", callback_data="t25_menu")
            ]])
        )
        return states.CHOOSING_MODE


def _estimate_score(user_answer: str) -> int:
    """Примерная оценка без AI."""
    parts = user_answer.split('\n\n')
    if len(parts) >= 3:
        return 3  # Средний балл
    elif len(parts) >= 2:
        return 2
    else:
        return 1
        
@safe_handler()
@validate_state_transition({states.ANSWERING})
async def handle_answer_parts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа по частям."""
    user_answer = update.message.text
    topic = context.user_data.get('current_topic')
    current_part = context.user_data.get('current_part', 1)
    answers = context.user_data.get('part_answers', {})
    
    if not topic:
        await update.message.reply_text("❌ Ошибка: тема не выбрана.")
        return states.CHOOSING_MODE
    
    # Сохраняем ответ на текущую часть
    answers[f'part{current_part}'] = user_answer
    context.user_data['part_answers'] = answers
    
    # Переходим к следующей части или завершаем
    if current_part < 3:
        current_part += 1
        context.user_data['current_part'] = current_part
        
        # Показываем следующую часть
        parts = topic.get('parts', {})
        part_text = parts.get(f'part{current_part}', '')
        
        part_names = {
            2: "Ответ на вопрос",
            3: "Примеры"
        }
        
        text = (
            f"✅ Часть {current_part - 1} получена!\n\n"
            f"<b>Часть {current_part}: {part_names.get(current_part, '')}</b>\n\n"
            f"{part_text}\n\n"
            f"💡 <i>Отправьте ваш ответ</i>"
        )
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML
        )
        
        return ANSWERING_PARTS  # Используем константу из states
    
    else:
        # Все части собраны, объединяем и проверяем
        full_answer = "\n\n".join([
            f"Часть 1 (Обоснование):\n{answers.get('part1', '')}",
            f"Часть 2 (Ответ):\n{answers.get('part2', '')}",
            f"Часть 3 (Примеры):\n{answers.get('part3', '')}"
        ])
        
        # Очищаем временные данные
        context.user_data.pop('part_answers', None)
        context.user_data.pop('current_part', None)
        
        # Сохраняем полный ответ для проверки
        context.user_data['full_answer'] = full_answer
        
        # Вызываем стандартную функцию проверки
        # Создаем фиктивное обновление с полным текстом
        update.message.text = full_answer
        return await handle_answer(update, context)


def _format_evaluation_result(result: EvaluationResult, topic: Dict) -> str:
    """Форматирует результат AI-оценки для отображения."""
    score = result.total_score
    max_score = result.max_score
    
    # Заголовок в зависимости от результата
    if score >= 5:
        header = "🎉 <b>Отличный результат!</b>"
    elif score >= 3:
        header = "👍 <b>Хороший ответ!</b>"
    else:
        header = "📝 <b>Нужно доработать</b>"
    
    text = f"{header}\n\n"
    text += f"<b>Ваш балл:</b> {score} из {max_score}\n\n"
    
    # Детальная разбивка по критериям
    if hasattr(result, 'criteria_scores') and result.criteria_scores:
        text += "<b>📊 Детальная оценка:</b>\n"
        text += f"• К1 (Обоснование): {result.criteria_scores.get('k1_score', 0)}/2\n"
        text += f"• К2 (Ответ на вопрос): {result.criteria_scores.get('k2_score', 0)}/1\n"
        text += f"• К3 (Примеры): {result.criteria_scores.get('k3_score', 0)}/3\n\n"
    
    # Обратная связь
    if result.feedback:
        text += f"<b>💭 Комментарий:</b>\n{result.feedback}\n\n"
    
    # ИСПРАВЛЕНО: используем правильное имя атрибута detailed_feedback
    if hasattr(result, 'detailed_feedback') and result.detailed_feedback:
        detail = result.detailed_feedback
        if isinstance(detail, dict):
            if detail.get('k1_comment'):
                text += f"<b>📌 Обоснование:</b> {detail['k1_comment']}\n"
            if detail.get('k2_comment'):
                text += f"<b>📌 Ответ:</b> {detail['k2_comment']}\n"
            if detail.get('k3_comment'):
                text += f"<b>📌 Примеры:</b> {detail['k3_comment']}\n"
            
            # Найденные примеры
            if detail.get('k3_examples_found'):
                examples = detail['k3_examples_found']
                if examples and isinstance(examples, list):
                    text += "\n<b>Найденные примеры:</b>\n"
                    for i, ex in enumerate(examples[:3], 1):
                        text += f"{i}. {ex}\n"
    
    # Рекомендации
    if hasattr(result, 'suggestions') and result.suggestions:
        text += "\n<b>💡 Рекомендации:</b>\n"
        for suggestion in result.suggestions[:3]:
            text += f"• {suggestion}\n"
    
    # Фактические ошибки
    if hasattr(result, 'factual_errors') and result.factual_errors:
        text += "\n<b>⚠️ Фактические ошибки:</b>\n"
        for error in result.factual_errors[:3]:
            text += f"• {error}\n"
    
    return text.strip()


@safe_handler()
async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после получения результата."""
    query = update.callback_query
    
    action = query.data.split('_')[-1]
    
    # Используем универсальные callback_data
    if action == 'retry':
        return await handle_retry(update, context)
    elif action == 'new':
        return await random_topic_all(update, context)
    elif action == 'theory':
        return await theory_mode(update, context)
    elif action == 'examples':
        return await bank_examples(update, context)
    elif action == 'menu':
        return await return_to_menu(update, context)
    
    return states.CHOOSING_MODE


@safe_handler()
async def search_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало поиска примеров."""
    query = update.callback_query
    
    text = (
        "🔍 <b>Поиск примеров</b>\n\n"
        "Введите ключевые слова для поиска.\n"
        "Например: <i>семья, экономика, право</i>\n\n"
        "Отправьте /cancel для отмены"
    )
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML
    )
    
    return states.SEARCHING

@safe_handler()
async def examples_by_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Примеры по блокам."""
    query = update.callback_query
    
    blocks = task25_data.get("topics_by_block", {})
    
    text = "📚 <b>Примеры по блокам</b>\n\nВыберите блок:"
    buttons = []
    
    for block_name in blocks.keys():
        buttons.append([InlineKeyboardButton(
            block_name,
            callback_data=f"t25_examples_block:{block_name}"
        )])
    
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_examples")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def best_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ лучших примеров."""
    query = update.callback_query
    
    # Выбираем 5 случайных тем с примерами
    topics_with_examples = [
        t for t in task25_data.get('topics', [])
        if 'example_answers' in t
    ]
    
    if not topics_with_examples:
        return states.CHOOSING_MODE
    
    sample_topics = random.sample(
        topics_with_examples,
        min(5, len(topics_with_examples))
    )
    
    text = "⭐ <b>Лучшие примеры ответов</b>\n\n"
    buttons = []
    
    for i, topic in enumerate(sample_topics, 1):
        text += f"{i}. {topic['title']}\n"
        buttons.append([InlineKeyboardButton(
            f"👁 Пример {i}",
            callback_data=f"t25_show_example:{topic['id']}"
        )])
    
    buttons.append([InlineKeyboardButton("🔄 Другие примеры", callback_data="t25_best_examples")])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_examples")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def show_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ примера ответа."""
    query = update.callback_query
    
    topic_id = query.data.split(':')[1]
    topic = task25_data.get("topic_by_id", {}).get(topic_id)
    
    if not topic or 'example_answers' not in topic:
        return states.CHOOSING_MODE
    
    example = topic['example_answers']
    
    text = f"📝 <b>Пример ответа</b>\n\n"
    text += f"<b>Тема:</b> {topic['title']}\n\n"
    
    # Показываем части задания
    parts = topic.get('parts', {})
    if parts:
        text += "<b>Задание:</b>\n"
        if parts.get('part1'):
            text += f"1) {parts['part1']}\n"
        if parts.get('part2'):
            text += f"2) {parts['part2']}\n"
        if parts.get('part3'):
            text += f"3) {parts['part3']}\n"
        text += "\n"
    
    # Эталонный ответ
    text += "<b>Эталонный ответ:</b>\n\n"
    
    if isinstance(example.get('part1'), dict):
        text += f"<b>1. Обоснование (2 балла):</b>\n{example['part1']['answer']}\n\n"
    elif 'part1' in example:
        text += f"<b>1. Обоснование (2 балла):</b>\n{example['part1']}\n\n"
    
    if isinstance(example.get('part2'), dict):
        text += f"<b>2. Ответ (1 балл):</b>\n{example['part2']['answer']}\n\n"
    elif 'part2' in example:
        text += f"<b>2. Ответ (1 балл):</b>\n{example['part2']}\n\n"
    
    if 'part3' in example:
        text += "<b>3. Примеры (3 балла):</b>\n"
        if isinstance(example['part3'], list):
            for i, ex in enumerate(example['part3'], 1):
                if isinstance(ex, dict):
                    text += f"{i}) <i>{ex.get('type', '')}:</i> {ex.get('example', '')}\n"
                else:
                    text += f"{i}) {ex}\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Попробовать эту тему", callback_data=f"t25_topic:{topic_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_examples")]
    ])
    
    await query.edit_message_text(
        text[:4000],  # Telegram limit
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
@validate_state_transition({states.ANSWERING})
async def example_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Примеры ответов в теории."""
    query = update.callback_query
    
    return await best_examples(update, context)


@safe_handler()
async def common_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Типичные ошибки."""
    query = update.callback_query
    
    text = (
        "⚠️ <b>Типичные ошибки в задании 25</b>\n\n"
        
        "❌ <b>Ошибки в обосновании (К1):</b>\n"
        "• Одно предложение вместо развёрнутого ответа\n"
        "• Отсутствие теоретической аргументации\n"
        "• Подмена обоснования примером\n"
        "• Нет причинно-следственных связей\n\n"
        
        "❌ <b>Ошибки в ответе (К2):</b>\n"
        "• Неполный или уклончивый ответ\n"
        "• Ответ не соответствует вопросу\n"
        "• Забыли ответить на эту часть\n\n"
        
        "❌ <b>Ошибки в примерах (К3):</b>\n"
        "• Абстрактные примеры без деталей\n"
        "• Повторение одного примера\n"
        "• Примеры не из жизни РФ (когда требуется)\n"
        "• Менее трёх примеров\n"
        "• Примеры не соответствуют заданию\n\n"
        
        "💡 <b>Как избежать:</b>\n"
        "• Внимательно читайте ВСЕ части задания\n"
        "• Структурируйте ответ по частям\n"
        "• Проверяйте соответствие критериям\n"
        "• Используйте черновик"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Примеры хороших ответов", callback_data="t25_example_answers")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def detailed_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная статистика."""
    query = update.callback_query
    
    # Здесь можно добавить более подробную статистику
    return states.CHOOSING_MODE


@safe_handler()
async def recommendations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рекомендации по улучшению."""
    query = update.callback_query
    
    stats = context.user_data.get('task25_stats', {})
    
    text = "🎯 <b>Персональные рекомендации</b>\n\n"
    
    # Анализируем статистику и даем советы
    if not stats.get('total_attempts'):
        text += "📝 Начните с изучения теории и примеров\n"
        text += "💡 Попробуйте режим ответов по частям\n"
        text += "🟢 Начните с тем легкого уровня\n"
    else:
        avg_score = sum(stats.get('scores', [0])) / max(len(stats.get('scores', [1])), 1)
        
        if avg_score < 3:
            text += "📚 Изучите типичные ошибки\n"
            text += "💡 Используйте режим по частям\n"
            text += "🔍 Анализируйте эталонные ответы\n"
        elif avg_score < 5:
            text += "✏️ Работайте над развёрнутостью примеров\n"
            text += "🎯 Тренируйтесь на сложных темах\n"
        else:
            text += "⭐ Отличные результаты!\n"
            text += "🔴 Попробуйте экспертный уровень проверки\n"
    
    # Рекомендуем непройденные блоки
    blocks_progress = stats.get('blocks_progress', {})
    weak_blocks = [b for b, p in blocks_progress.items() if p < 50]
    
    if weak_blocks:
        text += f"\n<b>Обратите внимание на блоки:</b>\n"
        for block in weak_blocks[:3]:
            text += f"• {block}\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 К статистике", callback_data="t25_progress")],
        [InlineKeyboardButton("💪 Начать практику", callback_data="t25_practice")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

# Остальные обработчики...
@safe_handler()
async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Банк примеров."""
    query = update.callback_query
    
    text = (
        "🏦 <b>Банк примеров</b>\n\n"
        "Здесь собраны эталонные примеры ответов.\n"
        "Выберите способ поиска:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Поиск по ключевым словам", callback_data="t25_search_examples")],
        [InlineKeyboardButton("📚 По блокам", callback_data="t25_examples_by_block")],
        [InlineKeyboardButton("⭐ Лучшие примеры", callback_data="t25_best_examples")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def show_example_topic(query, context: ContextTypes.DEFAULT_TYPE, topic_idx: int):
    """Показывает эталонный ответ для темы по индексу."""
    topics_with_examples = [t for t in task25_data.get('topics', []) 
                           if 'example_answers' in t]
    
    if topic_idx >= len(topics_with_examples) or topic_idx < 0:
        topic_idx = 0
    
    topic = topics_with_examples[topic_idx]
    total = len(topics_with_examples)
    
    # Форматируем текст
    text = f"📚 <b>Банк эталонных ответов</b>\n"
    text += f"Пример {topic_idx + 1} из {total}\n"
    text += "━" * 35 + "\n\n"
    
    text += f"<b>Тема:</b> {topic['title']}\n"
    text += f"<b>Блок:</b> {topic.get('block', 'Не указан')}\n\n"
    
    # Текст задания
    if 'task_text' in topic:
        text += f"<b>Задание:</b>\n{topic['task_text']}\n\n"
    elif 'parts' in topic:
        text += "<b>Задание:</b>\n"
        parts = topic['parts']
        if 'part1' in parts:
            text += f"1. {parts['part1']}\n"
        if 'part2' in parts:
            text += f"2. {parts['part2']}\n"
        if 'part3' in parts:
            text += f"3. {parts['part3']}\n"
        text += "\n"
    
    # Эталонный ответ
    text += _format_example_answer(topic)
    
    # Кнопки навигации
    kb_buttons = []
    
    # Навигация между примерами
    nav_row = []
    if topic_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"t25_example_nav:{topic_idx-1}"))
    nav_row.append(InlineKeyboardButton(f"{topic_idx+1}/{total}", callback_data="t25_noop"))
    if topic_idx < total - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"t25_example_nav:{topic_idx+1}"))
    
    kb_buttons.append(nav_row)
    
    # Действия
    kb_buttons.extend([
        [InlineKeyboardButton("📝 Попробовать эту тему", callback_data=f"t25_try_topic:{topic['id']}")],
        [InlineKeyboardButton("🔍 Поиск по темам", callback_data="t25_bank_search")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def handle_example_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по примерам ответов."""
    query = update.callback_query
    
    _, _, topic_idx = query.data.split(":")
    topic_idx = int(topic_idx)
    
    # Вызываем существующую функцию show_example_topic
    await show_example_topic(query, context, topic_idx)
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def bank_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по банку примеров."""
    query = update.callback_query
    
    topic_idx = int(query.data.split(":")[1])
    await show_example_topic(query, context, topic_idx)
    return states.CHOOSING_MODE


@safe_handler()
async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прогресса пользователя."""
    query = update.callback_query
    
    results = context.user_data.get('task25_results', [])
    
    if not results:
        text = MessageFormatter.format_welcome_message(
            "задание 25",
            is_new_user=True
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("💪 Начать практику", callback_data="t25_practice"),
            InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")
        ]])
    else:
        # Собираем статистику
        total_attempts = len(results)
        scores = [r['score'] for r in results]
        average_score = sum(scores) / len(scores)
        unique_topics = len(set(r['topic_id'] for r in results))
        
        # Топ результаты
        topic_scores = {}
        for result in results:
            topic_id = result['topic_id']
            if topic_id not in topic_scores or result['score'] > topic_scores[topic_id]:
                topic_scores[topic_id] = {
                    'topic': result.get('topic_title', 'Неизвестная тема'),
                    'score': result['score'],
                    'max_score': 6
                }
        
        top_results = sorted(topic_scores.values(), key=lambda x: x['score'], reverse=True)[:3]
        
        # Форматируем сообщение
        text = MessageFormatter.format_progress_message({
            'total_attempts': total_attempts,
            'average_score': average_score,
            'completed': unique_topics,
            'total': len(task25_data.get('topics', [])),
            'total_time': 0,
            'top_results': top_results,
            'current_average': average_score / 6 * 100,
            'previous_average': (average_score / 6 * 100) - 5
        }, "заданию 25")
        
        kb = AdaptiveKeyboards.create_progress_keyboard(
            has_detailed_stats=True,
            can_export=True,
            module_code="t25"
        )
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def settings_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки задания 25."""
    query = update.callback_query
    
    # Получаем текущие настройки - ИСПРАВЛЕНО
    settings = context.user_data.get('task25_settings', {
        'answer_mode': 'full',  # full или parts
        'show_examples': True,
        'strictness': 'standard'
    })
    
    # Убедимся, что settings это словарь
    if not isinstance(settings, dict):
        settings = {
            'answer_mode': 'full',
            'show_examples': True,
            'strictness': 'standard'
        }
        context.user_data['task25_settings'] = settings
    
    text = "⚙️ <b>Настройки задания 25</b>\n\n"
    
    # Режим ответа
    answer_mode_text = "целиком" if settings.get('answer_mode', 'full') == 'full' else "по частям"
    text += f"📝 Режим ответа: <b>{answer_mode_text}</b>\n"
    
    # Показ примеров
    examples_text = "да" if settings.get('show_examples', True) else "нет"
    text += f"📚 Показывать примеры: <b>{examples_text}</b>\n"
    
    # Строгость проверки
    strictness_map = {
        'lenient': 'мягкая',
        'standard': 'стандартная',
        'strict': 'строгая',
        'expert': 'экспертная'
    }
    text += f"🎯 Строгость проверки: <b>{strictness_map.get(settings.get('strictness', 'standard'), 'стандартная')}</b>\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{'✅' if settings.get('answer_mode', 'full') == 'full' else '⚪'} Отвечать целиком",
            callback_data="t25_set_mode:full"
        )],
        [InlineKeyboardButton(
            f"{'✅' if settings.get('answer_mode', 'full') == 'parts' else '⚪'} Отвечать по частям",
            callback_data="t25_set_mode:parts"
        )],
        [InlineKeyboardButton(
            f"{'✅' if settings.get('show_examples', True) else '❌'} Показ примеров",
            callback_data="t25_toggle_examples"
        )],
        [InlineKeyboardButton("🎯 Строгость проверки", callback_data="t25_strictness_menu")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


# Вспомогательные функции
async def cmd_task25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task25."""
    text = (
        "📝 <b>Задание 25</b>\n\n"
        "Развёрнутый ответ с обоснованием и примерами.\n"
        "Максимальный балл: 6\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t25_practice")],
        [InlineKeyboardButton("📚 Теория", callback_data="t25_theory")],
        [InlineKeyboardButton("🏦 Банк примеров", callback_data="t25_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t25_progress")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="t25_settings")],
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
        "❌ Действие отменено.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 К заданиям", callback_data="t25_menu")
        ]])
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 25."""
    query = update.callback_query
    
    results = context.user_data.get('task25_results', [])
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(set(r.get('topic_id') for r in results)) / 100 * 100) if results else 0
    }

    greeting = get_personalized_greeting(user_stats)
    text = greeting + MessageFormatter.format_welcome_message(
        "задание 25",
        is_new_user=user_stats['total_attempts'] == 0
    )
    
    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t25")
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE, states.CHOOSING_BLOCK, states.CHOOSING_TOPIC, states.ANSWERING, states.ANSWERING_PARTS})
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню."""
    query = update.callback_query
    
    kb = build_main_menu()
    
    await query.edit_message_text(
        "🎓 <b>Подготовка к ЕГЭ по обществознанию</b>\n\n"
        "Выберите раздел для тренировки:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return ConversationHandler.END


@safe_handler()
async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик для неактивных кнопок."""
    query = update.callback_query
    return states.CHOOSING_MODE

@safe_handler()
async def handle_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик для информационных кнопок."""
    query = update.callback_query
    return None

# Дополнительные обработчики...
async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка тем с пагинацией."""
    query = update.callback_query
    
    # Извлекаем номер страницы
    parts = query.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0
    
    # Получаем темы блока
    block_name = context.user_data.get("selected_block", "")
    topics = task25_data.get("topics_by_block", {}).get(block_name, [])
    
    if not topics:
        await query.edit_message_text(
            "❌ Темы не найдены",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data=f"t25_block:{block_name}")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Пагинация
    topics_per_page = 5
    total_pages = (len(topics) + topics_per_page - 1) // topics_per_page
    start_idx = page * topics_per_page
    end_idx = min(start_idx + topics_per_page, len(topics))
    
    text = f"📚 <b>Темы блока: {block_name}</b>\n"
    text += f"Страница {page + 1} из {total_pages}\n\n"
    
    kb_buttons = []
    
    # Добавляем темы текущей страницы
    for i in range(start_idx, end_idx):
        topic = topics[i]
        difficulty = topic.get('difficulty', 'medium')
        diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(difficulty, "⚪")
        
        kb_buttons.append([InlineKeyboardButton(
            f"{diff_emoji} {topic['title'][:40]}...",
            callback_data=f"t25_select_topic:{topic['id']}"
        )])
    
    # Навигация по страницам
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"t25_list_topics:page:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"t25_list_topics:page:{page+1}"))
    
    if nav_buttons:
        kb_buttons.append(nav_buttons)
    
    kb_buttons.append([InlineKeyboardButton("⬅️ К блоку", callback_data=f"t25_block:{block_name}")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_BLOCK_T25

@safe_handler()
async def show_topic_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ конкретной темы по ID."""
    query = update.callback_query
    
    # Парсим ID темы из callback_data
    topic_id = query.data.split(':', 1)[1]
    
    # Пытаемся преобразовать в число, если это число
    try:
        topic_id = int(topic_id)
    except ValueError:
        pass  # Оставляем как строку
    
    topic = task25_data.get("topic_by_id", {}).get(topic_id)
    
    if not topic:
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    # Проверяем режим ответа
    settings = context.user_data.get('task25_settings', {})
    
    if settings.get('answer_mode') == 'parts':
        # Начинаем с первой части
        context.user_data['current_part'] = 1
        context.user_data['part_answers'] = {}
        
        parts = topic.get('parts', {})
        part1_text = parts.get('part1', '')
        
        text = (
            f"📝 <b>Режим ответа по частям</b>\n\n"
            f"<b>Тема:</b> {topic['title']}\n"
            f"<b>Блок:</b> {topic.get('block', 'Общие темы')}\n"
            f"<b>Сложность:</b> { {'easy': '🟢 Легкая', 'medium': '🟡 Средняя', 'hard': '🔴 Сложная'}.get(topic.get('difficulty', 'medium'), '⚪') }\n\n"
            f"<b>Часть 1: Обоснование (2 балла)</b>\n\n"
            f"{part1_text}\n\n"
            f"💡 <i>Отправьте ваше обоснование</i>"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="t25_practice")]
        ])
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return ANSWERING_PARTS
    else:
        # Стандартный режим
        text = _build_topic_message(topic)
        
        # Определяем откуда вернуться
        selected_block = context.user_data.get('selected_block')
        if selected_block:
            back_callback = f"t25_block:{selected_block}"
            back_text = "⬅️ К блоку"
        else:
            back_callback = "t25_all_topics_list"
            back_text = "⬅️ К списку"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Другая тема", callback_data="t25_another_topic")],
            [InlineKeyboardButton(back_text, callback_data=back_callback)]
        ])
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return states.ANSWERING

@safe_handler()
async def show_topic_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка тем с пагинацией."""
    query = update.callback_query
    
    # Парсим callback_data: t25_list_topics:page:0
    parts = query.data.split(':')
    page = int(parts[2]) if len(parts) > 2 else 0
    
    block_name = context.user_data.get("selected_block")
    topics = task25_data.get("topics_by_block", {}).get(block_name, [])
    
    # Пагинация - 10 тем на страницу
    items_per_page = 10
    total_pages = (len(topics) + items_per_page - 1) // items_per_page
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, len(topics))
    
    # Формируем текст
    text = f"📚 <b>{block_name}</b>\n"
    text += f"Страница {page + 1} из {total_pages}\n\n"
    
    # Получаем прогресс пользователя
    user_stats = context.user_data.get('task25_stats', {})
    completed_topics = user_stats.get('topics_completed', set())
    
    # Список тем на текущей странице
    buttons = []
    for i in range(start_idx, end_idx):
        topic = topics[i]
        topic_id = topic.get('id')
        
        # Определяем эмодзи статуса
        if topic_id in completed_topics:
            status = "✅"
        else:
            status = "📝"
        
        # Сокращаем название если слишком длинное
        title = topic.get('title', 'Без названия')
        if len(title) > 40:
            title = title[:37] + "..."
        
        button_text = f"{status} {title}"
        buttons.append([InlineKeyboardButton(
            button_text,
            callback_data=f"t25_topic:{topic_id}"
        )])
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"t25_list_topics:page:{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"t25_list_topics:page:{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("⬅️ К блокам", callback_data="t25_select_block")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def random_topic_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайная тема из выбранного блока с правильными кнопками."""
    query = update.callback_query
    
    block_name = context.user_data.get("selected_block")
    if not block_name:
        return states.CHOOSING_MODE
    
    topics = task25_data.get("topics_by_block", {}).get(block_name, [])
    
    if not topics:
        return states.CHOOSING_MODE
    
    # Приоритет непройденным темам
    user_stats = context.user_data.get('task25_stats', {})
    completed = set(user_stats.get('topics_completed', []))
    
    uncompleted = [t for t in topics if t.get('id') not in completed]
    topic_pool = uncompleted if uncompleted else topics
    
    topic = random.choice(topic_pool)
    context.user_data['current_topic'] = topic
    
    # Проверяем режим ответа
    settings = context.user_data.get('task25_settings', {})
    
    text = _build_topic_message(topic)
    
    if settings.get('answer_mode') == 'parts':
        # Начинаем режим по частям
        context.user_data['current_part'] = 1
        context.user_data['part_answers'] = {}
        
        parts = topic.get('parts', {})
        part1_text = parts.get('part1', '')
        
        text = (
            f"📝 <b>Режим ответа по частям</b>\n\n"
            f"<b>Тема:</b> {topic['title']}\n\n"
            f"<b>Часть 1: Обоснование (2 балла)</b>\n\n"
            f"{part1_text}\n\n"
            f"💡 <i>Отправьте ваше обоснование</i>"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data=f"t25_block:{block_name}")]
        ])
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return ANSWERING_PARTS
    else:
        # Стандартный режим
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Другая тема", callback_data="t25_random_block")],
            [InlineKeyboardButton("⬅️ К блоку", callback_data=f"t25_block:{block_name}")]
        ])
        
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        return states.ANSWERING


@safe_handler()
async def bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск в банке ответов."""
    query = update.callback_query
    
    text = (
        "🔍 <b>Поиск в банке ответов</b>\n\n"
        "Отправьте ключевые слова для поиска.\n"
        "Например: <i>демократия</i>, <i>рыночная экономика</i>\n\n"
        "Или выберите действие:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Все примеры", callback_data="t25_all_examples")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.SEARCHING

@safe_handler()
async def list_all_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка всех тем без разделения по блокам."""
    query = update.callback_query
    
    # Собираем все темы
    all_topics = task25_data.get('topics', [])
    
    if not all_topics:
        return states.CHOOSING_MODE
    
    # Сортируем по сложности для удобства
    topics_by_difficulty = {
        'easy': [],
        'medium': [],
        'hard': []
    }
    
    for topic in all_topics:
        difficulty = topic.get('difficulty', 'medium')
        topics_by_difficulty[difficulty].append(topic)
    
    # Формируем текст
    text = "📚 <b>Все темы задания 25</b>\n\n"
    
    # Статистика
    user_stats = context.user_data.get('task25_stats', {})
    completed_topics = set(user_stats.get('topics_completed', []))
    
    text += f"✅ Изучено: {len(completed_topics)}/{len(all_topics)}\n\n"
    
    # Группируем по сложности
    difficulty_names = {
        'easy': '🟢 Легкие темы',
        'medium': '🟡 Средние темы',
        'hard': '🔴 Сложные темы'
    }
    
    buttons = []
    
    for difficulty in ['easy', 'medium', 'hard']:
        topics = topics_by_difficulty[difficulty]
        if topics:
            completed_in_level = len([t for t in topics if t.get('id') in completed_topics])
            buttons.append([InlineKeyboardButton(
                f"{difficulty_names[difficulty]} ({completed_in_level}/{len(topics)})",
                callback_data=f"t25_list_by_diff:{difficulty}"
            )])
    
    buttons.append([InlineKeyboardButton("🎲 Случайная тема", callback_data="t25_random_all")])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_practice")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def handle_settings_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка изменения настроек."""
    query = update.callback_query
    
    # Парсим режим из callback_data: t25_set_mode:full
    mode = query.data.split(':')[1]
    
    # Получаем текущие настройки
    settings = context.user_data.get('task25_settings', {})
    
    # Убедимся, что это словарь
    if not isinstance(settings, dict):
        settings = {}
    
    # Обновляем настройки
    settings['answer_mode'] = mode
    context.user_data['task25_settings'] = settings
    
    # Обновляем отображение
    return await settings_mode(update, context)


@safe_handler()
async def toggle_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключение показа примеров."""
    query = update.callback_query
    
    settings = context.user_data.get('task25_settings', {})
    settings['show_examples'] = not settings.get('show_examples', True)
    context.user_data['task25_settings'] = settings
    
    return await settings_mode(update, context)


@safe_handler()
async def strictness_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбора строгости проверки."""
    query = update.callback_query
    
    current_strictness = context.user_data.get('task25_settings', {}).get('strictness', 'standard')
    
    text = (
        "🎯 <b>Выберите уровень строгости проверки:</b>\n\n"
        "🟢 <b>Мягкая</b> - засчитываются частично правильные ответы\n"
        "🟡 <b>Стандартная</b> - обычные критерии ЕГЭ\n"
        "🔴 <b>Строгая</b> - требуется полное соответствие критериям\n"
        "⚫ <b>Экспертная</b> - максимальная строгость\n"
    )
    
    buttons = []
    strictness_levels = [
        ('lenient', '🟢 Мягкая'),
        ('standard', '🟡 Стандартная'),
        ('strict', '🔴 Строгая'),
        ('expert', '⚫ Экспертная')
    ]
    
    for level, name in strictness_levels:
        check = '✅ ' if level == current_strictness else ''
        buttons.append([InlineKeyboardButton(
            f"{check}{name}",
            callback_data=f"t25_strictness:{level}"
        )])
    
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_settings")])
    
    kb = InlineKeyboardMarkup(buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def handle_bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поиска в банке примеров."""
    search_query = update.message.text.lower()
    
    # Ищем подходящие темы
    found_topics = []
    for topic in task25_data.get('topics', []):
        if (search_query in topic.get('title', '').lower() or
            search_query in topic.get('task_text', '').lower() or
            any(search_query in str(part).lower() for part in topic.get('parts', {}).values())):
            found_topics.append(topic)
    
    if not found_topics:
        text = "🔍 <b>Результаты поиска</b>\n\n"
        text += f"По запросу «{update.message.text}» ничего не найдено.\n"
        text += "Попробуйте другие ключевые слова."
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Новый поиск", callback_data="t25_search_examples")],
            [InlineKeyboardButton("⬅️ К банку примеров", callback_data="t25_examples")]
        ])
    else:
        text = f"🔍 <b>Найдено тем: {len(found_topics)}</b>\n\n"
        
        # Показываем первые 5 результатов
        buttons = []
        for i, topic in enumerate(found_topics[:5]):
            text += f"{i+1}. {topic['title']}\n"
            buttons.append([InlineKeyboardButton(
                f"👁 {topic['title'][:40]}...",
                callback_data=f"t25_show_example:{topic['id']}"
            )])
        
        if len(found_topics) > 5:
            text += f"\n<i>...и ещё {len(found_topics) - 5} тем</i>"
        
        buttons.append([InlineKeyboardButton("🔍 Новый поиск", callback_data="t25_search_examples")])
        buttons.append([InlineKeyboardButton("⬅️ К банку примеров", callback_data="t25_examples")])
        
        kb = InlineKeyboardMarkup(buttons)
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def handle_settings_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий в настройках."""
    # Реализация...
    pass


@safe_handler()
async def set_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка уровня строгости."""
    query = update.callback_query
    
    level = query.data.split(':')[1]
    
    settings = context.user_data.get('task25_settings', {})
    settings['strictness'] = level
    context.user_data['task25_settings'] = settings
    
    return await settings_mode(update, context)


@safe_handler()
async def show_block_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика по блокам тем."""
    query = update.callback_query
    
    stats = context.user_data.get('practice_stats', {})
    
    if not stats:
        text = "📊 <b>Статистика по блокам</b>\n\n"
        text += "Вы ещё не решали задания.\n"
        text += "Начните практику для сбора статистики!"
    else:
        # Собираем статистику по блокам
        block_data = {}
        
        for topic_id, topic_stats in stats.items():
            topic = task25_data.get('topic_by_id', {}).get(int(topic_id))
            if topic:
                block = topic.get('block', 'Другое')
                if block not in block_data:
                    block_data[block] = {
                        'topics_tried': 0,
                        'total_attempts': 0,
                        'scores': []
                    }
                
                block_data[block]['topics_tried'] += 1
                block_data[block]['total_attempts'] += topic_stats.get('attempts', 0)
                block_data[block]['scores'].extend(topic_stats.get('scores', []))
        
        text = "📊 <b>Статистика по блокам</b>\n\n"
        
        for block, data in sorted(block_data.items()):
            total_topics = len(task25_data.get('topics_by_block', {}).get(block, []))
            coverage = (data['topics_tried'] / total_topics * 100) if total_topics > 0 else 0
            
            text += f"<b>{block}</b>\n"
            text += f"• Изучено тем: {data['topics_tried']}/{total_topics} ({coverage:.0f}%)\n"
            text += f"• Всего попыток: {data['total_attempts']}\n"
            
            if data['scores']:
                avg_score = sum(data['scores']) / len(data['scores'])
                max_score = max(data['scores'])
                text += f"• Средний балл: {avg_score:.1f}/6\n"
                text += f"• Лучший результат: {max_score}/6\n"
            
            text += "\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Общий прогресс", callback_data="t25_progress")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def detailed_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальный прогресс по темам."""
    query = update.callback_query
    
    stats = context.user_data.get('practice_stats', {})
    
    if not stats:
        
        return states.CHOOSING_MODE
    
    # Сортируем темы по последней попытке
    sorted_topics = sorted(
        stats.items(),
        key=lambda x: x[1].get('attempts', 0),
        reverse=True
    )
    
    text = "📈 <b>Детальный прогресс</b>\n\n"
    
    for topic_id, topic_stats in sorted_topics[:10]:  # Показываем топ-10
        topic = task25_data.get('topic_by_id', {}).get(int(topic_id))
        if topic:
            topic_name = topic.get('title', 'Неизвестная тема')[:40]
            attempts = topic_stats.get('attempts', 0)
            scores = topic_stats.get('scores', [])
            
            text += f"<b>{topic_name}</b>\n"
            text += f"• Попыток: {attempts}\n"
            
            if scores:
                avg_score = sum(scores) / len(scores)
                last_score = scores[-1]
                best_score = max(scores)
                
                text += f"• Последний результат: {last_score}/6\n"
                text += f"• Лучший результат: {best_score}/6\n"
                text += f"• Средний балл: {avg_score:.1f}/6\n"
                
                # Тренд
                if len(scores) > 1:
                    if scores[-1] > scores[-2]:
                        text += "• Тренд: 📈 Улучшение\n"
                    elif scores[-1] < scores[-2]:
                        text += "• Тренд: 📉 Снижение\n"
                    else:
                        text += "• Тренд: ➡️ Стабильно\n"
            
            text += "\n"
    
    if len(sorted_topics) > 10:
        text += f"<i>Показаны 10 из {len(sorted_topics)} изученных тем</i>"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 По блокам", callback_data="t25_block_stats")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t25_progress")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def _save_user_stats(context: ContextTypes.DEFAULT_TYPE, topic: Dict, score: int):
    """Сохраняет статистику пользователя."""
    stats = context.user_data.get('task25_stats', {
        'total_attempts': 0,
        'topics_completed': [],  # Используем list вместо set
        'scores': [],
        'blocks_progress': {}
    })
    
    # Обновляем статистику
    stats['total_attempts'] += 1
    
    # Добавляем тему если её ещё нет
    topic_id = topic.get('id')
    if topic_id and topic_id not in stats['topics_completed']:
        stats['topics_completed'].append(topic_id)
    
    stats['scores'].append(score)
    
    # Обновляем прогресс по блокам
    block_name = topic.get('block', 'Общие темы')
    if block_name not in stats['blocks_progress']:
        stats['blocks_progress'][block_name] = 0
    
    # Подсчитываем прогресс
    block_topics = task25_data.get('topics_by_block', {}).get(block_name, [])
    if block_topics:
        completed_in_block = len([
            t for t in block_topics 
            if t.get('id') in stats['topics_completed']
        ])
        stats['blocks_progress'][block_name] = (completed_in_block / len(block_topics)) * 100
    
    context.user_data['task25_stats'] = stats

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
    """Форматирует эталонный ответ."""
    example = topic.get('example_answers', {})
    if not example:
        return ""
    
    text = "\n\n📚 <b>Эталонный ответ:</b>\n\n"
    
    if 'part1' in example:
        text += f"<b>1. Обоснование:</b>\n{example['part1']}\n\n"
    
    if 'part2' in example:
        text += f"<b>2. Ответ:</b>\n{example['part2']}\n\n"
    
    if 'part3' in example:
        text += "<b>3. Примеры:</b>\n"
        if isinstance(example['part3'], list):
            for i, ex in enumerate(example['part3'], 1):
                if isinstance(ex, dict):
                    text += f"\n{i}) <i>{ex.get('type', 'Пример')}:</i>\n"
                    text += f"{ex.get('example', ex)}\n"
                else:
                    text += f"{i}) {ex}\n"
        else:
            text += f"{example['part3']}\n"
    
    return text

@safe_handler()
async def handle_strictness_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик изменения уровня строгости."""
    query = update.callback_query
    
    # Парсим уровень из callback_data
    _, level_str = query.data.split(':')
    
    global evaluator
    
    try:
        # Определяем новый уровень
        new_level = StrictnessLevel[level_str.upper()]
        
        # Пересоздаём evaluator с новым уровнем
        if AI_EVALUATOR_AVAILABLE:
            evaluator = Task25AIEvaluator(strictness=new_level)
            
            logger.info(f"Changed strictness level to {new_level.value}")
            
    except Exception as e:
        logger.error(f"Error changing strictness: {e}")
    # Возвращаемся в меню настроек
    return await show_settings(update, context)


@safe_handler()
async def handle_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает прогресс пользователя."""
    query = update.callback_query
    
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


@safe_handler()
async def handle_reset_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс прогресса пользователя."""
    query = update.callback_query
    
    text = (
        "⚠️ <b>Сброс прогресса</b>\n\n"
        "Вы уверены, что хотите сбросить весь прогресс по заданию 25?\n"
        "Это действие нельзя отменить!"
    )
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, сбросить", callback_data="t25_confirm_reset"),
            InlineKeyboardButton("❌ Отмена", callback_data="t25_settings")
        ]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def choose_practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор режима практики."""
    query = update.callback_query
    
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


@safe_handler()
async def handle_random_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор случайной темы."""
    query = update.callback_query
    
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


@safe_handler()
async def choose_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока для практики."""
    query = update.callback_query
    
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


@safe_handler()
async def handle_by_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор темы по сложности."""
    query = update.callback_query
    
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


@safe_handler()
async def handle_difficulty_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбранной сложности."""
    query = update.callback_query
    
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


@safe_handler()
async def handle_recommended(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор рекомендованной темы."""
    query = update.callback_query
    
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

@safe_handler()
async def handle_topic_by_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора темы из блока."""
    query = update.callback_query
    
    block_name = query.data.split(":", 1)[1]
    context.user_data["selected_block"] = block_name
    
    topics = task25_data.get("topics_by_block", {}).get(block_name, [])
    
    text = f"📚 <b>Блок: {block_name}</b>\n"
    text += f"Доступно тем: {len(topics)}\n\n"
    text += "Выберите действие:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Список тем", callback_data=f"t25_list_topics:page:0")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t25_random_block")],
        [InlineKeyboardButton("⬅️ К блокам", callback_data="t25_by_block")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_BLOCK_T25


@safe_handler()
async def handle_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повторить то же задание."""
    query = update.callback_query
    
    topic = context.user_data.get('current_topic')
    if not topic:
        return await choose_practice_mode(update, context)
    
    # Показываем то же задание
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Попробуйте ещё раз:</b>\n\n"
        "<i>💡 Подсказка: обратите внимание на все три части задания</i>",
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_ANSWER

@safe_handler()
async def handle_new_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Новая случайная тема."""
    query = update.callback_query
    
    # Выбираем новую тему
    if topic_selector:
        user_id = update.effective_user.id
        topic = topic_selector.get_random_topic(user_id)
    else:
        topics = task25_data.get('topics', [])
        topic = random.choice(topics) if topics else None
    
    if not topic:
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    # Показываем новое задание
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>",
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_ANSWER


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню настроек."""
    query = update.callback_query
    
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
    

@safe_handler()
async def confirm_reset_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение сброса прогресса."""
    query = update.callback_query
    
    # Сбрасываем статистику
    context.user_data['practice_stats'] = {}
    
    
    # Возвращаемся в настройки
    return await show_settings(update, context)


@safe_handler()
@validate_state_transition({states.ANSWERING})
async def show_example_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает эталонный ответ для выбранной темы."""
    query = update.callback_query
    
    # Извлекаем ID темы
    _, topic_id = query.data.split(':')
    topic = task25_data.get('topic_by_id', {}).get(int(topic_id))
    
    if not topic:
        return states.CHOOSING_MODE
    
    # Форматируем эталонный ответ
    text = f"📚 <b>Эталонный ответ</b>\n\n"
    text += f"<b>Тема:</b> {topic['title']}\n"
    text += f"{'─' * 30}\n\n"
    
    if 'example_answers' in topic:
        example = topic['example_answers']
        
        # Часть 1 - Обоснование
        if 'part1' in example:
            text += "<b>1. Обоснование:</b>\n"
            text += f"{example['part1']}\n\n"
        
        # Часть 2 - Ответ
        if 'part2' in example:
            text += "<b>2. Ответ на вопрос:</b>\n"
            text += f"{example['part2']}\n\n"
        
        # Часть 3 - Примеры
        if 'part3' in example:
            text += "<b>3. Примеры:</b>\n"
            for i, ex in enumerate(example['part3'], 1):
                text += f"\n{i}) <i>{ex.get('type', 'Пример')}:</i>\n"
                text += f"{ex['example']}\n"
    else:
        text += "<i>Эталонный ответ для этой темы пока не добавлен</i>"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Попробовать тему", callback_data=f"t25_try_topic:{topic_id}")],
        [InlineKeyboardButton("🔍 К поиску", callback_data="t25_bank_search")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="t25_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def handle_select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы из списка."""
    query = update.callback_query
    
    # Извлекаем ID темы
    _, topic_id = query.data.split(':')
    topic = task25_data.get('topic_by_id', {}).get(int(topic_id))
    
    if not topic:
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    # Показываем задание
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>",
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_ANSWER


@safe_handler()
async def handle_try_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Попробовать решить выбранную тему после просмотра примера."""
    query = update.callback_query
    
    # Извлекаем ID темы
    _, topic_id = query.data.split(':')
    topic = task25_data.get('topic_by_id', {}).get(int(topic_id))
    
    if not topic:
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    # Показываем задание
    from .utils import format_topic_for_display
    topic_text = format_topic_for_display(topic)
    
    await query.edit_message_text(
        f"{topic_text}\n\n"
        "📝 <b>Напишите развёрнутый ответ:</b>\n\n"
        "<i>💡 Подсказка: вы только что просмотрели эталонный ответ для этой темы</i>",
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_ANSWER

@safe_handler()
@validate_state_transition({states.ANSWERING})
async def handle_answer_document_task25(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка развернутого ответа из документа для task25."""
    
    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text("❌ Ошибка: тема не выбрана.")
        return states.CHOOSING_MODE
    
    extracted_text = await DocumentHandlerMixin.handle_document_answer(
        update, 
        context,
        task_name="развернутый ответ"
    )
    
    if not extracted_text:
        return states.ANSWERING
    
    # Для task25 может быть разбивка на части
    current_part = context.user_data.get('current_part', 0)
    
    if current_part > 0:
        # Если отвечаем по частям
        update.message.text = extracted_text
        return await handle_answer_parts(update, context)
    else:
        # Если полный ответ
        update.message.text = extracted_text
        return await handle_answer(update, context)

@safe_handler()
async def handle_all_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все доступные примеры."""
    query = update.callback_query
    
    # Фильтруем темы с примерами
    topics_with_examples = [t for t in task25_data.get('topics', []) 
                           if 'example_answers' in t]
    
    if not topics_with_examples:
        await query.edit_message_text(
            "❌ Примеры ответов пока не добавлены",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t25_bank_search")
            ]])
        )
        return states.CHOOSING_MODE
    
    text = f"📚 <b>Банк эталонных ответов</b>\n"
    text += f"Доступно примеров: {len(topics_with_examples)}\n\n"
    
    # Группируем по блокам
    by_block = {}
    for topic in topics_with_examples:
        block = topic.get('block', 'Другое')
        if block not in by_block:
            by_block[block] = []
        by_block[block].append(topic)
    
    kb_buttons = []
    for block, topics in sorted(by_block.items()):
        kb_buttons.append([InlineKeyboardButton(
            f"{block} ({len(topics)} тем)",
            callback_data=f"t25_examples_block:{block}"
        )])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t25_bank_search")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def show_theory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ теории по заданию 25."""
    query = update.callback_query
    
    text = """📚 <b>Теория по заданию 25</b>

<b>Структура развернутого ответа:</b>

1️⃣ <b>Обоснование (К1 - 2 балла)</b>
• Теоретическое обоснование тезиса
• Опора на обществоведческие понятия
• Логическая связь с вопросом

2️⃣ <b>Ответ на вопрос (К2 - 1 балл)</b>
• Четкий и однозначный ответ
• Соответствие заданному вопросу

3️⃣ <b>Примеры (К3 - 3 балла)</b>
• Три развернутых примера
• Из разных сфер общественной жизни
• Конкретные, с деталями

<b>Типичные ошибки:</b>
❌ Отсутствие теоретического обоснования
❌ Примеры из одной сферы
❌ Абстрактные примеры без конкретики
❌ Несоответствие примеров тезису"""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎯 Попробовать", callback_data="t25_practice"),
        InlineKeyboardButton("⬅️ Назад", callback_data="t25_menu")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE