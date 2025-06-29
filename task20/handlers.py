# Начало файла task20/handlers.py
import logging
import os
import csv
import io
import json
from typing import Optional, Dict, List
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
from core.admin_tools import admin_manager
from core import states
from core.states import ANSWERING_T20, SEARCHING, VIEWING_EXAMPLE, CONFIRMING_RESET
from core.universal_ui import UniversalUIComponents, AdaptiveKeyboards, MessageFormatter
from core.ui_helpers import (
    show_thinking_animation,
    show_streak_notification,
    show_extended_thinking_animation,
    get_personalized_greeting,
    get_motivational_message,
    create_visual_progress
)
from core.error_handler import safe_handler, auto_answer_callback
from core.plugin_loader import build_main_menu
from core.state_validator import validate_state_transition, state_validator
from core.utils import safe_edit_message

logger = logging.getLogger(__name__)

# Глобальные переменные для данных
task20_data = {}
topic_selector = None
evaluator = None

# Импорты внутренних модулей ПОСЛЕ определения переменных
try:
    from .evaluator import Task20AIEvaluator, StrictnessLevel, EvaluationResult, AI_EVALUATOR_AVAILABLE
except ImportError as e:
    logger.error(f"Failed to import evaluator: {e}")
    AI_EVALUATOR_AVAILABLE = False

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

try:
    from .user_experience import UserProgress, SmartRecommendations
except ImportError as e:
    logger.error(f"Failed to import user_experience: {e}")
    UserProgress = None
    SmartRecommendations = None

async def init_task20_data():
    """Инициализация данных с кэшированием."""
    global task20_data, evaluator, topic_selector
    
    # Проверяем кэш
    if cache:
        cached_data = await cache.get('task20_data')
        if cached_data:
            task20_data = cached_data
            if TopicSelector:
                topic_selector = TopicSelector(task20_data['topics'])
            logger.info("Loaded task20 data from cache")
        else:
            # Загружаем из файла
            data_file = os.path.join(os.path.dirname(__file__), "task20_topics.json")
            
            # Проверяем наличие файла
            if not os.path.exists(data_file):
                logger.error(f"Topics file not found: {data_file}")
                task20_data = {
                    "topics": [],
                    "topic_by_id": {},
                    "topics_by_block": {},
                    "blocks": {}
                }
                topic_selector = None
                logger.warning("Task20 initialized with empty data due to missing topics file")
            else:
                try:
                    with open(data_file, "r", encoding="utf-8") as f:
                        topics_list = json.load(f)
                    
                    # Проверяем, что это список
                    if not isinstance(topics_list, list):
                        logger.error(f"Invalid topics file format: expected list, got {type(topics_list)}")
                        topics_list = []
                    
                    # Преобразуем список тем в нужную структуру
                    all_topics = []
                    topic_by_id = {}
                    topics_by_block = {}
                    blocks = {}
                    
                    for topic in topics_list:
                        # Валидация темы
                        if not isinstance(topic, dict):
                            logger.warning(f"Skipping invalid topic: {topic}")
                            continue
                        
                        if 'id' not in topic or 'title' not in topic:
                            logger.warning(f"Skipping topic without id or title: {topic}")
                            continue
                        
                        # Добавляем тему в общий список
                        all_topics.append(topic)
                        
                        # Индексируем по ID
                        topic_by_id[str(topic["id"])] = topic
                        
                        # Группируем по блокам
                        block_name = topic.get("block", "Без категории")
                        if block_name not in topics_by_block:
                            topics_by_block[block_name] = []
                            blocks[block_name] = {"topics": []}
                        
                        topics_by_block[block_name].append(topic)
                        blocks[block_name]["topics"].append(topic)
                    
                    # Формируем итоговую структуру данных
                    task20_data = {
                        "topics": all_topics,
                        "topic_by_id": topic_by_id,
                        "topics_by_block": topics_by_block,
                        "blocks": blocks
                    }
                    
                    logger.info(f"Loaded {len(all_topics)} topics for task20")
                    logger.info(f"Blocks: {list(blocks.keys())}")

                    # Сохраняем в кэш
                    if cache:
                        await cache.set('task20_data', task20_data)
                    
                    # Создаём селектор
                    if TopicSelector and all_topics:
                        topic_selector = TopicSelector(all_topics)
                    else:
                        topic_selector = None
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse task20 topics JSON: {e}")
                    task20_data = {"topics": [], "blocks": {}, "topics_by_block": {}, "topic_by_id": {}}
                    topic_selector = None
                except Exception as e:
                    logger.error(f"Failed to load task20 data: {e}")
                    task20_data = {"topics": [], "blocks": {}, "topics_by_block": {}, "topic_by_id": {}}
                    topic_selector = None
    else:
        # Если кэш недоступен, загружаем напрямую
        logger.warning("Cache not available, loading data directly")
        data_file = os.path.join(os.path.dirname(__file__), "task20_topics.json")
        
        if not os.path.exists(data_file):
            logger.error(f"Topics file not found: {data_file}")
            task20_data = {
                "topics": [],
                "topic_by_id": {},
                "topics_by_block": {},
                "blocks": {}
            }
            topic_selector = None
        else:
            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    topics_list = json.load(f)
                
                # Та же логика обработки...
                all_topics = []
                topic_by_id = {}
                topics_by_block = {}
                blocks = {}
                
                for topic in topics_list:
                    if not isinstance(topic, dict) or 'id' not in topic or 'title' not in topic:
                        continue
                    
                    all_topics.append(topic)
                    topic_by_id[topic["id"]] = topic
                    
                    block_name = topic.get("block", "Без категории")
                    if block_name not in topics_by_block:
                        topics_by_block[block_name] = []
                        blocks[block_name] = {"topics": []}
                    
                    topics_by_block[block_name].append(topic)
                    blocks[block_name]["topics"].append(topic)
                
                task20_data = {
                    "topics": all_topics,
                    "topic_by_id": topic_by_id,
                    "topics_by_block": topics_by_block,
                    "blocks": blocks
                }
                
                if TopicSelector and all_topics:
                    topic_selector = TopicSelector(all_topics)
                
            except Exception as e:
                logger.error(f"Failed to load task20 data: {e}")
                task20_data = {"topics": [], "blocks": {}, "topics_by_block": {}, "topic_by_id": {}}
                topic_selector = None
    
    # Инициализируем AI evaluator
    # Важно: импортируем здесь, чтобы избежать циклических импортов
    from .evaluator import Task20AIEvaluator, StrictnessLevel, AI_EVALUATOR_AVAILABLE
    
    logger.info(f"AI_EVALUATOR_AVAILABLE = {AI_EVALUATOR_AVAILABLE}")
    
    if AI_EVALUATOR_AVAILABLE:
        try:
            strictness_level = StrictnessLevel[os.getenv('TASK20_STRICTNESS', 'STANDARD').upper()]
            logger.info(f"Using strictness level: {strictness_level.value}")
        except KeyError:
            strictness_level = StrictnessLevel.STANDARD
            logger.info("Using default strictness level: STANDARD")
        
        try:
            evaluator = Task20AIEvaluator(strictness=strictness_level)
            logger.info(f"Task20 AI evaluator initialized successfully with {strictness_level.value} strictness")
        except Exception as e:
            logger.error(f"Failed to initialize AI evaluator: {e}", exc_info=True)
            evaluator = None
    else:
        logger.warning("AI evaluator not available for task20 - check imports")
        evaluator = None
        
    logger.info(f"Final evaluator status: {'initialized' if evaluator else 'not initialized'}")

@safe_handler()
@validate_state_transition({ConversationHandler.END, None})
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в задание 20 из главного меню."""
    query = update.callback_query
    
    user_id = update.effective_user.id
    context.user_data['module'] = 'task20'
    
    # Получаем статистику пользователя
    if UserProgress:
        user_stats = UserProgress(context.user_data).get_stats()
    else:
        user_stats = {
            'total_attempts': 0,
            'streak': 0,
            'weak_topics_count': 0,
            'progress_percent': 0
        }
    
    # Используем персонализированное приветствие
    greeting = get_personalized_greeting(user_stats)
    is_new_user = user_stats.get('total_attempts', 0) == 0
    text = greeting + MessageFormatter.format_welcome_message("задание 20", is_new_user)
    
    # Создаем адаптивное меню
    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t20")
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def cmd_task20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task20."""
    text = (
        "📝 <b>Задание 20</b>\n\n"
        "В этом задании нужно сформулировать суждения (аргументы) "
        "абстрактного характера с элементами обобщения.\n\n"
        "⚠️ <b>Важно:</b> НЕ приводите конкретные примеры!\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t20_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t20_theory")],
        [InlineKeyboardButton("🏦 Банк суждений", callback_data="t20_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t20_progress")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="t20_settings")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def show_achievement_notification(update: Update, context: ContextTypes.DEFAULT_TYPE, achievement: Dict):
    """Показать уведомление о достижении."""
    text = f"""
🎉 <b>Новое достижение!</b>

{achievement['icon']} <b>{achievement['name']}</b>
<i>{achievement['description']}</i>

{achievement.get('reward_text', '')}
"""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("👍 Отлично!", callback_data="t20_achievement_ok")
    ]])
    
    # Отправляем как отдельное сообщение
    msg = await update.effective_message.reply_text(
        text, 
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    # Удаляем через 10 секунд
    context.job_queue.run_once(
        lambda ctx: msg.delete(),
        when=10,
        name=f"delete_achievement_{msg.message_id}"
    )


@safe_handler()
async def handle_achievement_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки OK в уведомлении о достижении."""
    query = update.callback_query
    
    try:
        await query.message.delete()
    except Exception:
        pass
    
    # Не меняем состояние conversation handler
    return None

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики с улучшенным UX."""
    query = update.callback_query
    
    # Проверяем доступность UserProgress
    if UserProgress:
        progress = UserProgress(context.user_data)
        stats = progress.get_stats()
    else:
        # Fallback, если UserProgress не доступен
        stats = {
            'total_attempts': 0,
            'average_score': 0,
            'streak': 0
        }
        progress = None
    
    text = "💪 <b>Режим практики</b>\n\n"
    
    # Показываем мини-статистику
    if stats['total_attempts'] > 0:
        avg_visual = create_visual_progress(round(stats['average_score']), 3)
        text += f"📊 Ваш прогресс: {stats['total_attempts']} попыток, средний балл {avg_visual}\n"
        
        if stats['streak'] > 0:
            text += f"🔥 Серия правильных ответов: {stats['streak']}\n"
        
        text += "\n"
    
    # Показываем подсказку, если нужно
    if progress and hasattr(progress, 'should_show_tip'):
        tip = progress.should_show_tip()
        if tip:
            text += f"{tip}\n\n"
    
    text += "Выберите способ тренировки:"
    
    kb_buttons = []
    
    # Кнопка "Продолжить с последней темы"
    if progress and progress.last_topic_id and topic_selector:
        last_topic = topic_selector.topics_by_id.get(progress.last_topic_id)
        if last_topic:
            kb_buttons.append([
                InlineKeyboardButton(
                    f"⏮️ Продолжить: {last_topic['title'][:30]}...", 
                    callback_data=f"t20_topic:{last_topic['id']}"
                )
            ])
    
    # Кнопка "Рекомендованная тема"
    if stats['total_attempts'] >= 3 and topic_selector and SmartRecommendations:
        recommended = SmartRecommendations.get_next_topic_recommendation(progress, topic_selector)
        if recommended:
            kb_buttons.append([
                InlineKeyboardButton(
                    "🎯 Рекомендуем эту тему", 
                    callback_data=f"t20_topic:{recommended['id']}"
                )
            ])
    
    # Стандартные кнопки
    kb_buttons.extend([
        [InlineKeyboardButton("📚 Выбрать блок тем", callback_data="t20_select_block")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t20_random_all")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим теории и советов."""
    query = update.callback_query
    
    text = """📚 <b>Теория по заданию 20</b>

<b>Что требуется в задании 20?</b>
Сформулировать суждения (аргументы) абстрактного характера с элементами обобщения.

<b>Ключевые отличия от задания 19:</b>
• Задание 19 - конкретные примеры
• Задание 20 - абстрактные суждения

<b>Критерии оценивания:</b>
• 3 балла - приведены 3 суждения правильного типа
• 2 балла - приведено 2 суждения
• 1 балл - приведено 1 суждение
• 0 баллов - суждения неверного типа или отсутствуют

<b>Важно:</b> Если наряду с требуемыми суждениями приведено 2 или более дополнительных суждения с ошибками, ответ оценивается в 0 баллов!

<b>Новые возможности:</b>
🔧 <b>Работа над ошибками</b> - повторите темы с низкими баллами
📈 <b>Детальная статистика</b> - графики вашего прогресса
🏅 <b>Достижения</b> - мотивация для улучшения результатов
⚙️ <b>Уровни строгости</b> - от мягкого до экспертного

Выберите раздел для изучения:"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Как писать суждения", callback_data="t20_how_to_write")],
        [InlineKeyboardButton("✅ Правильные примеры", callback_data="t20_good_examples")],
        [InlineKeyboardButton("❌ Типичные ошибки", callback_data="t20_common_mistakes")],
        [InlineKeyboardButton("🔤 Полезные конструкции", callback_data="t20_useful_phrases")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def how_to_write(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Как писать суждения."""
    query = update.callback_query
    
    text = """📝 <b>Как писать суждения для задания 20</b>

<b>1. Структура суждения:</b>
• Начните с обобщающего тезиса
• Раскройте причинно-следственную связь
• Завершите выводом или следствием

<b>2. Используйте абстрактные понятия:</b>
• "Экономические субъекты" вместо "компания Apple"
• "Развитые страны" вместо "США и Германия"
• "Современные технологии" вместо "iPhone 15"

<b>3. Применяйте обобщающие слова:</b>
• Процессы: способствует, приводит к, порождает
• Влияние: определяет, формирует, трансформирует
• Связи: обусловливает, детерминирует, коррелирует

<b>4. Избегайте:</b>
• Конкретных дат и чисел
• Названий организаций и стран
• Имён конкретных людей
• Описания единичных событий

<b>Пример правильного суждения:</b>
<i>"Развитие информационных технологий способствует глобализации экономических процессов, позволяя хозяйствующим субъектам осуществлять деятельность вне зависимости от географических границ."</i>"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE
    
# Добавьте эти функции в файл task20/handlers.py

@safe_handler()
async def search_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Инициализация поиска в банке суждений."""
    query = update.callback_query
    
    await query.edit_message_text(
        "🔍 <b>Поиск в банке суждений</b>\n\n"
        "Отправьте название темы или ключевые слова для поиска:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="t20_examples")
        ]]),
        parse_mode=ParseMode.HTML
    )
    
    context.user_data['waiting_for_bank_search'] = True
    return states.SEARCHING

@safe_handler()
async def view_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр конкретного примера суждений."""
    query = update.callback_query
    
    # Извлекаем индекс темы из callback_data
    topic_idx = int(query.data.split(":")[1])
    topics = task20_data.get('topics', [])
    
    if not topics or topic_idx >= len(topics):
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE
    
    topic = topics[topic_idx]
    context.user_data['bank_current_idx'] = topic_idx
    context.user_data['viewing_mode'] = 'single'
    
    text = f"""🏦 <b>Банк суждений - Детальный просмотр</b>

<b>Тема {topic_idx + 1}/{len(topics)}:</b> {topic['title']}
<b>Блок:</b> {topic['block']}

<b>Задание:</b>
<i>{topic['task_text']}</i>

<b>📝 Эталонные суждения:</b>
"""
    
    # Показываем суждения с подробными пояснениями
    for i, example in enumerate(topic.get('example_arguments', []), 1):
        text += f"\n<b>{i}. {example['type']}</b>\n"
        text += f"└ <i>{example['argument']}</i>\n"
        if 'explanation' in example:
            text += f"   💡 <code>{example['explanation']}</code>\n"
    
    # Кнопки навигации
    kb_buttons = []
    
    # Навигация между примерами
    nav_row = []
    if topic_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Пред.", callback_data=f"t20_prev_example"))
    nav_row.append(InlineKeyboardButton(f"{topic_idx + 1}/{len(topics)}", callback_data="noop"))
    if topic_idx < len(topics) - 1:
        nav_row.append(InlineKeyboardButton("След. ➡️", callback_data=f"t20_next_example"))
    kb_buttons.append(nav_row)
    
    # Дополнительные действия
    kb_buttons.extend([
        [InlineKeyboardButton("📋 Все примеры", callback_data=f"t20_view_all_examples:{topic['block']}")],
        [InlineKeyboardButton("🎯 Попробовать эту тему", callback_data=f"t20_topic:{topic['id']}")],
        [InlineKeyboardButton("⬅️ К банку суждений", callback_data="t20_back_examples")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.VIEWING_EXAMPLE

@safe_handler()
async def view_all_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ всех примеров по блокам."""
    query = update.callback_query
    
    # Если callback_data содержит блок (t20_all_examples:block_name)
    if ":" in query.data:
        block_name = query.data.split(":", 1)[1]
        return await show_block_examples(update, context, block_name)
    
    # Иначе показываем список блоков
    blocks = {}
    for topic in task20_data.get('topics', []):
        block = topic.get('block', 'Другое')
        if block not in blocks:
            blocks[block] = []
        blocks[block].append(topic)
    
    text = "🏦 <b>Банк суждений по блокам</b>\n\n"
    text += "Выберите блок для просмотра:\n\n"
    
    kb_buttons = []
    for block_name, topics in sorted(blocks.items()):
        kb_buttons.append([InlineKeyboardButton(
            f"📚 {block_name} ({len(topics)} тем)",
            callback_data=f"t20_all_examples:{block_name}"
        )])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_examples")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def show_block_examples(update: Update, context: ContextTypes.DEFAULT_TYPE, block_name: str):
    """Показ примеров из конкретного блока."""
    query = update.callback_query
    
    # Находим все темы блока
    block_topics = []
    for idx, topic in enumerate(task20_data.get('topics', [])):
        if topic.get('block') == block_name:
            block_topics.append((idx, topic))
    
    if not block_topics:
        await query.answer("Темы не найдены", show_alert=True)
        return states.CHOOSING_MODE
    
    text = f"📚 <b>Блок: {block_name}</b>\n\n"
    text += f"Найдено тем: {len(block_topics)}\n\n"
    
    kb_buttons = []
    for idx, topic in block_topics[:15]:  # Максимум 15 тем
        kb_buttons.append([InlineKeyboardButton(
            f"📖 {topic['title'][:50]}...",
            callback_data=f"t20_bank_nav:{idx}"
        )])
    
    if len(block_topics) > 15:
        text += f"\n<i>Показаны первые 15 из {len(block_topics)} тем</i>"
    
    kb_buttons.append([InlineKeyboardButton("⬅️ К блокам", callback_data="t20_view_all_examples")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def next_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к следующему примеру."""
    query = update.callback_query
    
    current_idx = context.user_data.get('bank_current_idx', 0)
    topics = task20_data.get('topics', [])
    
    # Увеличиваем индекс
    new_idx = min(current_idx + 1, len(topics) - 1)
    
    if new_idx == current_idx:
        await query.answer("Это последняя тема", show_alert=True)
        return states.VIEWING_EXAMPLE
    
    # Обновляем данные и показываем новый пример
    query.data = f"t20_view_example:{new_idx}"
    return await view_example(update, context)

@safe_handler()
async def prev_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к предыдущему примеру."""
    query = update.callback_query
    
    current_idx = context.user_data.get('bank_current_idx', 0)
    
    # Уменьшаем индекс
    new_idx = max(current_idx - 1, 0)
    
    if new_idx == current_idx:
        await query.answer("Это первая тема", show_alert=True)
        return states.VIEWING_EXAMPLE
    
    # Обновляем данные и показываем новый пример
    query.data = f"t20_view_example:{new_idx}"
    return await view_example(update, context)

@safe_handler()
async def back_to_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к банку примеров."""
    query = update.callback_query
    
    # Очищаем временные данные
    context.user_data.pop('viewing_mode', None)
    context.user_data.pop('bank_current_idx', None)
    
    # Возвращаемся к главному меню банка
    return await examples_bank(update, context)

@safe_handler()
async def cancel_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена сброса прогресса."""
    query = update.callback_query
    
    await query.answer("✅ Сброс отменён")
    
    # Возвращаемся в настройки
    return await settings_mode(update, context)

@safe_handler()
async def handle_unexpected_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка неожиданных текстовых сообщений."""
    
    # Проверяем, не ждем ли мы поискового запроса
    if context.user_data.get('waiting_for_bank_search'):
        return await handle_bank_search(update, context)
    
    # Определяем текущее состояние
    current_state = context.user_data.get('current_state', states.CHOOSING_MODE)
    
    # Формируем сообщение в зависимости от состояния
    if current_state == states.ANSWERING_T20:
        text = ("⚠️ Похоже, вы отправили сообщение не в том формате.\n\n"
                "Для ответа на задание 20 отправьте все три суждения одним сообщением.")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отменить", callback_data="t20_menu")
        ]])
    else:
        text = "ℹ️ Пожалуйста, используйте кнопки меню для навигации."
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 В меню задания 20", callback_data="t20_menu"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
        ]])
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return current_state

@safe_handler()
async def skip_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск текущего вопроса."""
    query = update.callback_query
    
    topic = context.user_data.get('current_topic')
    
    if not topic:
        await query.answer("Нет активного задания", show_alert=True)
        return states.CHOOSING_MODE
    
    # Сохраняем пропуск в статистику
    result = {
        'topic': topic['title'],
        'topic_id': topic['id'],
        'block': topic['block'],
        'score': 0,
        'max_score': 3,
        'skipped': True,
        'timestamp': datetime.now().isoformat()
    }
    
    if 'task20_results' not in context.user_data:
        context.user_data['task20_results'] = []
    context.user_data['task20_results'].append(result)
    
    # Показываем сообщение о пропуске
    text = (
        "⏭️ <b>Задание пропущено</b>\n\n"
        f"Тема: {topic['title']}\n\n"
        "Пропущенные задания можно выполнить позже в режиме "
        "«Работа над ошибками»."
    )
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎲 Новая тема", callback_data="t20_new"),
            InlineKeyboardButton("📊 Мой прогресс", callback_data="t20_progress")
        ],
        [InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


# Дополнительная вспомогательная функция для обработки ответов в ANSWERING_T20
async def safe_handle_answer_task20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Безопасная обработка ответа на задание 20."""
    
    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Получаем текст ответа
    user_answer = update.message.text.strip()
    
    # Проверяем минимальную длину
    if len(user_answer) < 50:
        await update.message.reply_text(
            "❌ Ответ слишком короткий. Приведите три развернутых суждения.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отменить", callback_data="t20_menu")
            ]])
        )
        return states.ANSWERING_T20
    
    # Показываем анимацию проверки
    thinking_msg = await show_thinking_animation(
        update.message,
        "Анализирую ваши суждения",
    )
    
    # Оцениваем ответ
    if evaluator and AI_EVALUATOR_AVAILABLE:
        try:
            result = await evaluator.evaluate(
                answer=user_answer,
                topic=topic['title'],  # передаем название темы
                task_text=topic.get('task_text', ''),  # передаем текст задания
                user_id=update.effective_user.id
            )
            score = result.total_score  # Исправлено: result.score → result.total_score
            feedback = result.feedback
            criteria_scores = result.criteria_scores
        except Exception as e:
            logger.error(f"Evaluation error: {e}")
            score = 2
            feedback = "Ваш ответ принят. Продолжайте практиковаться!"
            criteria_scores = {"abstractness": 1, "relevance": 1, "completeness": 0}
    else:
        # Простая оценка без AI
        score = min(3, len(user_answer) // 100)
        feedback = "Ваш ответ принят. Продолжайте практиковаться!"
        criteria_scores = {"abstractness": 1, "relevance": 1, "completeness": score - 2}
    
    # Удаляем анимацию
    await thinking_msg.delete()
    
    # Сохраняем результат
    result_data = {
        'topic': topic['title'],
        'topic_id': topic['id'],
        'block': topic['block'],
        'score': score,
        'max_score': 3,
        'timestamp': datetime.now().isoformat(),
        'user_answer': user_answer[:500]  # Сохраняем первые 500 символов
    }
    
    if 'task20_results' not in context.user_data:
        context.user_data['task20_results'] = []
    context.user_data['task20_results'].append(result_data)
    
    # Формируем ответ
    score_emoji = {0: "❌", 1: "🟡", 2: "🟢", 3: "🎯"}.get(score, "🟡")
    
    text = f"{score_emoji} <b>Ваш результат: {score}/3 балла</b>\n\n"
    text += f"<b>Обратная связь:</b>\n{feedback}\n\n"
    
    if criteria_scores:
        text += "<b>Оценка по критериям:</b>\n"
        criteria_names = {
            "abstractness": "Абстрактность",
            "relevance": "Соответствие теме",
            "completeness": "Полнота ответа"
        }
        for criterion, value in criteria_scores.items():
            name = criteria_names.get(criterion, criterion)
            emoji = "✅" if value > 0 else "❌"
            text += f"{emoji} {name}: {'+' if value > 0 else ''}{value}\n"
    
    # Кнопки действий
    kb = AdaptiveKeyboards.create_result_keyboard(
        score=score,
        max_score=3,
        module_code="t20"
    )
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE
    
@safe_handler()
async def good_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Примеры правильных суждений."""
    query = update.callback_query
    
    text = """✅ <b>Примеры правильных суждений</b>

<b>Тема: Роль образования в обществе</b>

<u>Правильно:</u>
<i>"Образование как социальный институт формирует человеческий капитал, обеспечивая передачу накопленных знаний и культурных ценностей от поколения к поколению."</i>

<b>Почему правильно:</b>
• Абстрактные понятия (система, капитал, поколения)
• Причинно-следственная связь
• Обобщающие слова (формирует, обеспечивая)

<b>Тема: Влияние конкуренции</b>

<u>Правильно:</u>
<i>"Конкурентная среда стимулирует предпринимателей к постоянному совершенствованию производственных процессов, что способствует повышению эффективности экономики в целом."</i>

<b>Почему правильно:</b>
• Нет конкретных примеров
• Есть обобщение (экономика в целом)
• Логическая связь между частями

<b>Тема: СМИ и общество</b>

<u>Правильно:</u>
<i>"Средства массовой информации выполняют функцию социального контроля, привлекая внимание общественности к нарушениям норм и злоупотреблениям, что способствует поддержанию социального порядка."</i>

<b>Почему правильно:</b>
• Указана функция, а не конкретный случай
• Абстрактное описание механизма
• Вывод о влиянии на общество"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def common_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Типичные ошибки."""
    query = update.callback_query
    
    text = """❌ <b>Типичные ошибки в задании 20</b>

<b>Ошибка 1: Конкретные примеры вместо суждений</b>

<u>Неправильно:</u>
<i>"В 2020 году компания Tesla увеличила производство электромобилей на 50%, что показывает влияние инноваций на развитие промышленности."</i>

<b>Почему неправильно:</b>
• Конкретная дата (2020 год)
• Название компании (Tesla)
• Конкретные цифры (50%)

<u>Как исправить:</u>
<i>"Внедрение инновационных технологий способствует росту производительности в промышленном секторе и модернизации производственных процессов."</i>

<b>Ошибка 2: Простое перечисление фактов</b>

<u>Неправильно:</u>
<i>"Глобализация есть. Она влияет на культуру. Культуры меняются."</i>

<b>Почему неправильно:</b>
• Нет развёрнутого суждения
• Отсутствуют причинно-следственные связи
• Слишком простые предложения

<b>Ошибка 3: Бытовые рассуждения</b>

<u>Неправильно:</u>
<i>"Все знают, что образование важно для человека, потому что без него никуда."</i>

<b>Почему неправильно:</b>
• Разговорный стиль
• Нет теоретического обоснования
• Отсутствует научная терминология

<b>Помните:</b> Суждение должно звучать как фрагмент научной статьи, а не как пример из жизни!"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def useful_phrases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полезные конструкции."""
    query = update.callback_query
    
    text = """🔤 <b>Полезные конструкции для задания 20</b>

<b>Для выражения влияния:</b>
• способствует развитию...
• приводит к формированию...
• обусловливает появление...
• детерминирует процессы...
• оказывает воздействие на...

<b>Для обобщения:</b>
• в современном обществе...
• в условиях рыночной экономики...
• в процессе социализации...
• в системе общественных отношений...
• в структуре социальных институтов...

<b>Для причинно-следственных связей:</b>
• вследствие чего...
• что позволяет...
• благодаря чему...
• в результате чего...
• это обеспечивает...

<b>Для характеристики процессов:</b>
• трансформация... происходит...
• модернизация... выражается в...
• эволюция... проявляется через...
• динамика... определяется...

<b>Для указания функций:</b>
• выполняет функцию...
• реализует задачу...
• обеспечивает условия для...
• создаёт предпосылки...

<b>Шаблон суждения:</b>
[Субъект] + [действие с обобщающим словом] + [объект], + [связка] + [следствие/результат]

<b>Пример:</b>
<i>"Социальные институты</i> (субъект) <i>формируют</i> (действие) <i>нормативную основу общества</i> (объект), <i>что обеспечивает</i> (связка) <i>стабильность социальных взаимодействий</i> (результат)."
"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К теории", callback_data="t20_theory")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def handle_theory_sections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Общий обработчик для разделов теории."""
    query = update.callback_query
    
    if query.data == "t20_how_to_write":
        return await how_to_write(update, context)
    elif query.data == "t20_good_examples":
        return await good_examples(update, context)
    elif query.data == "t20_common_mistakes":
        return await common_mistakes(update, context)
    elif query.data == "t20_useful_phrases":
        return await useful_phrases(update, context)
    
    return states.CHOOSING_MODE

@safe_handler()
async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Банк суждений - начальное меню."""
    query = update.callback_query
    
    context.user_data['bank_current_idx'] = 0
    
    text = (
        "🏦 <b>Банк суждений</b>\n\n"
        "Здесь собраны эталонные суждения по всем темам задания 20.\n\n"
        "Изучайте примеры, чтобы понять:\n"
        "• Как формулировать абстрактные суждения\n"
        "• Какие обобщающие конструкции использовать\n"
        "• Как избегать конкретных примеров\n\n"
        "Выберите способ просмотра:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Просмотр по порядку", callback_data="t20_bank_nav:0")],
        [InlineKeyboardButton("🔍 Поиск темы", callback_data="t20_bank_search")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прогресса пользователя с улучшенной визуализацией."""
    query = update.callback_query
    
    # Убираем явный вызов query.answer(), так как декоратор safe_handler уже делает это
    
    results = context.user_data.get('task20_results', [])
    
    if not results:
        text = (
            "📊 <b>Ваш прогресс</b>\n\n"
            "У вас пока нет результатов.\n"
            "Начните практику, чтобы увидеть статистику!"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💪 Начать практику", callback_data="t20_practice")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
        ])
    else:
        # Вычисляем статистику
        total_attempts = len(results)
        total_score = sum(r['score'] for r in results)
        max_possible = sum(r['max_score'] for r in results)
        avg_score = total_score / total_attempts
        perfect_scores = sum(1 for r in results if r['score'] == r['max_score'])
        
        # Визуальный прогресс
        progress_visual = create_visual_progress(total_score, max_possible)
        
        # Анализ по блокам
        block_stats = {}
        for result in results:
            block = result.get('block', 'Без категории')
            if block not in block_stats:
                block_stats[block] = {'attempts': 0, 'total_score': 0}
            block_stats[block]['attempts'] += 1
            block_stats[block]['total_score'] += result['score']
        
        text = f"""📊 <b>Ваш прогресс</b>

<b>Общая статистика:</b>
📝 Выполнено заданий: {total_attempts}
⭐ Средний балл: {avg_score:.1f}/3
🎯 Идеальных ответов: {perfect_scores} ({perfect_scores/total_attempts*100:.0f}%)
📈 Общий прогресс: {progress_visual}

<b>По блокам:</b>"""
        
        for block, stats in sorted(block_stats.items()):
            block_avg = stats['total_score'] / stats['attempts']
            text += f"\n• {block}: {block_avg:.1f}/3 ({stats['attempts']} попыток)"
        
        # Рекомендации
        if avg_score < 2:
            text += "\n\n💡 <i>Совет: изучите банк суждений для улучшения результатов</i>"
        elif avg_score >= 2.5:
            text += "\n\n🎉 <i>Отличные результаты! Продолжайте в том же духе!</i>"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Детальная статистика", callback_data="t20_detailed_progress")],
            [InlineKeyboardButton("🏅 Достижения", callback_data="t20_achievements")],
            [InlineKeyboardButton("🔧 Работа над ошибками", callback_data="t20_mistakes")],
            [InlineKeyboardButton("📥 Экспорт результатов", callback_data="t20_export")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
        ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

def _format_evaluation_result(result: EvaluationResult, topic: Dict) -> str:
    """Форматирование результата с использованием универсальных компонентов."""
    # Используем универсальный форматтер
    text = MessageFormatter.format_result_message(
        score=result.total_score,
        max_score=3,
        topic=topic['title']
    )
    
    # Добавляем детальный анализ
    text += "\n"
    for i, criterion in enumerate(result.criteria_scores, 1):
        if criterion.met:
            status = "✅"
            color = UniversalUIComponents.COLOR_INDICATORS['green']
        else:
            status = "❌"
            color = UniversalUIComponents.COLOR_INDICATORS['red']
        
        text += f"\n{color} <b>Критерий {i}:</b> {status}"
        if criterion.feedback:
            text += f"\n   └ <i>{criterion.feedback}</i>"
    
    # Общий комментарий
    if result.general_feedback:
        text += f"\n\n💬 <b>Комментарий эксперта:</b>\n<i>{result.general_feedback}</i>"
    
    return text

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def settings_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки проверки."""
    query = update.callback_query
    
    current_level = evaluator.strictness if evaluator else StrictnessLevel.STANDARD
    
    # Получаем статистику для каждого уровня
    user_id = update.effective_user.id
    stats_by_level = context.bot_data.get(f'task20_stats_by_level_{user_id}', {})
    
    text = f"""⚙️ <b>Настройки проверки</b>

<b>Текущий уровень:</b> {current_level.value}

<b>Описание уровней:</b>

🟢 <b>Мягкий</b>
• Засчитывает суждения с небольшими недочётами
• Подходит для начинающих
• Средний балл пользователей: 2.3/3

🟡 <b>Стандартный</b> (рекомендуется)
• Баланс между строгостью и справедливостью
• Соответствует реальным критериям ЕГЭ
• Средний балл пользователей: 1.8/3

🔴 <b>Строгий</b>
• Требует полного соответствия критериям
• Как на реальном экзамене
• Средний балл пользователей: 1.2/3

🔥 <b>Экспертный</b>
• Максимальная строгость
• Для тех, кто хочет гарантированно высокий балл
• Средний балл пользователей: 0.8/3"""
    
    kb_buttons = []
    for level in StrictnessLevel:
        emoji = "✅" if level == current_level else ""
        # Показываем личную статистику для уровня
        level_stats = stats_by_level.get(level.name, {})
        attempts = level_stats.get('attempts', 0)
        avg_score = level_stats.get('avg_score', 0)
        
        button_text = f"{emoji} {level.value}"
        if attempts > 0:
            button_text += f" (ваш балл: {avg_score:.1f})"
        
        kb_buttons.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"t20_set_strictness:{level.name}"
            )
        ])
    
    kb_buttons.append([InlineKeyboardButton("🔄 Сбросить прогресс", callback_data="t20_reset_progress")])
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def reset_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс прогресса - подтверждение."""
    query = update.callback_query
    
    await query.edit_message_text(
        "⚠️ <b>Подтверждение сброса</b>\n\n"
        "Вы уверены, что хотите сбросить весь прогресс по заданию 20?\n"
        "Это действие нельзя отменить!",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Да, сбросить", callback_data="t20_confirm_reset"),
                InlineKeyboardButton("❌ Отмена", callback_data="t20_settings")
            ]
        ]),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def confirm_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение сброса прогресса."""
    query = update.callback_query
    
    # Сбрасываем результаты
    context.user_data['task20_results'] = []
    
    
    return await settings_mode(update, context)


@safe_handler()
async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 20."""
    query = update.callback_query
    
    # Очищаем временные данные
    keys_to_clear = ['current_topic', 'current_block', 'bank_current_idx', 'waiting_for_bank_search']
    for key in keys_to_clear:
        context.user_data.pop(key, None)
    
    # Получаем статистику пользователя
    if UserProgress:
        user_stats = UserProgress(context.user_data).get_stats()
    else:
        user_stats = {
            'total_attempts': 0,
            'streak': 0,
            'weak_topics_count': 0,
            'progress_percent': 0
        }

    greeting = get_personalized_greeting(user_stats)
    is_new_user = user_stats.get('total_attempts', 0) == 0
    text = greeting + MessageFormatter.format_welcome_message("задание 20", is_new_user)

    kb = AdaptiveKeyboards.create_menu_keyboard(user_stats, module_code="t20")

    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )

    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE, states.CHOOSING_BLOCK, states.CHOOSING_TOPIC, ANSWERING_T20, states.ANSWERING_PARTS})
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню."""
    query = update.callback_query
    
    # Очищаем состояние пользователя
    from core.state_validator import state_validator
    if query and query.from_user:
        state_validator.clear_state(query.from_user.id)
    
    # Очищаем данные модуля
    keys_to_clear = [
        'current_topic', 'current_block', 'bank_current_idx', 
        'waiting_for_bank_search', 'task20_results', 'module',
        'active_module', 'current_module'
    ]
    for key in keys_to_clear:
        context.user_data.pop(key, None)
    
    # Отвечаем на callback
    if query:
        await query.answer()
    
    # Показываем главное меню
    try:
        await query.edit_message_text(
            "👋 Что хотите потренировать?",
            reply_markup=build_main_menu()
        )
    except Exception as e:
        # Если не удалось отредактировать, отправляем новое сообщение
        await query.message.reply_text(
            "👋 Что хотите потренировать?",
            reply_markup=build_main_menu()
        )
    
    return ConversationHandler.END

@safe_handler()
async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для неактивных кнопок."""
    query = update.callback_query
    await query.answer()
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока тем."""
    query = update.callback_query
    
    # Получаем реальные блоки из загруженных данных
    blocks_data = task20_data.get("topics_by_block", {})
    
    if not blocks_data:
        await query.edit_message_text(
            "❌ Данные о темах не загружены.\n\n"
            "Попробуйте перезапустить бота или обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    text = "📚 <b>Выберите блок тем:</b>"
    
    # Маппинг блоков на эмодзи
    block_emojis = {
        "Человек и общество": "🧠",
        "Экономика": "💰",
        "Социальные отношения": "👥",
        "Политика": "🏛️",
        "Право": "⚖️"
    }
    
    # Порядок блоков
    block_order = ["Человек и общество", "Экономика", "Социальные отношения", "Политика", "Право"]
    
    kb_buttons = []
    for block_name in block_order:
        if block_name in blocks_data:
            topics = blocks_data[block_name]
            emoji = block_emojis.get(block_name, "📚")
            kb_buttons.append([
                InlineKeyboardButton(
                    f"{emoji} {block_name} ({len(topics)} тем)",
                    callback_data=f"t20_block:{block_name}"
                )
            ])
    
    # Добавляем блоки, которых нет в block_order (на всякий случай)
    for block_name, topics in blocks_data.items():
        if block_name not in block_order and topics:
            kb_buttons.append([
                InlineKeyboardButton(
                    f"📚 {block_name} ({len(topics)} тем)",
                    callback_data=f"t20_block:{block_name}"
                )
            ])
    
    if not kb_buttons:
        kb_buttons.append([InlineKeyboardButton("❌ Нет доступных тем", callback_data="noop")])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

def _build_topic_message(topic: Dict) -> str:
    """Формирует текст сообщения с заданием по теме."""
    return (
        "📝 <b>Задание 20</b>\n\n"
        f"<b>Тема:</b> {topic['title']}\n"
        f"<b>Блок:</b> {topic['block']}\n\n"
        f"<b>Задание:</b> {topic['task_text']}\n\n"
        "<b>Требования:</b>\n"
        "• Приведите три суждения\n"
        "• Каждое суждение должно быть абстрактным\n"
        "• НЕ используйте конкретные примеры\n"
        "• Используйте обобщающие конструкции\n\n"
        "💡 <i>Отправьте ваш ответ одним сообщением</i>"
    )

@safe_handler()
async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после получения результата."""
    query = update.callback_query
    
    action = query.data.replace("t20_", "")
    
    if action == 'retry':
        # Повторить ту же тему
        topic = context.user_data.get('current_topic')
        if topic:
            text = _build_topic_message(topic)
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML
            )
            return ANSWERING_T20
    elif action == 'new':  # Обработка новой темы
        return await handle_new_task(update, context)
    elif action == 'menu':
        return await return_to_menu(update, context)
    elif action == 'progress':
        return await my_progress(update, context)
    
    return states.CHOOSING_MODE


@safe_handler()
async def block_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбранного блока."""
    query = update.callback_query
    
    block_name = query.data.split(":", 1)[1]
    context.user_data['current_block'] = block_name  # Важно!
    
    topics = task20_data["topics_by_block"].get(block_name, [])
    
    text = f"📚 <b>Блок: {block_name}</b>\n\n"
    text += f"Доступно тем: {len(topics)}\n\n"
    text += "Выберите действие:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Список тем", callback_data="t20_list_topics")],
        [InlineKeyboardButton("🎲 Случайная тема", callback_data="t20_random_block")],
        [InlineKeyboardButton("⬅️ К блокам", callback_data="t20_select_block")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({ANSWERING_T20})
async def handle_answer_document_task20(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка суждений из документа для task20."""
    
    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text("❌ Ошибка: тема не выбрана.")
        return states.CHOOSING_MODE
    
    extracted_text = await DocumentHandlerMixin.handle_document_answer(
        update, 
        context,
        task_name="суждения"
    )
    
    if not extracted_text:
        return ANSWERING_T20
    
    # Передаем в обычный обработчик
    update.message.text = extracted_text
    return await handle_answer(update, context)

@safe_handler()
async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка тем в блоке с пагинацией."""
    query = update.callback_query
    
    # Извлекаем номер страницы из callback_data
    parts = query.data.split(":page:")
    page = int(parts[1]) if len(parts) > 1 else 0
    
    block_name = context.user_data.get('current_block')
    if not block_name:
        await query.edit_message_text(
            "❌ Блок не выбран",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_select_block")
            ]])
        )
        return states.CHOOSING_MODE  # ✅ Правильно
    
    topics = task20_data["topics_by_block"].get(block_name, [])
    
    # Пагинация: 5 тем на страницу
    topics_per_page = 5
    total_pages = (len(topics) + topics_per_page - 1) // topics_per_page
    start_idx = page * topics_per_page
    end_idx = min(start_idx + topics_per_page, len(topics))
    
    text = f"📚 <b>{block_name}</b>\n"
    text += f"Выберите тему (стр. {page + 1} из {total_pages}):\n\n"
    
    kb_buttons = []
    
    # Кнопки с темами
    for topic in topics[start_idx:end_idx]:
        kb_buttons.append([
            InlineKeyboardButton(
                f"{topic['id']}. {topic['title']}",
                callback_data=f"t20_topic:{topic['id']}"
            )
        ])
    
    # Навигация по страницам (только если больше 1 страницы)
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"t20_list_topics:page:{page-1}"))
        nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"t20_list_topics:page:{page+1}"))
        
        kb_buttons.append(nav_buttons)
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"t20_block:{block_name}")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

@safe_handler()
async def select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора конкретной темы."""
    query = update.callback_query
    
    topic_id = query.data.split(":")[1]
    topic = task20_data["topic_by_id"].get(topic_id)
    
    if not topic:
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    text = _build_topic_message(topic)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="t20_list_topics")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING_T20

@safe_handler()
async def random_topic_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор случайной темы из всей базы."""
    query = update.callback_query
    
    # Проверяем наличие данных
    if not task20_data.get("topics"):
        await query.edit_message_text(
            "❌ Данные не загружены. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Если есть topic_selector, используем его
    if topic_selector:
        done_topics = {r['topic_id'] for r in context.user_data.get('task20_results', [])}
        topic = topic_selector.get_random_topic(exclude_ids=done_topics)
    else:
        # Fallback - простой random.choice
        import random
        topics = task20_data.get("topics", [])
        topic = random.choice(topics) if topics else None
    
    if not topic:
        await query.edit_message_text(
            "🎉 Поздравляем! Вы изучили все темы!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    text = _build_topic_message(topic)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="t20_practice")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return ANSWERING_T20

@safe_handler()
async def random_topic_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор случайной темы из блока."""
    query = update.callback_query
    
    import random
    
    block_name = context.user_data.get('current_block')  # Используем current_block
    if not block_name:
        await query.answer("Блок не выбран", show_alert=True)
        return states.CHOOSING_MODE
    
    topics = task20_data["topics_by_block"].get(block_name, [])
    if not topics:
        await query.answer("В блоке нет тем", show_alert=True)
        return states.CHOOSING_MODE
    
    topic = random.choice(topics)
    context.user_data['current_topic'] = topic
    
    text = _build_topic_message(topic)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=f"t20_block:{block_name}")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING_T20  # Важно: возвращаем правильное состояние


@safe_handler()
async def bank_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по банку суждений."""
    query = update.callback_query
    
    # Извлекаем индекс из callback_data
    topic_idx = int(query.data.split(":")[1])
    topics = task20_data.get('topics', [])
    
    if not topics or topic_idx >= len(topics) or topic_idx < 0:
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE
    
    # Проверяем, изменился ли индекс
    current_idx = context.user_data.get('bank_current_idx', -1)
    if current_idx == topic_idx:
        # Если индекс не изменился, просто отвечаем на callback
        if topic_idx == 0:
            await query.answer("Это первая тема", show_alert=False)
        elif topic_idx == len(topics) - 1:
            await query.answer("Это последняя тема", show_alert=False)
        else:
            await query.answer()
        return states.CHOOSING_MODE
    
    # Сохраняем новый индекс
    context.user_data['bank_current_idx'] = topic_idx
    
    topic = topics[topic_idx]
    
    text = f"""🏦 <b>Банк суждений</b>

<b>Тема {topic_idx + 1}/{len(topics)}:</b> {topic['title']}
<b>Блок:</b> {topic['block']}

<b>Задание:</b>
<i>{topic['task_text']}</i>

<b>📝 Эталонные суждения:</b>

"""
    
    # Показываем суждения
    for i, example in enumerate(topic.get('example_arguments', []), 1):
        text += f"<b>{i}. {example['type']}</b>\n"
        text += f"└ <i>{example['argument']}</i>\n\n"
    
    text += "💡 <b>Обратите внимание:</b>\n"
    text += "• Суждения носят абстрактный характер\n"
    text += "• Используются обобщающие слова\n"
    text += "• Нет конкретных примеров и дат"
    
    # Навигация
    kb_buttons = []
    nav_row = []
    
    # Кнопка "Назад" - только если не первая тема
    if topic_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"t20_bank_nav:{topic_idx-1}"))
    else:
        nav_row.append(InlineKeyboardButton("⏮️", callback_data="noop"))  # Неактивная кнопка
    
    # Прогресс
    progress_display = create_visual_progress(topic_idx + 1, len(topics))
    nav_row.append(InlineKeyboardButton(progress_display, callback_data="noop"))
    
    # Кнопка "Вперед" - только если не последняя тема  
    if topic_idx < len(topics) - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"t20_bank_nav:{topic_idx+1}"))
    else:
        nav_row.append(InlineKeyboardButton("⏭️", callback_data="noop"))  # Неактивная кнопка
    
    kb_buttons.append(nav_row)
    kb_buttons.append([InlineKeyboardButton("🔍 Поиск темы", callback_data="t20_bank_search")])
    kb_buttons.append([InlineKeyboardButton("📋 Все темы", callback_data="t20_view_all_examples")])
    kb_buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")])
    
    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(kb_buttons),
            parse_mode=ParseMode.HTML
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            # Если сообщение не изменилось, просто отвечаем на callback
            await query.answer()
        else:
            raise
    
    return states.CHOOSING_MODE

@safe_handler()
async def bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск темы в банке суждений."""
    query = update.callback_query
    
    await query.edit_message_text(
        "🔍 <b>Поиск в банке суждений</b>\n\n"
        "Отправьте название темы или ключевые слова для поиска:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="t20_examples")
        ]]),
        parse_mode=ParseMode.HTML
    )
    
    context.user_data['waiting_for_bank_search'] = True
    return states.SEARCHING

@safe_handler()
async def strictness_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбора уровня строгости."""
    query = update.callback_query
    
    current_level = evaluator.strictness.name if evaluator else "STANDARD"
    
    text = (
        "🎯 <b>Уровень строгости проверки</b>\n\n"
        "Выберите, насколько строго проверять ваши ответы:\n\n"
        "🟢 <b>Мягкий</b> - засчитываются частично правильные ответы\n"
        "🟡 <b>Стандартный</b> - обычные критерии ЕГЭ\n"
        "🔴 <b>Строгий</b> - требуется точное соответствие критериям"
    )
    
    buttons = []
    levels = [
        ("LENIENT", "🟢 Мягкий"),
        ("STANDARD", "🟡 Стандартный"),
        ("STRICT", "🔴 Строгий")
    ]
    
    for level_code, level_name in levels:
        check = "✅ " if level_code == current_level else ""
        buttons.append([InlineKeyboardButton(
            f"{check}{level_name}",
            callback_data=f"t20_strictness:{level_code}"
        )])
    
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_settings")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def set_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка уровня строгости."""
    global evaluator
    
    query = update.callback_query
    level_str = query.data.split(":")[1].upper()
    
    try:
        new_level = StrictnessLevel[level_str]
        
        # Пересоздаем evaluator с новым уровнем
        from .evaluator import Task20AIEvaluator, AI_EVALUATOR_AVAILABLE
        
        if AI_EVALUATOR_AVAILABLE:
            evaluator = Task20AIEvaluator(strictness=new_level)
            logger.info(f"Task20 strictness changed to {new_level.value}")
            
            # Сохраняем статистику по уровню
            await save_stats_by_level(context, query.from_user.id, 0)
            
            await query.answer(f"✅ Установлен уровень: {new_level.value}")
        else:
            await query.answer("⚠️ AI проверка недоступна", show_alert=True)
            
        # Возвращаемся в настройки
        return await settings_mode(update, context)
        
    except Exception as e:
        logger.error(f"Error setting strictness: {e}")
        await query.answer("❌ Ошибка при изменении настроек", show_alert=True)
        return states.CHOOSING_MODE


@safe_handler()
async def handle_settings_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик действий в настройках."""
    query = update.callback_query
    
    if query.data == "t20_reset_progress":
        return await reset_progress(update, context)
    elif query.data == "t20_confirm_reset":
        return await confirm_reset(update, context)
    
    return states.CHOOSING_MODE

@safe_handler()
async def detailed_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная статистика по темам."""
    query = update.callback_query
    
    results = context.user_data.get('task20_results', [])
    
    if len(results) < 5:
        await query.edit_message_text(
            "📊 <b>Детальная статистика</b>\n\n"
            "Для отображения детальной статистики необходимо выполнить минимум 5 заданий.\n\n"
            f"Сейчас выполнено: {len(results)} из 5\n\n"
            "Продолжайте практику, чтобы увидеть подробный анализ!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💪 Продолжить практику", callback_data="t20_practice")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")]
            ]),
            parse_mode=ParseMode.HTML
        )
        return states.CHOOSING_MODE
    
    # Группируем результаты по темам
    topic_stats = {}
    for result in results:
        topic = result.get('topic', 'Неизвестная тема')
        if topic not in topic_stats:
            topic_stats[topic] = {
                'attempts': 0,
                'total_score': 0,
                'scores': []
            }
        topic_stats[topic]['attempts'] += 1
        topic_stats[topic]['total_score'] += result['score']
        topic_stats[topic]['scores'].append(result['score'])
    
    # Сортируем темы по среднему баллу (от худших к лучшим)
    sorted_topics = sorted(
        topic_stats.items(),
        key=lambda x: x[1]['total_score'] / x[1]['attempts']
    )
    
    text = "📈 <b>Детальная статистика по темам</b>\n\n"
    
    # Показываем топ-5 худших тем для работы
    text += "🔴 <b>Темы, требующие внимания:</b>\n"
    for i, (topic, stats) in enumerate(sorted_topics[:5], 1):
        avg_score = stats['total_score'] / stats['attempts']
        text += f"{i}. {topic}: {avg_score:.1f}/3 ({stats['attempts']} попыток)\n"
    
    # Показываем топ-5 лучших тем
    if len(sorted_topics) > 5:
        text += "\n🟢 <b>Ваши сильные темы:</b>\n"
        for i, (topic, stats) in enumerate(reversed(sorted_topics[-5:]), 1):
            avg_score = stats['total_score'] / stats['attempts']
            text += f"{i}. {topic}: {avg_score:.1f}/3 ({stats['attempts']} попыток)\n"
    
    # Общие рекомендации
    weak_topics = [t for t, s in sorted_topics if s['total_score']/s['attempts'] < 2]
    if weak_topics:
        text += f"\n💡 <i>Рекомендуем поработать над {len(weak_topics)} темами с низкими баллами</i>"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔧 Работа над ошибками", callback_data="t20_mistakes")],
        [InlineKeyboardButton("📥 Экспорт в CSV", callback_data="t20_export")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def achievements_check(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Проверка и выдача достижений."""
    results = context.user_data.get('task20_results', [])
    achievements = context.user_data.get('task20_achievements', set())
    new_achievements = []
    
    # Определяем достижения
    achievement_conditions = {
        'first_perfect': {
            'name': '🌟 Первый идеал',
            'desc': 'Получить первый максимальный балл',
            'check': lambda r: any(res['score'] == 3 for res in r)
        },
        'consistency_5': {
            'name': '🎯 Стабильность',
            'desc': 'Получить 3 балла 5 раз подряд',
            'check': lambda r: any(all(r[i:i+5]) for i in range(len(r)-4) if all(res['score'] == 3 for res in r[i:i+5]))
        },
        'explorer_10': {
            'name': '🗺️ Исследователь',
            'desc': 'Изучить 10 разных тем',
            'check': lambda r: len(set(res['topic_id'] for res in r)) >= 10
        },
        'persistent_20': {
            'name': '💪 Упорство',
            'desc': 'Выполнить 20 заданий',
            'check': lambda r: len(r) >= 20
        },
        'master_50': {
            'name': '🏆 Мастер',
            'desc': 'Выполнить 50 заданий со средним баллом выше 2.5',
            'check': lambda r: len(r) >= 50 and sum(res['score'] for res in r) / len(r) >= 2.5
        },
        'comeback': {
            'name': '🔥 Возвращение',
            'desc': 'Получить 3 балла после 3+ неудачных попыток',
            'check': lambda r: any(
                r[i]['score'] == 3 and all(r[j]['score'] < 2 for j in range(max(0, i-3), i))
                for i in range(3, len(r))
            )
        }
    }
    
    # Проверяем каждое достижение
    for ach_id, ach_data in achievement_conditions.items():
        if ach_id not in achievements and ach_data['check'](results):
            achievements.add(ach_id)
            new_achievements.append(ach_data)
    
    # Сохраняем достижения
    context.user_data['task20_achievements'] = achievements
    
    return new_achievements

@safe_handler()
async def show_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все достижения."""
    query = update.callback_query
    
    achievements = context.user_data.get('task20_achievements', set())
    
    all_achievements = {
        'first_perfect': ('🌟 Первый идеал', 'Получить первый максимальный балл'),
        'consistency_5': ('🎯 Стабильность', 'Получить 3 балла 5 раз подряд'),
        'explorer_10': ('🗺️ Исследователь', 'Изучить 10 разных тем'),
        'persistent_20': ('💪 Упорство', 'Выполнить 20 заданий'),
        'master_50': ('🏆 Мастер', 'Выполнить 50 заданий со средним баллом выше 2.5'),
        'comeback': ('🔥 Возвращение', 'Получить 3 балла после 3+ неудачных попыток')
    }
    
    text = "🏅 <b>Ваши достижения</b>\n\n"
    
    # Полученные достижения
    if achievements:
        text += "<b>Получено:</b>\n"
        for ach_id in achievements:
            if ach_id in all_achievements:
                name, desc = all_achievements[ach_id]
                text += f"{name} - {desc}\n"
        text += "\n"
    
    # Доступные достижения
    not_achieved = set(all_achievements.keys()) - achievements
    if not_achieved:
        text += "<b>Доступно:</b>\n"
        for ach_id in not_achieved:
            name, desc = all_achievements[ach_id]
            text += f"❓ {name[2:]} - {desc}\n"
    
    # Прогресс
    progress_display = create_visual_progress(len(achievements), len(all_achievements))
    text += f"\n<b>Прогресс:</b> {progress_display}"
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def mistakes_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим работы над ошибками."""
    query = update.callback_query
    
    # Находим темы с низкими баллами
    results = context.user_data.get('task20_results', [])
    weak_topics = {}
    
    for result in results:
        if result['score'] < 2:  # Меньше 2 баллов
            topic_id = result.get('topic_id', result.get('topic', 'unknown'))
            if topic_id not in weak_topics:
                weak_topics[topic_id] = {
                    'topic': result['topic'],
                    'attempts': 0,
                    'avg_score': 0,
                    'total_score': 0
                }
            weak_topics[topic_id]['attempts'] += 1
            weak_topics[topic_id]['total_score'] += result['score']
    
    # Вычисляем средние баллы
    for topic_id in weak_topics:
        topic_data = weak_topics[topic_id]
        topic_data['avg_score'] = topic_data['total_score'] / topic_data['attempts']
    
    if not weak_topics:
        text = "🎉 Отлично! У вас нет тем, требующих дополнительной практики!"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")
        ]])
    else:
        text = "🔧 <b>Работа над ошибками</b>\n\n"
        text += "Темы, требующие внимания:\n\n"
        
        # Сортируем по среднему баллу
        sorted_topics = sorted(weak_topics.items(), key=lambda x: x[1]['avg_score'])
        
        kb_buttons = []
        for topic_id, data in sorted_topics[:5]:  # Показываем топ-5
            score_visual = "🔴" if data['avg_score'] < 1 else "🟡"
            kb_buttons.append([InlineKeyboardButton(
                f"{score_visual} {data['topic'][:40]}... ({data['avg_score']:.1f})",
                callback_data=f"t20_topic:{topic_id}"
            )])
        
        kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")])
        kb = InlineKeyboardMarkup(kb_buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def handle_topic_choice_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обертка для обработки выбора темы."""
    return await choose_topic(update, context)

@safe_handler()
async def handle_new_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора новой темы."""
    # Используем случайную тему
    return await random_topic_all(update, context)

@safe_handler()
async def export_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт результатов в CSV."""
    query = update.callback_query
    user_id = query.from_user.id
    
    results = context.user_data.get('task20_results', [])
    
    if not results:
        await query.answer("Нет результатов для экспорта", show_alert=True)
        return states.CHOOSING_MODE
    
    # Создаем CSV
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')  # Используем ; для лучшей совместимости с Excel
    
    # Добавляем заголовок с BOM для корректного отображения в Excel
    writer.writerow(["Дата", "Тема", "Блок", "Балл", "Макс.балл", "Процент"])
    
    for result in results:
        timestamp = result.get('timestamp', '')
        topic = result.get('topic', '')
        block = result.get('block', '')
        score = result.get('score', 0)
        max_score = result.get('max_score', 3)
        percentage = f"{(score/max_score*100):.0f}%" if max_score > 0 else "0%"
        
        writer.writerow([timestamp, topic, block, score, max_score, percentage])
    
    # Добавляем итоговую строку
    total_score = sum(r.get('score', 0) for r in results)
    total_max = sum(r.get('max_score', 3) for r in results)
    avg_percentage = f"{(total_score/total_max*100):.0f}%" if total_max > 0 else "0%"
    
    writer.writerow([])
    writer.writerow(["ИТОГО", "", "", total_score, total_max, avg_percentage])
    
    # Отправляем файл с правильной кодировкой
    output.seek(0)
    # Используем utf-8-sig для добавления BOM, чтобы Excel корректно определил кодировку
    await query.message.reply_document(
        document=io.BytesIO(output.getvalue().encode('utf-8-sig')),
        filename=f"task20_results_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        caption="📊 Ваши результаты по заданию 20\n\nФайл можно открыть в Excel или Google Sheets"
    )
    
    await query.answer("✅ Файл успешно создан!")
    
    return states.CHOOSING_MODE

@safe_handler()
async def practice_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика практики."""
    query = update.callback_query
    
    results = context.user_data.get('task20_results', [])
    
    if not results:
        text = "📊 У вас пока нет статистики практики"
    else:
        total = len(results)
        avg_score = sum(r['score'] for r in results) / total
        perfect = sum(1 for r in results if r['score'] == 3)
        
        text = f"""📊 <b>Статистика практики</b>

📝 Всего попыток: {total}
⭐ Средний балл: {avg_score:.1f}/3
🎯 Идеальных ответов: {perfect} ({perfect/total*100:.0f}%)

💡 Совет: регулярная практика - ключ к успеху!"""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
async def choose_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы из списка."""
    query = update.callback_query
    
    topic_id = query.data.split(":")[1]
    topic = task20_data["topic_by_id"].get(topic_id)
    
    if not topic:
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    text = _build_topic_message(topic)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="t20_list_topics")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return ANSWERING_T20

async def save_stats_by_level(context: ContextTypes.DEFAULT_TYPE, user_id: int, score: int):
    """Сохранение статистики по уровням строгости."""
    if not evaluator:
        return
    
    current_level = evaluator.strictness.name
    stats_key = f'task20_stats_by_level_{user_id}'
    
    if stats_key not in context.bot_data:
        context.bot_data[stats_key] = {}
    
    if current_level not in context.bot_data[stats_key]:
        context.bot_data[stats_key][current_level] = {
            'attempts': 0,
            'total_score': 0,
            'avg_score': 0
        }
    
    stats = context.bot_data[stats_key][current_level]
    stats['attempts'] += 1
    stats['total_score'] += score
    stats['avg_score'] = stats['total_score'] / stats['attempts']

@safe_handler()
@validate_state_transition({ANSWERING_T20})
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await safe_handle_answer_task20(update, context)

@safe_handler()
async def handle_bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстового поиска в банке суждений."""
    if not context.user_data.get('waiting_for_bank_search'):
        return states.CHOOSING_MODE
        
    search_query = update.message.text.lower()
    topics = task20_data.get('topics', [])
    
    # Ищем темы по вхождению текста
    found_topics = []
    for idx, topic in enumerate(topics):
        if (search_query in topic['title'].lower() or 
            search_query in topic.get('keywords', '').lower() or
            search_query in topic['task_text'].lower()):
            found_topics.append((idx, topic))
    
    if not found_topics:
        text = "❌ По вашему запросу ничего не найдено.\n\nПопробуйте другие ключевые слова."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Искать снова", callback_data="t20_bank_search")],
            [InlineKeyboardButton("⬅️ К банку", callback_data="t20_examples")]
        ])
    else:
        text = f"🔍 <b>Результаты поиска</b>\n\nНайдено тем: {len(found_topics)}\n\n"
        kb_buttons = []
        
        for idx, topic in found_topics[:10]:  # Показываем максимум 10
            kb_buttons.append([InlineKeyboardButton(
                f"📖 {topic['title'][:50]}...",
                callback_data=f"t20_bank_nav:{idx}"
            )])
        
        if len(found_topics) > 10:
            text += f"\n<i>Показаны первые 10 из {len(found_topics)} результатов</i>"
        
        kb_buttons.append([InlineKeyboardButton("⬅️ К банку", callback_data="t20_examples")])
        kb = InlineKeyboardMarkup(kb_buttons)
    
    # Очищаем флаг поиска
    context.user_data['waiting_for_bank_search'] = False
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    await update.message.reply_text(
        "Действие отменено.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 В меню задания 20", callback_data="t20_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ])
    )
    return ConversationHandler.END