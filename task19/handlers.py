"""Обработчики для задания 19."""
import asyncio
import logging
import os
import json
import random
import time
from typing import Optional, Dict, List, Any
from core.document_processor import DocumentHandlerMixin
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest
from core.admin_tools import admin_manager
from core import states
from core.states import TASK19_WAITING
from core.ai_evaluator import Task19Evaluator, EvaluationResult
from datetime import datetime
import io
from .evaluator import StrictnessLevel, Task19AIEvaluator, AI_EVALUATOR_AVAILABLE
from core.universal_ui import UniversalUIComponents, AdaptiveKeyboards, MessageFormatter
from core.ui_helpers import (
    show_thinking_animation,
    show_extended_thinking_animation,
    show_streak_notification,
    show_ai_evaluation_animation,
    get_personalized_greeting,
    get_motivational_message,
    create_visual_progress,
    get_achievement_emoji,
)
from core.migration import ensure_module_migration
from core.error_handler import safe_handler, auto_answer_callback
from core.plugin_loader import build_main_menu
from core.state_validator import validate_state_transition, state_validator
from payment.decorators import requires_module

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
    
    # Проверяем, что пользователь админ
    if not admin_manager.is_admin(query.from_user.id):
        await query.answer("❌ Недостаточно прав", show_alert=True)
        return states.CHOOSING_MODE
    
    # Безопасно получаем текущий уровень строгости
    current_strictness = StrictnessLevel.STRICT  # значение по умолчанию
    if evaluator and hasattr(evaluator, 'strictness'):
        current_strictness = evaluator.strictness
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Мягкий", callback_data="t19_strict:lenient")],
        [InlineKeyboardButton("🟡 Стандартный", callback_data="t19_strict:standard")],
        [InlineKeyboardButton("🔴 Строгий (ФИПИ)", callback_data="t19_strict:strict")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]
    ])
    
    # Безопасное получение текущего уровня
    if evaluator and hasattr(evaluator, 'strictness'):
        current = evaluator.strictness.value
    else:
        current = "не установлен"
    
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
    
    return states.CHOOSING_MODE

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
            # ИСПРАВЛЕНИЕ: Используем обработанные данные из кэша
            task19_data = _topics_cache
            logger.info(f"Loaded task19 data from cache: {len(task19_data.get('topics', []))} topics")
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

        # ИСПРАВЛЕНИЕ: Кэшируем обработанные данные, а не сырые
        _topics_cache = task19_data
        _topics_cache_time = datetime.now()
        
        logger.info(f"Loaded {len(all_topics)} topics for task19")
    except FileNotFoundError:
        logger.error(f"File not found: {data_file}")
        task19_data = {"topics": [], "blocks": {}, "topics_by_block": {}, "topic_by_id": {}}
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in {data_file}: {e}")
        task19_data = {"topics": [], "blocks": {}, "topics_by_block": {}, "topic_by_id": {}}
    except Exception as e:
        logger.error(f"Failed to load task19 data: {e}")
        task19_data = {"topics": [], "blocks": {}, "topics_by_block": {}, "topic_by_id": {}}


@safe_handler()
@validate_state_transition({ConversationHandler.END, None})
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в задание 19 из главного меню."""
    query = update.callback_query
    
    # Устанавливаем активный модуль
    set_active_module(context)
    
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

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбора типа практики."""
    query = update.callback_query
    
    # Проверка загрузки данных
    if not task19_data or not task19_data.get('topics'):
        logger.error("Task19 data not loaded when entering practice mode")
        await query.answer("❌ Данные заданий не загружены", show_alert=True)
        
        # Пытаемся загрузить данные еще раз
        await init_task19_data()
        
        # Если после повторной загрузки данных все еще нет
        if not task19_data or not task19_data.get('topics'):
            text = """❌ <b>Данные заданий не загружены</b>
            
К сожалению, не удалось загрузить базу заданий.
Пожалуйста, обратитесь к администратору."""
            
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="t19_practice")],
                [InlineKeyboardButton("⬅️ В меню", callback_data="t19_menu")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
            ])
            
            await query.edit_message_text(
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            return states.CHOOSING_MODE
    
    # Очищаем предыдущее состояние практики
    context.user_data.pop('current_topic', None)
    context.user_data.pop('practice_results', None)
    
    # Очищаем предыдущие ID сообщений
    for key in ['task19_question_msg_id', 'task19_answer_msg_id', 
                'task19_result_msg_id', 'task19_thinking_msg_id']:
        context.user_data.pop(key, None)
    
    # Показываем меню выбора типа практики
    text = "💪 <b>Режим практики</b>\n\nВыберите способ выбора темы:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t19_random_all")],
        [InlineKeyboardButton("📚 По блокам", callback_data="t19_select_block")],
        [InlineKeyboardButton("📋 Все темы", callback_data="t19_list_topics")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]
    ])
    
    # ВАЖНО: используем edit_message_text вместо reply_text
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    # Остаемся в состоянии CHOOSING_MODE для обработки выбора
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
    """Показ прогресса с изолированным хранилищем."""
    query = update.callback_query
    
    # ИЗМЕНЕНИЕ: Используем task19_practice_stats
    results = context.user_data.get('task19_results', [])
    task19_stats = context.user_data.get('task19_practice_stats', {})
    
    if not results and not task19_stats:
        text = MessageFormatter.format_welcome_message(
            "задание 19", 
            is_new_user=True
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("💪 Начать практику", callback_data="t19_practice"),
            InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
        ]])
    else:
        total_attempts = 0
        total_score = 0
        max_possible = 0
        topic_stats_combined = {}
        
        if results:
            for result in results:
                topic_id = str(result.get('topic_id', 0))
                topic_title = result.get('topic_title', result.get('topic', 'Неизвестная тема'))
                
                if topic_id not in topic_stats_combined:
                    topic_stats_combined[topic_id] = {
                        'title': topic_title,
                        'scores': [],
                        'attempts': 0
                    }
                
                topic_stats_combined[topic_id]['scores'].append(result['score'])
                topic_stats_combined[topic_id]['attempts'] += 1
                total_attempts += 1
                total_score += result['score']
                max_possible += result.get('max_score', 3)
        
        # Дополняем из task19_practice_stats
        for topic_id_str, topic_data in task19_stats.items():
            if topic_data.get('attempts', 0) > 0:
                if topic_id_str not in topic_stats_combined:
                    topic_stats_combined[topic_id_str] = {
                        'title': topic_data.get('topic_title', f'Тема {topic_id_str}'),
                        'scores': topic_data.get('scores', []),
                        'attempts': topic_data.get('attempts', 0)
                    }
                    total_attempts += topic_data['attempts']
                    total_score += sum(topic_data.get('scores', []))
                    max_possible += topic_data['attempts'] * 3
        
        avg_score = total_score / total_attempts if total_attempts > 0 else 0
        
        text = f"""📊 <b>Ваш прогресс в Задании 19</b>

📝 <b>Всего попыток:</b> {total_attempts}
⭐ <b>Средний балл:</b> {avg_score:.1f}/3
📚 <b>Изучено тем:</b> {len(topic_stats_combined)}
"""
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Экспорт результатов", callback_data="t19_export")],
            [InlineKeyboardButton("🏅 Достижения", callback_data="t19_achievements")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]
        ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE


def _format_evaluation_result(result) -> str:
    """Форматирует результат оценки для отображения пользователю."""
    text = f"📊 <b>Результаты проверки</b>\n\n"
    
    # Итоговый балл
    total_score = getattr(result, 'total_score', 0)
    max_score = getattr(result, 'max_score', 3)
    text += f"<b>Итого: {total_score}/{max_score} баллов</b>\n\n"
    
    # Основная обратная связь
    if hasattr(result, 'feedback') and result.feedback:
        text += f"{result.feedback}\n"
    
    # Детальная информация из detailed_feedback
    if hasattr(result, 'detailed_feedback') and result.detailed_feedback:
        detail = result.detailed_feedback
        
        # Информация о засчитанных примерах
        if detail.get('valid_examples'):
            text += f"\n✅ <b>Засчитанные примеры:</b>\n"
            for ex in detail['valid_examples']:
                text += f"• Пример {ex.get('number', '?')}: {ex.get('comment', 'Пример корректный')}\n"
        
        # Информация о незасчитанных примерах
        if detail.get('invalid_examples'):
            text += f"\n❌ <b>Не засчитанные примеры:</b>\n"
            for ex in detail['invalid_examples']:
                text += f"• Пример {ex.get('number', '?')}: {ex.get('reason', 'Не соответствует критериям')}\n"
                if ex.get('improvement'):
                    text += f"  💡 <i>Совет: {ex['improvement']}</i>\n"
        
        # Информация о штрафах
        if detail.get('penalty_applied'):
            text += f"\n⚠️ <b>Применён штраф:</b> {detail.get('penalty_reason', 'Превышено количество примеров с ошибками')}\n"
    
    # Рекомендации
    if hasattr(result, 'suggestions') and result.suggestions:
        text += "\n💡 <b>Рекомендации:</b>\n"
        for suggestion in result.suggestions:
            text += f"• {suggestion}\n"
    
    # Фактические ошибки
    if hasattr(result, 'factual_errors') and result.factual_errors:
        text += "\n⚠️ <b>Обратите внимание на ошибки:</b>\n"
        for error in result.factual_errors:
            if isinstance(error, str):
                text += f"• {error}\n"
    
    # Мотивационное сообщение
    if total_score == max_score:
        text += "\n🎉 Отличная работа! Все примеры засчитаны!"
    elif total_score > 0:
        text += "\n💪 Неплохо! Продолжайте практиковаться!"
    else:
        text += "\n📚 Изучите теорию и примеры, затем попробуйте снова!"
    
    return text

@safe_handler()
@validate_state_transition({TASK19_WAITING})
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ответа пользователя на задание 19."""
    user_answer = update.message.text.strip()
    topic = context.user_data.get('current_topic')
    
    if not topic:
        await update.message.reply_text(
            "❌ Не найдена текущая тема. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ В меню", callback_data="t19_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Проверяем минимальную длину
    if len(user_answer) < 50:
        await update.message.reply_text(
            "❌ Ответ слишком короткий. Приведите три развернутых примера.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отменить", callback_data="t19_menu")
            ]])
        )
        return TASK19_WAITING
    
    # Показываем анимацию обработки
    thinking_msg = await show_ai_evaluation_animation(
        update.message,
        duration=30  # 30 секунд для task19
    )
    
    try:
        # Оцениваем ответ (AI или базовая оценка)
        if evaluator and AI_EVALUATOR_AVAILABLE:
            try:
                result = await evaluator.evaluate(
                    answer=user_answer,
                    topic=topic.get('title', ''),
                    task_text=topic.get('task_text', ''),
                    user_id=update.effective_user.id
                )
                score = result.total_score if hasattr(result, 'total_score') else result.get('score', 0)
                feedback_text = _format_evaluation_result(result)
                
            except Exception as e:
                logger.error(f"AI evaluation error: {e}")
                # Fallback к базовой оценке
                score, feedback = await _basic_evaluation(user_answer, topic)
                feedback_text = feedback
        else:
            # Базовая оценка без AI
            score, feedback_text = await _basic_evaluation(user_answer, topic)
        
        # Удаляем анимацию
        await thinking_msg.delete()
        
        # === ИСПРАВЛЕНИЕ: Используем функцию save_result_task19 ===
        # Вместо дублирующего кода сохранения в practice_stats
        # используем готовую функцию, которая сохраняет в изолированное хранилище
        save_result_task19(context, topic, score)
        
        # Обновляем серию (уже есть в save_result_task19, но дублируем для надежности)
        if score >= 2:
            context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
            
            # Показываем уведомление о серии
            if context.user_data['correct_streak'] % 3 == 0:
                await show_streak_notification(
                    update.message,
                    context.user_data['correct_streak']
                )
        else:
            context.user_data['correct_streak'] = 0
        
        # Проверяем достижения
        achievements_before = len(context.user_data.get('task19_achievements', set()))
        new_achievements = await check_achievements(context, update.effective_user.id)
        
        # Если есть новые достижения, добавляем в текст
        if new_achievements:
            feedback_text += "\n\n🏅 <b>Новые достижения:</b>"
            for ach in new_achievements:
                feedback_text += f"\n• {ach['name']}"
        
        # Формируем клавиатуру
        kb = AdaptiveKeyboards.create_result_keyboard(
            score=score,
            max_score=3,
            module_code="t19"
        )
        
        # Отправляем результат
        await update.message.reply_text(
            feedback_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        # Возвращаем состояние для продолжения
        return states.CHOOSING_MODE
        
    except Exception as e:
        logger.error(f"Error in handle_answer: {e}")
        await thinking_msg.delete()
        
        await update.message.reply_text(
            "❌ Произошла ошибка при проверке. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Попробовать снова", callback_data="t19_practice"),
                InlineKeyboardButton("📝 В меню", callback_data="t19_menu")
            ]])
        )
        return states.CHOOSING_MODE

def save_result_task19(context: ContextTypes.DEFAULT_TYPE, topic: Dict, score: int):
    """Сохраняет результат проверки для task19 с изолированным хранилищем."""
    from datetime import datetime
    
    if 'task19_results' not in context.user_data:
        context.user_data['task19_results'] = []
    
    if isinstance(topic, dict):
        topic_id = topic.get('id', 0)
        topic_title = topic.get('title', 'Неизвестная тема')
        block = topic.get('block', 'Общие темы')
        task_text = topic.get('task_text', '')
    else:
        topic_id = hash(str(topic)) % 10000
        topic_title = str(topic)
        block = 'Общие темы'
        task_text = ''
    
    result = {
        'topic_id': topic_id,
        'topic': topic_title,
        'topic_title': topic_title,
        'block': block,
        'score': score,
        'max_score': 3,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'task_text': task_text[:100] if task_text else ''
    }
    
    context.user_data['task19_results'].append(result)
    
    # ИЗМЕНЕНИЕ: Используем task19_practice_stats вместо practice_stats
    if 'task19_practice_stats' not in context.user_data:
        context.user_data['task19_practice_stats'] = {}
    
    topic_id_str = str(topic_id)
    
    if topic_id_str not in context.user_data['task19_practice_stats']:
        context.user_data['task19_practice_stats'][topic_id_str] = {
            'attempts': 0,
            'scores': [],
            'last_attempt': None,
            'best_score': 0,
            'topic_title': topic_title,
            'topic_id': topic_id,
            'module': 'task19'
        }
    
    topic_stats = context.user_data['task19_practice_stats'][topic_id_str]
    topic_stats['attempts'] += 1
    topic_stats['scores'].append(score)
    topic_stats['last_attempt'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    topic_stats['best_score'] = max(topic_stats.get('best_score', 0), score)
    topic_stats['topic_title'] = topic_title
    
    if score >= 2:
        context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
    else:
        context.user_data['correct_streak'] = 0
    
    return result

@safe_handler()
async def handle_new_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопки 'Новое задание'."""
    query = update.callback_query
    await query.answer()
    
    # Переходим к выбору новой темы
    return await practice_mode(update, context)

def _build_topic_message(topic: Dict) -> str:
    """Строит сообщение с заданием для темы."""
    text = f"""📝 <b>Задание 19</b>

<b>Тема:</b> {topic.get('title', 'Неизвестная тема')}

<b>Задание:</b>
{topic.get('task_text', 'Текст задания не найден')}

<b>Требования:</b>
• Приведите ТРИ примера
• Каждый пример должен быть конкретным
• Используйте имена, даты, места
• Избегайте общих фраз

💡 <i>Отправьте ваш ответ текстом или документом</i>"""
    
    return text

@safe_handler()
async def handle_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопки 'Попробовать снова'."""
    query = update.callback_query
    await query.answer()
    
    topic = context.user_data.get('current_topic')
    if topic:
        # Проверяем формат topic
        if isinstance(topic, str):
            # Ищем полный объект
            for t in task19_data.get('topics', []):
                if t.get('title') == topic:
                    topic = t
                    context.user_data['current_topic'] = topic
                    break
            else:
                await query.answer("❌ Ошибка: тема не найдена", show_alert=True)
                return await return_to_menu(update, context)
        
        text = _build_topic_message(topic)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Выбрать другую тему", callback_data="t19_practice")
        ]])
        
        await query.edit_message_text(
            text, 
            reply_markup=kb, 
            parse_mode=ParseMode.HTML
        )
        
        # Устанавливаем состояние
        from core.state_validator import state_validator
        state_validator.set_state(query.from_user.id, TASK19_WAITING)
        
        return TASK19_WAITING
    else:
        await query.answer("❌ Ошибка: тема не найдена", show_alert=True)
        return await return_to_menu(update, context)

@safe_handler()
async def handle_show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопки 'Мой прогресс'."""
    return await show_progress_enhanced(update, context)

@safe_handler()
async def handle_theory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопки 'Изучить теорию'."""
    return await theory_mode(update, context)

@safe_handler()
async def handle_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопки 'Примеры'."""
    return await examples_bank(update, context)

@safe_handler()
async def handle_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопки 'Достижения'."""
    return await show_achievements(update, context)

@safe_handler()
async def handle_show_ideal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопки 'Посмотреть эталон'."""
    query = update.callback_query
    await query.answer("Эта функция находится в разработке", show_alert=True)
    return states.CHOOSING_MODE

async def _basic_evaluation(answer: str, topic: Any) -> tuple[int, str]:
    """Базовая оценка без AI."""
    # Получаем название темы независимо от формата
    if isinstance(topic, dict):
        topic_title = topic.get('title', 'Неизвестная тема')
    elif isinstance(topic, str):
        topic_title = topic
    else:
        topic_title = 'Неизвестная тема'
    
    # Базовая проверка количества примеров
    lines = [line.strip() for line in answer.split('\n') if line.strip()]
    examples_count = 0
    
    # Простой подсчет примеров по номерам или буллетам
    for line in lines:
        if any(line.startswith(marker) for marker in ['1.', '2.', '3.', '•', '-', '*', '1)', '2)', '3)']):
            examples_count += 1
    
    # Оценка
    if examples_count >= 3 and len(answer) > 200:
        score = 3
        feedback = f"✅ Хорошо! Вы привели {examples_count} примера. "
    elif examples_count >= 2 and len(answer) > 150:
        score = 2
        feedback = f"👍 Неплохо! Засчитано {examples_count} примера. "
    elif examples_count >= 1 and len(answer) > 100:
        score = 1
        feedback = "📝 Засчитан 1 пример. "
    else:
        score = 0
        feedback = "❌ Примеры не засчитаны. "
    
    # Дополнительная обратная связь
    if score == 3:
        feedback += "Все примеры засчитаны."
    elif score > 0:
        feedback += f"💡 Неплохо, но можно лучше. Добавьте больше деталей в примеры."
    else:
        feedback += "❌ Примеры не засчитаны. Убедитесь, что они конкретные и развернутые."
    
    return score, feedback

def _format_evaluation_result(result) -> str:
    """Форматирование результата проверки AI."""
    # Безопасное получение значений
    if isinstance(result, dict):
        score = result.get('total_score', 0)
        max_score = result.get('max_score', 3)
        feedback_text = result.get('feedback', '')
        suggestions = result.get('suggestions', [])
        detailed = result.get('detailed_feedback', {})
    else:
        score = getattr(result, 'total_score', 0)
        max_score = getattr(result, 'max_score', 3)
        feedback_text = getattr(result, 'feedback', '')
        suggestions = getattr(result, 'suggestions', [])
        detailed = getattr(result, 'detailed_feedback', {})
    
    # Преобразуем в int
    score = int(score)
    max_score = int(max_score)
    
    # Заголовок в зависимости от результата
    percentage = (score / max_score * 100) if max_score > 0 else 0
    
    if percentage >= 90:
        header = "🎉 <b>Отличный результат!</b>"
    elif percentage >= 60:
        header = "👍 <b>Хороший результат!</b>"
    elif percentage >= 30:
        header = "📝 <b>Неплохо, но есть над чем поработать</b>"
    else:
        header = "❌ <b>Нужно больше практики</b>"
    
    # Основная информация
    feedback = f"{header}\n\n"
    feedback += f"<b>Ваш балл:</b> {score} из {max_score}\n\n"
    
    # Детальный разбор (если есть)
    if detailed and isinstance(detailed, dict):
        feedback += "<b>📊 Анализ ответа:</b>\n"
        
        # Информация о примерах
        valid_count = detailed.get('valid_examples_count', 0)
        total_count = detailed.get('total_examples', 0)
        
        if total_count > 0:
            feedback += f"• Всего примеров: {total_count}\n"
            feedback += f"• Засчитано: {valid_count}\n"
            
            # Штрафы
            if detailed.get('penalty_applied'):
                reason = detailed.get('penalty_reason', 'нарушение требований')
                feedback += f"• ⚠️ Применен штраф: {reason}\n"
        
        feedback += "\n"
    
    # Краткая обратная связь от AI
    if feedback_text:
        feedback += f"<b>💭 Комментарий:</b>\n{feedback_text}\n\n"
    
    # Рекомендации (без дублирования)
    if suggestions and isinstance(suggestions, list):
        unique_suggestions = []
        seen = set()
        for s in suggestions:
            if s and s not in seen:
                unique_suggestions.append(s)
                seen.add(s)
        
        if unique_suggestions:
            feedback += "<b>💡 Рекомендации:</b>\n"
            for suggestion in unique_suggestions[:3]:
                feedback += f"• {suggestion}\n"
    
    return feedback.strip()

@safe_handler()
@validate_state_transition({TASK19_WAITING})
async def handle_answer_document_task19(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка примеров из документа для task19."""
    
    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана."
        )
        return ConversationHandler.END

    # Обработка старого формата (если topic - строка)
    if isinstance(topic, str):
        # Ищем полный объект темы
        for t in task19_data.get('topics', []):
            if t.get('title') == topic:
                topic = t
                context.user_data['current_topic'] = topic
                break
        else:
            await update.message.reply_text(
                "❌ Ошибка: данные темы не найдены."
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
    
    # ИСПРАВЛЕНИЕ: Сохраняем текст в контексте
    context.user_data['document_text'] = extracted_text
    
    # Вызываем обычный обработчик
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
@validate_state_transition({states.CHOOSING_MODE})
async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ банка эталонных примеров."""
    query = update.callback_query
    
    # ДОБАВЛЕНО: Проверка и повторная загрузка данных при необходимости
    if not task19_data or not task19_data.get('topics'):
        logger.warning("Task19 data not loaded when accessing examples bank")
        await query.answer("⏳ Загружаю данные...", show_alert=False)
        
        # Пытаемся загрузить данные
        await init_task19_data()
    
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
            [InlineKeyboardButton("➡️ Следующая тема", callback_data="t19_bank_nav:1")],
            [InlineKeyboardButton("🔍 Поиск темы", callback_data="t19_bank_search")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]
        ])
    else:
        # ИСПРАВЛЕНО: Более информативное сообщение об ошибке
        text = """📚 <b>Банк примеров</b>

❌ <b>Не удалось загрузить банк примеров</b>

Возможные причины:
• Файл с данными отсутствует или поврежден
• Проблемы с правами доступа к файлу

Пожалуйста, обратитесь к администратору."""
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="t19_examples")],
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
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    # Просто вызываем глобальный обработчик
    from core.menu_handlers import handle_to_main_menu
    return await handle_to_main_menu(update, context)



@safe_handler()
async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню task19."""
    query = update.callback_query
    
    # Автоматическая миграция при возврате
    from core.migration import ensure_module_migration
    ensure_module_migration(context, 'task19', task19_data)  # Передаем context, НЕ context.user_data!
    
    # Устанавливаем активный модуль
    set_active_module(context)
    
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

@safe_handler()
async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после показа результата."""
    query = update.callback_query
    
    # Обрабатываем оба варианта callback_data (с полным и коротким префиксом)
    action = query.data
    if action.startswith("task19_"):
        action = action.replace("task19_", "t19_")
    
    if action == "t19_new":
        # Показываем меню выбора темы
        return await practice_mode(update, context)
    
    elif action == "t19_retry":
        # Показываем то же задание заново
        topic = context.user_data.get('current_topic')
        if topic:
            text = _build_topic_message(topic)
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Выбрать другую тему", callback_data="t19_practice")
            ]])
            
            await query.edit_message_text(
                text, 
                reply_markup=kb, 
                parse_mode=ParseMode.HTML
            )
            
            # Устанавливаем состояние
            from core.state_validator import state_validator
            state_validator.set_state(query.from_user.id, TASK19_WAITING)
            
            return TASK19_WAITING
        else:
            await query.answer("❌ Ошибка: тема не найдена", show_alert=True)
            return await return_to_menu(update, context)
    
    elif action == "t19_menu":
        # Возвращаемся в главное меню задания
        return await return_to_menu(update, context)
    
    elif action == "t19_progress":
        # Показываем прогресс
        return await show_progress_enhanced(update, context)
    
    elif action == "t19_show_ideal":
        # Показываем идеальный ответ (если реализовано)
        await query.answer("Эта функция находится в разработке", show_alert=True)
        return states.CHOOSING_MODE
    
    else:
        # Неизвестное действие
        await query.answer("Неизвестное действие", show_alert=True)
        return states.CHOOSING_MODE

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

def migrate_task19_data(context: ContextTypes.DEFAULT_TYPE):
    """Миграция данных task19 из общего practice_stats в изолированное хранилище."""
    
    # Если уже есть изолированное хранилище, пропускаем миграцию
    if 'task19_practice_stats' in context.user_data:
        return
    
    # Создаем изолированное хранилище
    context.user_data['task19_practice_stats'] = {}
    
    # Если есть общий practice_stats, пытаемся извлечь данные task19
    if 'practice_stats' in context.user_data and task19_data and 'topics' in task19_data:
        # Получаем все topic_id из task19
        task19_topic_ids = {str(t.get('id', 0)) for t in task19_data['topics']}
        
        # Копируем только темы task19 в изолированное хранилище
        for topic_id_str, topic_data in context.user_data['practice_stats'].items():
            if topic_id_str in task19_topic_ids:
                context.user_data['task19_practice_stats'][topic_id_str] = topic_data.copy()
                # Добавляем идентификатор модуля
                context.user_data['task19_practice_stats'][topic_id_str]['module'] = 'task19'
    
    # Также мигрируем из task19_results если они есть
    if 'task19_results' in context.user_data:
        for result in context.user_data['task19_results']:
            topic_id_str = str(result.get('topic_id', 0))
            
            # Если этой темы еще нет в practice_stats
            if topic_id_str not in context.user_data['task19_practice_stats']:
                context.user_data['task19_practice_stats'][topic_id_str] = {
                    'attempts': 1,
                    'scores': [result['score']],
                    'last_attempt': result.get('timestamp'),
                    'best_score': result['score'],
                    'topic_title': result.get('topic_title', result.get('topic', 'Неизвестная тема')),
                    'topic_id': result.get('topic_id'),
                    'module': 'task19'
                }

async def reset_progress_task19(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полный сброс прогресса task19."""
    query = update.callback_query
    
    # Сбрасываем ТОЛЬКО данные task19
    context.user_data.pop('task19_results', None)
    context.user_data.pop('task19_practice_stats', None)  # Изолированное хранилище
    context.user_data.pop('task19_achievements', None)
    
    await query.answer("✅ Прогресс по заданию 19 сброшен!", show_alert=True)
    return await return_to_menu(update, context)

@safe_handler()
async def cmd_task19(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task19."""
    # ИСПРАВЛЕНИЕ: Вызываем миграцию данных в изолированное хранилище
    migrate_task19_data(context)  # Добавить эту строку если её нет
    
    # Устанавливаем активный модуль
    set_active_module(context)
    
    # Используем изолированное хранилище для статистики
    results = context.user_data.get('task19_results', [])
    task19_stats = context.user_data.get('task19_practice_stats', {})  # Изолированное хранилище
    
    # Подсчитываем статистику из изолированного хранилища
    total_attempts = sum(data.get('attempts', 0) for data in task19_stats.values())
    
    user_stats = {
        'total_attempts': total_attempts,
        'average_score': sum(r['score'] for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(task19_stats) / 50 * 100) if task19_stats else 0
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
    """Команда быстрого доступа к настройкам task19."""
    # Безопасное получение текущего уровня
    if evaluator and hasattr(evaluator, 'strictness'):
        current_level = evaluator.strictness
    else:
        current_level = StrictnessLevel.STRICT if StrictnessLevel else None
    
    text = """⚙️ <b>Быстрые настройки задания 19</b>

"""
    
    if current_level:
        text += f"Текущий уровень проверки: <b>{current_level.value}</b>\n\n"
    else:
        text += "Уровень проверки: <b>не установлен</b>\n\n"
    
    text += "Используйте кнопки ниже для изменения:"
    
    kb_buttons = []
    
    if StrictnessLevel:  # Проверяем, что enum импортирован
        for level in StrictnessLevel:
            emoji = "✅" if current_level and level == current_level else ""
            kb_buttons.append([
                InlineKeyboardButton(
                    f"{emoji} {level.value}",
                    callback_data=f"t19_set_strictness:{level.name}"
                )
            ])
    else:
        kb_buttons.append([
            InlineKeyboardButton("⚠️ Настройки недоступны", callback_data="noop")
        ])
    
    kb_buttons.append([
        InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def handle_theory_sections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка разделов теории."""
    query = update.callback_query
    section = query.data.replace("t19_", "")
    
    # Содержание для разных разделов
    theory_content = {
        'how_to_write': {
            'title': 'Как писать примеры',
            'content': """📝 <b>Как правильно приводить примеры</b>

<b>1. Структура примера:</b>
- Конкретное событие или явление
- Указание времени и места (если важно)
- Краткое описание сути
- Связь с аргументом

<b>2. Требования:</b>
- Достоверность и проверяемость
- Конкретность (не абстрактные рассуждения)
- Релевантность теме
- Краткость и ёмкость

<b>3. Избегайте:</b>
- Вымышленных примеров
- Слишком общих формулировок
- Примеров без связи с темой
- Повторов и тавтологии"""
        },
        'good_examples': {
            'title': 'Удачные примеры',
            'content': """✅ <b>Примеры хороших формулировок</b>

<b>Пример 1:</b>
"Великая Отечественная война показала силу духа советского народа: блокада Ленинграда продолжалась 872 дня, но город не сдался."

<b>Почему хорошо:</b>
- Конкретное событие
- Точные данные
- Ясная связь с темой

<b>Пример 2:</b>
"Реформы Петра I кардинально изменили Россию: строительство Санкт-Петербурга, создание флота, введение Табели о рангах."

<b>Почему хорошо:</b>
- Перечислены конкретные реформы
- Показан масштаб изменений
- Примеры подтверждают тезис"""
        },
        'common_mistakes': {
            'title': 'Частые ошибки',
            'content': """❌ <b>Типичные ошибки в примерах</b>

<b>1. Слишком общие формулировки:</b>
❌ "Многие войны показывают героизм"
✅ "Сталинградская битва показала героизм"

<b>2. Отсутствие конкретики:</b>
❌ "Известный учёный сделал открытие"
✅ "Менделеев открыл периодический закон"

<b>3. Неточные данные:</b>
❌ "В прошлом веке была война"
✅ "Первая мировая война 1914-1918 гг."

<b>4. Примеры не по теме:</b>
❌ Пример про экономику к теме культуры
✅ Пример строго по заданной теме"""
        },
        'useful_phrases': {
            'title': 'Полезные фразы',
            'content': """💬 <b>Фразы-связки для примеров</b>

<b>Для введения примера:</b>
- "Ярким примером является..."
- "Это подтверждается..."
- "Показательным является..."
- "Можно привести пример..."

<b>Для связи с аргументом:</b>
- "Этот пример демонстрирует..."
- "Данное событие подтверждает..."
- "Это свидетельствует о..."
- "Таким образом, мы видим..."

<b>Для перехода между примерами:</b>
- "Другим примером служит..."
- "Также можно отметить..."
- "Не менее важным является..."
- "Кроме того, стоит упомянуть..." """
        }
    }
    
    section_data = theory_content.get(section)
    
    if section_data:
        text = f"📚 <b>{section_data['title']}</b>\n\n{section_data['content']}"
    else:
        text = f"📚 Раздел <b>{section}</b> находится в разработке."
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ К теории", callback_data="t19_theory")
    ]])
    
    await query.edit_message_text(
        text, 
        reply_markup=kb, 
        parse_mode=ParseMode.HTML
    )
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
async def retry_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повторить задание по конкретной теме из работы над ошибками."""
    query = update.callback_query
    topic_id = query.data.split(':')[1]
    
    # Ищем задания по этой теме
    topic_questions = []
    topic_name = None
    
    for block_data in task19_data.values():
        for topic, questions in block_data.items():
            if questions and len(questions) > 0:
                if questions[0].get('topic_id') == topic_id:
                    topic_questions = questions
                    topic_name = topic
                    break
        if topic_questions:
            break
    
    if not topic_questions:
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE
    
    # Выбираем случайный вопрос
    question = random.choice(topic_questions)
    context.user_data['task19_current_question'] = question
    context.user_data['task19_retry_mode'] = True  # Флаг режима работы над ошибками
    
    text = f"🔧 <b>Работа над ошибками</b>\n"
    text += f"📚 Тема: <i>{topic_name}</i>\n\n"
    text += f"<b>{question['question']}</b>\n\n"
    text += "Приведите конкретный пример из истории."
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Отмена", callback_data="t19_mistakes")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.TASK19_WAITING


@safe_handler()
async def apply_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Применить выбранный уровень строгости."""
    global evaluator
    
    query = update.callback_query
    level_name = query.data.split(':')[1].upper()
    
    try:
        if StrictnessLevel:
            new_level = StrictnessLevel[level_name]
            
            # Пересоздаем evaluator с новым уровнем
            evaluator = Task19AIEvaluator(strictness=new_level)
            
            await query.answer(f"✅ Установлен уровень: {new_level.value}")
            
            # Возвращаемся в меню настроек
            return await strictness_menu(update, context)
        else:
            await query.answer("❌ Ошибка изменения настроек", show_alert=True)
            return states.CHOOSING_MODE
            
    except Exception as e:
        logger.error(f"Error setting strictness: {e}")
        await query.answer("❌ Ошибка изменения настроек", show_alert=True)
        return states.CHOOSING_MODE


@safe_handler()
async def show_achievement_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать детали конкретного достижения."""
    query = update.callback_query
    achievement_id = query.data.split(':')[1]
    
    # Детальные описания достижений
    achievement_details = {
        'first_example': {
            'name': '🌟 Первый пример',
            'desc': 'Вы привели свой первый корректный пример!',
            'tips': 'Это только начало! Продолжайте практиковаться для улучшения навыка.'
        },
        'perfect_5': {
            'name': '🎯 Пять идеалов',
            'desc': 'Получено 5 отличных оценок за примеры!',
            'tips': 'Вы отлично усвоили принципы. Попробуйте более сложные темы!'
        },
        'explorer_10': {
            'name': '🗺️ Исследователь',
            'desc': 'Изучено 10 разных тем!',
            'tips': 'Широкий кругозор - ключ к успеху на экзамене.'
        },
        'master_50': {
            'name': '🏆 Мастер примеров',
            'desc': 'Выполнено 50 заданий с высоким средним баллом!',
            'tips': 'Вы настоящий эксперт! Помогите другим освоить это задание.'
        }
    }
    
    details = achievement_details.get(achievement_id)
    if not details:
        await query.answer("Достижение не найдено", show_alert=True)
        return states.CHOOSING_MODE
    
    has_achievement = achievement_id in context.user_data.get('task19_achievements', set())
    
    text = f"{details['name']}\n\n"
    text += f"📝 <b>Описание:</b>\n{details['desc']}\n\n"
    
    if has_achievement:
        text += f"✅ <b>Получено!</b>\n\n"
        text += f"💡 <b>Совет:</b>\n{details['tips']}"
    else:
        text += "🔒 <b>Еще не получено</b>\n\n"
        text += "Продолжайте практиковаться!"
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ К достижениям", callback_data="t19_achievements")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def achievement_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки OK в уведомлении о достижении."""
    query = update.callback_query
    
    try:
        await query.message.delete()
    except:
        pass
    
    await query.answer()
    return None  # Не меняем состояние

@safe_handler()
async def show_ideal_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать эталонный ответ."""
    query = update.callback_query
    
    current_question = context.user_data.get('task19_current_question')
    if not current_question:
        await query.answer("Вопрос не найден", show_alert=True)
        return states.CHOOSING_MODE
    
    ideal_examples = current_question.get('examples', [])
    if not ideal_examples:
        await query.answer("Эталонные примеры не найдены", show_alert=True)
        return states.CHOOSING_MODE
    
    text = "💎 <b>Эталонные примеры:</b>\n\n"
    
    for i, example in enumerate(ideal_examples[:3], 1):
        text += f"<b>Пример {i}:</b>\n"
        text += f"{example}\n\n"
    
    text += "💡 <b>Обратите внимание:</b>\n"
    text += "• Конкретность формулировок\n"
    text += "• Точные даты и факты\n"
    text += "• Связь с темой вопроса\n"
    text += "• Краткость и ёмкость"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Попробовать снова", callback_data="t19_retry")],
        [InlineKeyboardButton("📝 Новое задание", callback_data="t19_new")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="t19_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def reset_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс результатов - показывает подтверждение."""
    query = update.callback_query
    
    results = context.user_data.get('task19_results', [])
    achievements = context.user_data.get('task19_achievements', set())
    
    if not results:
        await query.answer("Нет данных для сброса", show_alert=True)
        return states.CHOOSING_MODE
    
    text = (
        "⚠️ <b>Сброс прогресса</b>\n\n"
        "Вы уверены, что хотите сбросить весь прогресс?\n\n"
        f"Будет удалено:\n"
        f"• {len(results)} результатов\n"
        f"• {len(achievements)} достижений\n"
        f"• Вся статистика\n\n"
        "Это действие нельзя отменить!"
    )
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, сбросить", callback_data="t19_confirm_reset"),
            InlineKeyboardButton("❌ Отмена", callback_data="t19_settings")
        ]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def confirm_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение и выполнение сброса."""
    query = update.callback_query
    
    # Полный сброс данных
    context.user_data.pop('task19_results', None)
    context.user_data.pop('task19_achievements', None)
    context.user_data.pop('correct_streak', None)
    context.user_data.pop('practice_stats', None)
    context.user_data.pop('current_topic', None)
    context.user_data.pop('task19_current_topic', None)
    
    await query.answer("✅ Прогресс успешно сброшен!", show_alert=True)
    
    # Возвращаемся в меню
    return await return_to_menu(update, context)

async def show_achievement_notification(
    message: Message, 
    achievements: List[Dict],
    context: ContextTypes.DEFAULT_TYPE
):
    """Показать красивое уведомление о новых достижениях."""
    if not achievements:
        return
    
    for achievement in achievements:
        emoji = get_achievement_emoji(achievement['id'])
        
        text = f"{emoji} <b>Новое достижение!</b>\n\n"
        text += f"🏅 <b>{achievement['name']}</b>\n"
        text += f"📝 {achievement['desc']}\n\n"
        
        # Добавляем мотивационную фразу
        motivational = [
            "Отличная работа! Так держать! 🚀",
            "Вы делаете успехи! Продолжайте! 💪",
            "Превосходно! Новая вершина взята! 🏔️",
            "Браво! Ваше мастерство растет! 📈"
        ]
        text += f"<i>{random.choice(motivational)}</i>"
        
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("👍 Отлично!", callback_data="achievement_ok"),
            InlineKeyboardButton("🏆 Все достижения", callback_data="t19_achievements")
        ]])
        
        await message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        # Небольшая задержка между уведомлениями
        if len(achievements) > 1:
            await asyncio.sleep(1)

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def mistakes_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим работы над ошибками."""
    query = update.callback_query
    
    # Получаем результаты пользователя
    results = context.user_data.get('task19_results', [])
    
    # Находим темы с низкими баллами (меньше 2)
    low_score_topics = {}
    for result in results:
        if result.get('score', 0) < 2:
            topic_id = result.get('topic_id')
            if topic_id:
                if topic_id not in low_score_topics:
                    low_score_topics[topic_id] = {
                        'count': 0,
                        'avg_score': 0,
                        'scores': []
                    }
                low_score_topics[topic_id]['count'] += 1
                low_score_topics[topic_id]['scores'].append(result.get('score', 0))
    
    # Вычисляем средние баллы
    for topic_id, data in low_score_topics.items():
        data['avg_score'] = sum(data['scores']) / len(data['scores'])
    
    if not low_score_topics:
        text = "👍 <b>Отличная работа!</b>\n\n"
        text += "У вас нет тем с низкими баллами для повторения.\n"
        text += "Продолжайте практиковаться для поддержания навыка!"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💪 К практике", callback_data="t19_practice")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")]
        ])
    else:
        # Сортируем темы по среднему баллу (сначала худшие)
        sorted_topics = sorted(low_score_topics.items(), 
                             key=lambda x: x[1]['avg_score'])
        
        text = "🔧 <b>Работа над ошибками</b>\n\n"
        text += "Темы, требующие внимания:\n\n"
        
        buttons = []
        for i, (topic_id, data) in enumerate(sorted_topics[:5], 1):
            # Получаем название темы из task19_data
            topic_name = topic_id  # По умолчанию ID
            for block_data in task19_data.values():
                for topic, topic_data in block_data.items():
                    if topic_data and len(topic_data) > 0 and topic_data[0].get('topic_id') == topic_id:
                        topic_name = topic
                        break
            
            avg_visual = UniversalUIComponents.create_score_visual(
                data['avg_score'], 
                3,  # Максимальный балл для task19
                use_stars=False
            )
            
            text += f"{i}. {topic_name}\n"
            text += f"   Попыток: {data['count']}, Средний балл: {avg_visual}\n\n"
            
            buttons.append([InlineKeyboardButton(
                f"📝 {topic_name[:30]}{'...' if len(topic_name) > 30 else ''}",
                callback_data=f"t19_retry_topic:{topic_id}"
            )])
        
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")])
        kb = InlineKeyboardMarkup(buttons)
        
        text += "\n💡 <i>Выберите тему для повторения</i>"
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE


@safe_handler()
async def show_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать достижения пользователя."""
    query = update.callback_query
    
    achievements = context.user_data.get('task19_achievements', set())
    
    # Определение всех возможных достижений
    all_achievements = {
        'first_example': ('🌟 Первый пример', 'Привести первый корректный пример'),
        'perfect_5': ('🎯 Пять идеалов', 'Получить максимальный балл 5 раз'),
        'explorer_10': ('🗺️ Исследователь', 'Изучить 10 разных тем'),
        'persistent_20': ('💪 Упорство', 'Выполнить 20 заданий'),
        'master_50': ('🏆 Мастер примеров', 'Выполнить 50 заданий со средним баллом выше 2'),
        'speed_demon': ('⚡ Скорость', 'Дать правильный ответ менее чем за минуту'),
        'comeback': ('🔥 Возвращение', 'Получить максимум после серии неудач')
    }
    
    text = "🏅 <b>Ваши достижения в Задании 19</b>\n\n"
    
    # Полученные достижения
    if achievements:
        text += "<b>✅ Получено:</b>\n"
        for ach_id in achievements:
            if ach_id in all_achievements:
                name, desc = all_achievements[ach_id]
                emoji = get_achievement_emoji(ach_id)
                text += f"{emoji} {name} - {desc}\n"
        text += "\n"
    
    # Доступные достижения
    not_achieved = set(all_achievements.keys()) - achievements
    if not_achieved:
        text += "<b>🔓 Доступно:</b>\n"
        for ach_id in sorted(not_achieved):
            name, desc = all_achievements[ach_id]
            text += f"⚪ {name[2:]} - {desc}\n"
    
    # Прогресс
    progress_bar = UniversalUIComponents.create_progress_bar(
        len(achievements), 
        len(all_achievements),
        width=10
    )
    text += f"\n<b>📊 Прогресс:</b> {progress_bar}"
    
    # Мотивационное сообщение
    percentage = len(achievements) / len(all_achievements) if all_achievements else 0
    if percentage == 1:
        text += "\n\n🎊 Поздравляем! Вы собрали все достижения!"
    elif percentage >= 0.7:
        text += "\n\n💪 Отличный прогресс! Осталось совсем немного!"
    elif percentage >= 0.3:
        text += "\n\n📈 Хороший старт! Продолжайте в том же духе!"
    else:
        text += "\n\n🌟 Каждое достижение - шаг к мастерству!"
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t19_progress")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def check_achievements(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> List[Dict]:
    """Проверка и выдача новых достижений."""
    results = context.user_data.get('task19_results', [])
    achievements = context.user_data.get('task19_achievements', set())
    new_achievements = []
    
    # Условия для достижений
    if len(results) >= 1 and 'first_example' not in achievements:
        achievements.add('first_example')
        new_achievements.append({
            'id': 'first_example',
            'name': '🌟 Первый пример',
            'desc': 'Вы привели свой первый пример!'
        })
    
    perfect_count = sum(1 for r in results if r.get('score', 0) >= 2.5)
    if perfect_count >= 5 and 'perfect_5' not in achievements:
        achievements.add('perfect_5')
        new_achievements.append({
            'id': 'perfect_5',
            'name': '🎯 Пять идеалов',
            'desc': 'Получено 5 отличных оценок!'
        })
    
    unique_topics = len(set(r.get('topic_id', r.get('topic')) for r in results))
    if unique_topics >= 10 and 'explorer_10' not in achievements:
        achievements.add('explorer_10')
        new_achievements.append({
            'id': 'explorer_10',
            'name': '🗺️ Исследователь',
            'desc': 'Изучено 10 разных тем!'
        })
    
    if len(results) >= 20 and 'persistent_20' not in achievements:
        achievements.add('persistent_20')
        new_achievements.append({
            'id': 'persistent_20',
            'name': '💪 Упорство',
            'desc': 'Выполнено 20 заданий!'
        })
    
    if len(results) >= 50:
        avg = sum(r.get('score', 0) for r in results) / len(results)
        if avg > 2 and 'master_50' not in achievements:
            achievements.add('master_50')
            new_achievements.append({
                'id': 'master_50',
                'name': '🏆 Мастер примеров',
                'desc': 'Выполнено 50 заданий с высоким средним баллом!'
            })
    
    # Сохраняем обновленные достижения
    context.user_data['task19_achievements'] = achievements
    
    return new_achievements
