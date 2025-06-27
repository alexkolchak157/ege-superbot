"""Обработчики для задания 19."""
import asyncio
import logging
import os
import json
import random
from typing import Optional, Dict, List
from core.document_processor import DocumentHandlerMixin
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
from core.admin_tools import admin_manager
from core import states
from core.states import TASK19_WAITING
from core.ai_evaluator import Task19Evaluator, EvaluationResult
from datetime import datetime
import io
from .evaluator import StrictnessLevel, Task19AIEvaluator
from core.universal_ui import UniversalUIComponents, AdaptiveKeyboards, MessageFormatter
from core.ui_helpers import (
    show_thinking_animation,
    show_extended_thinking_animation,  # Добавить этот импорт
    show_streak_notification,
    get_personalized_greeting,
    get_motivational_message,
    create_visual_progress,
)
from core.error_handler import safe_handler, auto_answer_callback
from core.plugin_loader import build_main_menu
from core.state_validator import validate_state_transition, state_validator

TASK19_STRICTNESS = os.getenv('TASK19_STRICTNESS', 'STRICT').upper()

# Глобальный evaluator с настройками
evaluator = None

logger = logging.getLogger(__name__)

# Глобальное хранилище для данных задания 19
task19_data = {}

# Инициализируем evaluator если еще не создан
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

def set_active_module(context: ContextTypes.DEFAULT_TYPE):
    """Устанавливает task19 как активный модуль."""
    context.user_data['active_module'] = 'task19'
    context.user_data['current_module'] = 'task19'
    
# Меню выбора уровня строгости (только для админов)
@safe_handler()
async def strictness_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню выбора уровня строгости проверки."""
    query = update.callback_query

    # Проверка прав (добавьте свою логику проверки админов)
    if not admin_manager.is_admin(query.from_user.id):
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

        # Поддержка двух форматов данных: список тем или словарь блоков
        if isinstance(raw, list):
            topics_list = raw
        else:
            topics_list = []
            for block_name, block in raw.get("blocks", {}).items():
                for topic in block.get("topics", []):
                    topic["block"] = block_name
                    topics_list.append(topic)

        all_topics = []
        topic_by_id = {}
        topics_by_block = {}

        for topic in topics_list:
            block_name = topic.get("block", "Без категории")
            all_topics.append(topic)
            topic_by_id[topic["id"]] = topic
            topics_by_block.setdefault(block_name, []).append(topic)

        task19_data = {
            "topics": all_topics,
            "topic_by_id": topic_by_id,
            "topics_by_block": topics_by_block,
            "blocks": {b: {"topics": t} for b, t in topics_by_block.items()},
        }

        _topics_cache = raw
        _topics_cache_time = datetime.now()
        
        logger.info(f"Loaded {len(all_topics)} topics for task19")
    except Exception as e:
        logger.error(f"Failed to load task19 data: {e}")
        task19_data = {"topics": [], "blocks": {}, "topics_by_block": {}}


@safe_handler()
@validate_state_transition({ConversationHandler.END, None})
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в задание 19 из главного меню."""
    query = update.callback_query
    
    # Устанавливаем активный модуль
    set_active_module(context)
    
    # Отвечаем на callback, чтобы убрать "часики"
    await query.answer()
    
    # Устанавливаем активный модуль
    context.user_data['current_module'] = 'task19'
    context.user_data['active_module'] = 'task19'
    
    # Отвечаем на callback, чтобы убрать "часики"
    await query.answer()
    
    # Получаем статистику пользователя
    results = context.user_data.get('task19_results', [])
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(set(r['topic'] for r in results)) / 50 * 100) if results else 0
    }
    
    # Формируем приветствие
    greeting = get_personalized_greeting(user_stats)
    text = greeting + MessageFormatter.format_welcome_message(
        "задание 19",
        is_new_user=user_stats['total_attempts'] == 0
    )
    
    # Создаем адаптивную клавиатуру
    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t19")
    
    # Показываем меню
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    # Возвращаем состояние CHOOSING_MODE для работы с меню
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


async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики."""
    query = update.callback_query
    
    # Устанавливаем активный модуль
    set_active_module(context)
    context.user_data['current_module'] = 'task19'
    context.user_data['active_module'] = 'task19'
    results = context.user_data.get('task19_results', [])
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': 0,
        'weak_topics_count': 0,
        'progress_percent': int(len(set(r['topic'] for r in results)) / 50 * 100) if results else 0
    }
    
    greeting = get_personalized_greeting(user_stats)
    text = greeting + MessageFormatter.format_welcome_message(
        "задание 19",
        is_new_user=user_stats['total_attempts'] == 0
    )
    
    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t19")
    
    await update.message.reply_text(
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
    
    # ВАЖНО: Устанавливаем текущий модуль
    context.user_data['current_module'] = 'task19'
    
    # Удаляем сообщение о проверке, если оно есть
    if 'checking_message_id' in context.user_data:
        try:
            await context.bot.delete_message(
                chat_id=query.message.chat_id,
                message_id=context.user_data['checking_message_id']
            )
            del context.user_data['checking_message_id']
        except:
            pass
    
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


@safe_handler()
@validate_state_transition({states.CHOOSING_BLOCK})
async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока тем."""
    query = update.callback_query

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


@safe_handler()
async def block_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню внутри выбранного блока."""
    query = update.callback_query

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


@safe_handler()
async def random_topic_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайная тема из всех блоков."""
    query = update.callback_query

    topics: List[Dict] = task19_data.get("topics", [])
    if not topics:
        return states.CHOOSING_MODE

    topic = random.choice(topics)

    text = _build_topic_message(topic)
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Другая тема", callback_data="t19_practice")]]
    )
    context.user_data["current_topic"] = topic
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    
    # ВАЖНО: Устанавливаем состояние явно
    from core.state_validator import state_validator
    state_validator.set_state(query.from_user.id, TASK19_WAITING)
    
    return TASK19_WAITING


@safe_handler()
async def random_topic_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Случайная тема из выбранного блока."""
    query = update.callback_query

    block_name = context.user_data.get("selected_block")
    if not block_name:
        return states.CHOOSING_MODE

    topics = [t for t in task19_data.get("topics", []) if t.get("block") == block_name]
    if not topics:
        return states.CHOOSING_BLOCK

    topic = random.choice(topics)
    text = _build_topic_message(topic)
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Другая тема", callback_data=f"t19_block:{block_name}")]]
    )
    context.user_data["current_topic"] = topic
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    # ВАЖНО: Устанавливаем состояние явно
    from core.state_validator import state_validator
    state_validator.set_state(query.from_user.id, TASK19_WAITING)

    return TASK19_WAITING

@safe_handler()
async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список тем (с пагинацией)."""
    query = update.callback_query

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
    nav.append(
        InlineKeyboardButton(
            create_visual_progress(page + 1, total_pages), callback_data="noop"
        )
    )
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


@safe_handler()
async def select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора конкретной темы."""
    query = update.callback_query
    
    # Устанавливаем активный модуль
    set_active_module(context)
    
    # Извлекаем topic_id из callback_data
    topic_id = int(query.data.split(':')[1])
    topic = next((t for t in task19_data['topics'] if t['id'] == topic_id), None)
    
    if not topic:
        await query.edit_message_text("❌ Тема не найдена")
        return states.CHOOSING_MODE
    
    # Сохраняем текущую тему
    context.user_data['current_topic'] = topic
    context.user_data['current_module'] = 'task19'
    context.user_data['active_module'] = 'task19'
    text = _build_topic_message(topic)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Выбрать другую тему", callback_data="t19_practice")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    # ВАЖНО: Устанавливаем состояние явно
    from core.state_validator import state_validator
    state_validator.set_state(query.from_user.id, TASK19_WAITING)
    
    return TASK19_WAITING

@safe_handler()
async def show_progress_enhanced(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прогресса с улучшенным UI."""
    query = update.callback_query
    
    results = context.user_data.get('task19_results', [])
    
    if not results:
        text = MessageFormatter.format_welcome_message(
            "задание 19", 
            is_new_user=True
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("💪 Начать практику", callback_data="t19_practice"),
            InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
        ]])
    else:
        # Собираем статистику
        total_attempts = len(results)
        total_score = sum(r['score'] for r in results)
        max_possible = sum(r['max_score'] for r in results)
        avg_score = total_score / total_attempts
        
        # Анализ по темам
        topic_stats = {}
        for result in results:
            topic = result['topic']
            if topic not in topic_stats:
                topic_stats[topic] = []
            topic_stats[topic].append(result['score'])
        
        # Топ темы
        top_results = []
        for topic, scores in topic_stats.items():
            avg = sum(scores) / len(scores)
            top_results.append({
                'topic': topic,
                'score': avg,
                'max_score': 3
            })
        top_results.sort(key=lambda x: x['score'], reverse=True)
        
        # Форматируем сообщение
        text = MessageFormatter.format_progress_message({
            'total_attempts': total_attempts,
            'average_score': avg_score,
            'completed': len(topic_stats),
            'total': 50,  # Предполагаем 50 тем
            'total_time': 0,  # Добавить подсчет времени
            'top_results': top_results[:3]
        }, "заданию 19")
        
        # Клавиатура прогресса
        kb = AdaptiveKeyboards.create_progress_keyboard(
            has_detailed_stats=True,
            can_export=True,
            module_code="t19"
        )
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({TASK19_WAITING})
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа пользователя на задание 19."""
    logger.info(f"task19.handle_answer called for user {update.effective_user.id}")
    
    # Проверяем, что мы в правильном модуле
    if context.user_data.get('active_module') != 'task19':
        logger.debug("Ignoring answer - not in task19 module")
        return states.CHOOSING_MODE
    
    # Предотвращаем повторную обработку
    if context.user_data.get('processing_answer', False):
        logger.debug("Already processing answer, ignoring")
        return states.CHOOSING_MODE
    
    context.user_data['processing_answer'] = True
    
    try:
        user_answer = update.message.text
        topic = context.user_data.get('current_topic')
        
        if not topic:
            await update.message.reply_text(
                "❌ Ошибка: тема не выбрана. Начните заново.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📝 К заданиям", callback_data="t19_practice")
                ]])
            )
            return states.CHOOSING_MODE
        
        # Показываем анимацию проверки
        checking_msg = await show_extended_thinking_animation(
            update.message,
            "Проверяю ваш ответ на задание 19",
            duration=30
        )
        
        try:
            # Используем локальный evaluator
            if evaluator and hasattr(evaluator, 'evaluate'):
                # Вызываем evaluate с правильными параметрами для task19
                result = await evaluator.evaluate(
                    answer=user_answer,
                    topic=topic.get('title', ''),
                    task_text=topic.get('task_text', topic.get('title', '')),
                    topic_data=topic
                )
                
                # Форматируем результат
                if hasattr(result, 'format_feedback'):
                    feedback = result.format_feedback()
                else:
                    feedback = str(result)
                
                score = getattr(result, 'total_score', 0)
                max_score = getattr(result, 'max_score', 3)
                
            else:
                # Fallback оценка
                score, feedback = await _basic_evaluation(user_answer, topic)
                max_score = 3
            
            # Удаляем анимацию
            await checking_msg.delete()
            
            # Сохраняем результат
            context.user_data.setdefault('task19_results', []).append({
                'topic': topic['title'],
                'score': score,
                'max_score': max_score,
                'timestamp': datetime.now().isoformat()
            })
            
            # Показываем результат
            await update.message.reply_text(
                feedback,
                reply_markup=AdaptiveKeyboards.create_result_keyboard(
                    score=score,
                    max_score=max_score,
                    module_code="t19"
                ),
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"Answer evaluated: {score}/{max_score}")
            
        except Exception as e:
            logger.error(f"Error evaluating answer: {e}")
            await checking_msg.delete()
            
            await update.message.reply_text(
                "❌ Произошла ошибка при проверке. Попробуйте еще раз.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Попробовать снова", callback_data="t19_practice"),
                    InlineKeyboardButton("📝 В меню", callback_data="t19_menu")
                ]])
            )
            
    finally:
        context.user_data['processing_answer'] = False
    
    return states.CHOOSING_MODE

async def _basic_evaluation(answer: str, topic: Dict) -> tuple[int, str]:
    """Базовая оценка без AI."""
    examples = answer.split('\n')
    valid_examples = 0
    
    for example in examples[:3]:  # Максимум 3 примера
        if len(example.strip()) > 20:  # Минимальная длина
            valid_examples += 1
    
    score = valid_examples
    feedback = f"<b>Результат проверки:</b>\n\n"
    feedback += f"✅ Засчитано примеров: {valid_examples}/3\n\n"
    
    if score == 3:
        feedback += "🎉 Отличная работа! Все примеры засчитаны."
    elif score > 0:
        feedback += f"💡 Неплохо, но можно лучше. Добавьте больше деталей в примеры."
    else:
        feedback += "❌ Примеры не засчитаны. Убедитесь, что они конкретные и развернутые."
    
    return score, feedback

@safe_handler()
@validate_state_transition({TASK19_WAITING})
async def handle_answer_document_task19(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка примеров из документа для task19."""
    
    # Проверяем состояние
    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана."
        )
        return ConversationHandler.END
    
    # Обрабатываем документ
    extracted_text = await DocumentHandlerMixin.handle_document_answer(
        update, 
        context,
        task_name="примеры"
    )
    
    if not extracted_text:
        return TASK19_WAITING
    
    # Валидация
    is_valid, error_msg = DocumentHandlerMixin.validate_document_content(
        extracted_text,
        task_type="examples"
    )
    
    if not is_valid:
        await update.message.reply_text(f"❌ {error_msg}")
        return TASK19_WAITING
    
    # Передаем в обычный обработчик
    update.message.text = extracted_text
    return await handle_answer(update, context)

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ теории и советов."""
    query = update.callback_query
    
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


@safe_handler()
async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ банка примеров."""
    query = update.callback_query
    
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

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def bank_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по банку примеров."""
    query = update.callback_query
    
    current_idx = int(query.data.split(":")[1])
    topics = task19_data.get('topics', [])
    
    if current_idx >= len(topics):
        current_idx = 0
    
    topic = topics[current_idx]
    
    # Визуальный прогресс
    progress_bar = UniversalUIComponents.create_progress_bar(
        current_idx + 1, len(topics), width=20, show_percentage=True
    )
    
    text = f"📚 <b>Банк примеров</b>\n{progress_bar}\n\n"
    text += f"<b>Тема:</b> {topic['title']}\n"
    text += f"<b>Задание:</b> {topic['task_text']}\n\n"
    text += "<b>Эталонные примеры:</b>\n\n"
    
    for i, example in enumerate(topic.get('example_answers', []), 1):
        # Добавляем визуальные элементы для примеров
        color = UniversalUIComponents.COLOR_INDICATORS['green']
        text += f"{color} <b>{example['type']}</b>\n"
        text += f"   {example['example']}\n\n"
    
    # Навигация
    kb_buttons = []
    nav_row = []
    
    if current_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"t19_bank_nav:{current_idx-1}"))
    
    nav_row.append(
        InlineKeyboardButton(
            create_visual_progress(current_idx + 1, len(topics)), callback_data="noop"
        )
    )
    
    if current_idx < len(topics) - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"t19_bank_nav:{current_idx+1}"))
    
    kb_buttons.append(nav_row)
    kb_buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t19_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE




@safe_handler()
@validate_state_transition({states.CHOOSING_MODE, states.CHOOSING_BLOCK, states.CHOOSING_TOPIC, TASK19_WAITING})
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню с очисткой контекста."""
    query = update.callback_query
    
    # Очищаем ВСЕ связанные с модулем данные
    keys_to_clear = [
        'current_module',
        'active_module', 
        'current_topic',
        'answer_processing',
        'current_block',
        'waiting_for_bank_search'
    ]
    
    for key in keys_to_clear:
        context.user_data.pop(key, None)
    
    await query.edit_message_text(
        "👋 Выберите раздел для изучения:",
        reply_markup=build_main_menu()
    )
    return ConversationHandler.END


@safe_handler()
async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 19."""
    query = update.callback_query
    
    # Получаем статистику для адаптивного меню
    results = context.user_data.get('task19_results', [])
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(set(r['topic'] for r in results)) / 50 * 100) if results else 0
    }
    
    greeting = get_personalized_greeting(user_stats)
    text = greeting + MessageFormatter.format_welcome_message(
        "задание 19",
        is_new_user=user_stats['total_attempts'] == 0
    )
    
    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t19")
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после показа результата."""
    query = update.callback_query
    
    if query.data == "t19_new":
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
            
            return TASK19_WAITING
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
        return await show_progress_enhanced(update, context)

@safe_handler()
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    await update.message.reply_text("Действие отменено.")
    # Возвращаемся в главное меню task19
    return await cmd_task19(update, context)

@safe_handler()
async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик для неактивных кнопок."""
    query = update.callback_query
    # Ничего не делаем, просто отвечаем на callback

@safe_handler()
async def reset_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс результатов пользователя."""
    query = update.callback_query
    
    # Проверяем, есть ли подтверждение
    if context.user_data.get('confirm_reset_task19'):
        # Сбрасываем результаты
        context.user_data['task19_results'] = []
        context.user_data.pop('confirm_reset_task19', None)
        
        
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



@safe_handler()
async def cmd_task19(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task19."""
    # Устанавливаем активный модуль
    context.user_data['current_module'] = 'task19'
    context.user_data['active_module'] = 'task19'
    
    results = context.user_data.get('task19_results', [])
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': 0,
        'weak_topics_count': 0,
        'progress_percent': int(len(set(r['topic'] for r in results)) / 50 * 100) if results else 0
    }
    
    greeting = get_personalized_greeting(user_stats)
    text = greeting + MessageFormatter.format_welcome_message(
        "задание 19",
        is_new_user=user_stats['total_attempts'] == 0
    )
    
    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t19")
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

# Добавить в handlers.py:

@safe_handler()
async def bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск темы в банке примеров."""
    query = update.callback_query
    
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


@safe_handler()
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


@safe_handler()
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
    
    nav_row.append(
        InlineKeyboardButton(
            create_visual_progress(topic_idx + 1, len(topics)), callback_data="noop"
        )
    )
    
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


@safe_handler()
async def export_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт результатов в файл."""
    query = update.callback_query
    
    results = context.user_data.get('task19_results', [])
    
    if not results:
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

@safe_handler()
async def detailed_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ детального прогресса по блокам."""
    query = update.callback_query
    
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

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def settings_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки проверки."""
    query = update.callback_query
    
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


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def apply_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка выбранного уровня строгости."""
    global evaluator
    
    query = update.callback_query
    
    level_str = query.data.split(":")[1].upper()
    
    try:
        new_level = StrictnessLevel[level_str]
        evaluator = Task19AIEvaluator(strictness=new_level)
        
        
        # Возвращаемся в настройки
        return await settings_mode(update, context)
        
    except Exception as e:
        logger.error(f"Error setting strictness: {e}")
        return states.CHOOSING_MODE

@safe_handler()
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

@safe_handler()
async def handle_theory_sections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for handling detailed theory subsections."""
    query = update.callback_query
    section = query.data.replace("t19_", "")
    text = f"📚 Раздел <b>{section}</b> пока в разработке."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="t19_theory")]])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE


@safe_handler()
async def handle_settings_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for settings related callbacks."""
    query = update.callback_query
    action = query.data.replace("t19_", "")
    if action == "reset_progress":
        await query.edit_message_text(
            "⚠️ Действие сброса прогресса недоступно в этой версии.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="t19_settings")]]),
            parse_mode=ParseMode.HTML,
        )
    else:
        await query.edit_message_text(
            "✅ Прогресс не сброшен.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="t19_settings")]]),
            parse_mode=ParseMode.HTML,
        )
    return states.CHOOSING_MODE


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def mistakes_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for mistakes training mode."""
    query = update.callback_query
    await query.edit_message_text(
        "🛠️ Режим работы над ошибками пока недоступен.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]]),
        parse_mode=ParseMode.HTML,
    )
    return states.CHOOSING_MODE


@safe_handler()
async def show_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for achievements display."""
    query = update.callback_query
    await query.edit_message_text(
        "🏆 Раздел достижений находится в разработке.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]]),
        parse_mode=ParseMode.HTML,
    )
    return states.CHOOSING_MODE