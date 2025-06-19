# Начало файла task20/handlers.py
import logging
import os
import csv
import io
import json
from typing import Optional, Dict, List
from datetime import datetime
from core.document_processor import DocumentHandlerMixin
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from core import states

logger = logging.getLogger(__name__)

# Глобальные переменные (БЕЗ типизации)
task20_data = {}
evaluator = None
topic_selector = None

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

try:
    from .ui_components import UIComponents, EnhancedKeyboards
except ImportError as e:
    logger.error(f"Failed to import ui_components: {e}")
    UIComponents = None
    EnhancedKeyboards = None

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
                        topic_by_id[topic["id"]] = topic
                        
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

async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в задание 20 из главного меню."""
    query = update.callback_query
    await query.answer()
    
    # Проверяем достижения
    user_id = update.effective_user.id
    new_achievements = await achievements_check(context, user_id)
    
    text = (
        "📝 <b>Задание 20</b>\n\n"
        "В этом задании нужно сформулировать суждения (аргументы) "
        "абстрактного характера с элементами обобщения.\n\n"
        "⚠️ <b>Важно:</b> НЕ приводите конкретные примеры!\n\n"
    )
    
    # Показываем новые достижения
    if new_achievements:
        text += "🎉 <b>Новые достижения:</b>\n"
        for ach in new_achievements:
            text += f"{ach['name']} - {ach['desc']}\n"
        text += "\n"
    
    text += "Выберите режим работы:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t20_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t20_theory")],
        [InlineKeyboardButton("🏦 Банк суждений", callback_data="t20_examples")],
        [InlineKeyboardButton("🔧 Работа над ошибками", callback_data="t20_mistakes")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t20_progress")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="t20_settings")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
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

async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики с улучшенным UX."""
    query = update.callback_query
    await query.answer()
    
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
        text += f"📊 Ваш прогресс: {stats['total_attempts']} попыток, средний балл {stats['average_score']:.1f}/3\n"
        
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

async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим теории и советов."""
    query = update.callback_query
    await query.answer()
    
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
    await query.answer()
    
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
    
async def good_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Примеры правильных суждений."""
    query = update.callback_query
    await query.answer()
    
    text = """✅ <b>Примеры правильных суждений</b>

<b>Тема: Роль образования</b>

<u>Правильно:</u>
<i>"Система образования формирует человеческий капитал общества, обеспечивая передачу накопленных знаний и навыков новым поколениям, что является необходимым условием социально-экономического развития."</i>

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
    await query.answer()
    
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
    await query.answer()
    
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

async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Банк суждений - начальное меню."""
    query = update.callback_query
    await query.answer()
    
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

async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Улучшенный показ прогресса."""
    query = update.callback_query
    await query.answer()
    
    results = context.user_data.get('task20_results', [])
    achievements = context.user_data.get('task20_achievements', set())
    
    if not results:
        # Красивое сообщение для новичков
        text = """📊 <b>Ваш прогресс</b>

🌟 Добро пожаловать в задание 20!

Здесь вы научитесь формулировать абстрактные суждения с элементами обобщения.

<b>Что вас ждёт:</b>
• 📚 45+ тем для изучения
• 🎯 Персональные рекомендации
• 🏅 Система достижений
• 📈 Детальная статистика

Готовы начать? Выберите "Практика" в меню!"""
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💪 Начать практику", callback_data="t20_practice")],
            [InlineKeyboardButton("📚 Сначала теорию", callback_data="t20_theory")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
        ])
    else:
        # Детальная статистика для опытных
        total_attempts = len(results)
        scores = [r['score'] for r in results]
        average_score = sum(scores) / len(scores)
        unique_topics = len(set(r['topic_id'] for r in results))
        
        # Визуальные элементы
        if UIComponents:
            progress_bar = UIComponents.create_progress_bar(unique_topics, 45)  # Предполагаем 45 тем
            trend_indicator = UIComponents.create_trend_indicator(trend)
            time_formatted = UIComponents.format_time_spent(total_time)
        else:
            # Fallback версии без UIComponents
            progress_percent = int(unique_topics / 45 * 100)
            progress_bar = f"{progress_percent}% ({unique_topics}/45)"
            trend_indicator = "📈 Растёт" if trend == 'up' else "➡️ Стабильно"
            hours = total_time // 60
            mins = total_time % 60
            time_formatted = f"{hours}ч {mins}мин" if hours > 0 else f"{total_time} мин"
        
        # Подсчёт времени
        total_time = UserProgress(context.user_data).get_stats()['total_time']
        time_formatted = UIComponents.format_time_spent(total_time)
        
        text = f"""📊 <b>Ваш прогресс по заданию 20</b>

<b>📈 Общая статистика:</b>
├ 📝 Выполнено заданий: {total_attempts}
├ ⭐ Средний балл: {average_score:.2f}/3
├ 📚 Изучено тем: {unique_topics}/45
├ ⏱️ Время практики: {time_formatted}
└ 📊 Тренд: {trend_indicator}

<b>🎯 Прогресс по темам:</b>
{progress_bar}

<b>🏆 Лучшие результаты:</b>"""
        
        # Топ-3 темы
        topic_scores = {}
        for result in results:
            topic_id = result['topic_id']
            if topic_id not in topic_scores or result['score'] > topic_scores[topic_id]['score']:
                topic_scores[topic_id] = {
                    'title': result['topic_title'],
                    'score': result['score']
                }
        
        top_topics = sorted(topic_scores.values(), key=lambda x: x['score'], reverse=True)[:3]
        for i, topic in enumerate(top_topics, 1):
            score_visual = UIComponents.create_score_visual(topic['score'])
            text += f"\n{i}. {topic['title'][:30]}... {score_visual}"
        
        # Достижения
        if achievements:
            text += f"\n\n🏅 <b>Получено достижений:</b> {len(achievements)}"
        
        # Персональные рекомендации
        if average_score < 2:
            text += "\n\n💡 <b>Рекомендация:</b> Изучите раздел 'Полезные конструкции' в теории"
        elif unique_topics < 10:
            text += "\n\n💡 <b>Рекомендация:</b> Попробуйте темы из разных блоков"
        else:
            text += "\n\n🌟 <b>Отличная работа!</b> Продолжайте в том же духе!"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Детальная статистика", callback_data="t20_detailed_progress")],
            [InlineKeyboardButton("🏅 Достижения", callback_data="t20_achievements")],
            [InlineKeyboardButton("📤 Экспорт результатов", callback_data="t20_export")],
            [InlineKeyboardButton("🔧 Работа над ошибками", callback_data="t20_mistakes")],
            [InlineKeyboardButton("💪 Продолжить практику", callback_data="t20_practice")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
        ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def format_result_message(result: Dict, topic: Dict) -> str:
    """Красивое форматирование результата проверки."""
    if UIComponents:
        score_visual = UIComponents.create_score_visual(topic['score'])
    else:
        score_visual = f"{topic['score']}/3"
    score_visual = UIComponents.create_score_visual(result.total_score)
    
    # Заголовок в зависимости от результата
    if result.total_score == 3:
        header = "🎉 <b>Отличный результат!</b>"
        emoji = "🌟"
    elif result.total_score == 2:
        header = "👍 <b>Хороший результат!</b>"
        emoji = "✅"
    elif result.total_score == 1:
        header = "📝 <b>Есть над чем поработать</b>"
        emoji = "💡"
    else:
        header = "❌ <b>Нужно больше практики</b>"
        emoji = "📚"
    
    text = f"""{header}

<b>Тема:</b> {topic['title']}
<b>Результат:</b> {score_visual} ({result.total_score}/3 балла)

{emoji} <b>Детальный анализ:</b>
"""
    
    # Красивое форматирование критериев
    for i, criterion in enumerate(result.criteria_scores, 1):
        if criterion.met:
            status = "✅"
            color = "🟢"
        else:
            status = "❌"
            color = "🔴"
        
        text += f"\n{color} <b>Критерий {i}:</b> {status}"
        if criterion.feedback:
            text += f"\n   └ <i>{criterion.feedback}</i>"
    
    # Общий комментарий
    if result.general_feedback:
        text += f"\n\n💬 <b>Комментарий эксперта:</b>\n<i>{result.general_feedback}</i>"
    
    # Рекомендации в зависимости от оценки
    if result.total_score < 3:
        text += "\n\n💡 <b>Совет:</b> "
        if result.total_score == 0:
            text += "Изучите примеры в 'Банке суждений' для этой темы"
        elif result.total_score == 1:
            text += "Обратите внимание на использование обобщающих конструкций"
        else:
            text += "Проверьте, все ли суждения носят абстрактный характер"
    
    return text

async def settings_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки проверки."""
    query = update.callback_query
    await query.answer()
    
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

async def reset_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс прогресса - подтверждение."""
    query = update.callback_query
    await query.answer()
    
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

async def confirm_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение сброса прогресса."""
    query = update.callback_query
    await query.answer()
    
    # Сбрасываем результаты
    context.user_data['task20_results'] = []
    
    await query.answer("✅ Прогресс сброшен", show_alert=True)
    return await settings_mode(update, context)


async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 20."""
    query = update.callback_query
    await query.answer()
    
    # Очищаем временные данные
    keys_to_clear = ['current_topic', 'current_block', 'bank_current_idx', 'waiting_for_bank_search']
    for key in keys_to_clear:
        context.user_data.pop(key, None)
    
    return await entry_from_menu(update, context)

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню."""
    from core.plugin_loader import build_main_menu
    
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

async def select_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор блока тем."""
    query = update.callback_query
    await query.answer()
    
    blocks = list(task20_data.get("blocks", {}).keys())
    
    if not blocks:
        await query.edit_message_text(
            "❌ Блоки тем не найдены",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")
            ]])
        )
        return states.CHOOSING_MODE
    
    text = "📚 <b>Выберите блок тем:</b>"
    
    kb_buttons = []
    for block in blocks:
        topics_count = len(task20_data["topics_by_block"].get(block, []))
        kb_buttons.append([
            InlineKeyboardButton(
                f"{block} ({topics_count} тем)",
                callback_data=f"t20_block:{block}"
            )
        ])
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_practice")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_BLOCK

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

async def handle_result_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий после получения результата."""
    query = update.callback_query
    await query.answer()
    
    action = query.data.split("_")[2]  # t20_new_topic -> new, t20_retry -> retry
    
    if action == "retry":
        # Повторить ту же тему
        topic = context.user_data.get('current_topic')
        if topic:
            text = _build_topic_message(topic)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="t20_menu")]
            ])
            await query.edit_message_text(
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
            return states.ANSWERING
        else:
            await query.answer("Тема не найдена", show_alert=True)
            return await return_to_menu(update, context)
    
    elif action == "new":
        # Вернуться к выбору новой темы
        return await practice_mode(update, context)
    
    return states.CHOOSING_MODE


async def block_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню выбранного блока."""
    query = update.callback_query
    await query.answer()
    
    block_name = query.data.split(":", 1)[1]
    context.user_data['current_block'] = block_name
    
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
        return states.ANSWERING
    
    # Передаем в обычный обработчик
    update.message.text = extracted_text
    return await handle_answer(update, context)

async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка тем в блоке с пагинацией."""
    query = update.callback_query
    await query.answer()
    
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
        return states.CHOOSING_MODE
    
    topics = task20_data["topics_by_block"].get(block_name, [])
    
    # Пагинация: 5 тем на страницу
    topics_per_page = 5
    total_pages = (len(topics) + topics_per_page - 1) // topics_per_page
    start_idx = page * topics_per_page
    end_idx = min(start_idx + topics_per_page, len(topics))
    
    text = f"📚 <b>{block_name}</b>\n"
    text += f"Страница {page + 1} из {total_pages}\n\n"
    text += "Выберите тему:\n"
    
    kb_buttons = []
    
    # Кнопки с темами
    for topic in topics[start_idx:end_idx]:
        kb_buttons.append([
            InlineKeyboardButton(
                f"{topic['id']}. {topic['title']}",
                callback_data=f"t20_topic:{topic['id']}"
            )
        ])
    
    # Навигация по страницам
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"t20_list_topics:page:{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"t20_list_topics:page:{page+1}"))
    
    if nav_buttons:
        kb_buttons.append(nav_buttons)
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"t20_block:{block_name}")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_TOPIC

async def random_topic_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор случайной темы - оптимизированная версия."""
    query = update.callback_query
    await query.answer()
    
    # Используем оптимизированный селектор
    done_topics = {r['topic_id'] for r in context.user_data.get('task20_results', [])}
    topic = topic_selector.get_random_topic(exclude_ids=done_topics)
    
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
    return states.ANSWERING

async def random_topic_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор случайной темы из блока."""
    query = update.callback_query
    await query.answer()
    
    import random
    
    block_name = context.user_data.get('current_block')
    if not block_name:
        await query.edit_message_text(
            "❌ Блок не выбран",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_select_block")
            ]])
        )
        return states.CHOOSING_MODE
    
    topics = task20_data["topics_by_block"].get(block_name, [])
    if not topics:
        await query.edit_message_text(
            "❌ В блоке нет тем",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data=f"t20_block:{block_name}")
            ]])
        )
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
    
    return states.ANSWERING


async def bank_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по банку суждений."""
    query = update.callback_query
    await query.answer()
    
    topic_idx = int(query.data.split(":")[1])
    topics = task20_data.get('topics', [])
    
    if not topics or topic_idx >= len(topics):
        await query.edit_message_text("❌ Тема не найдена")
        return states.CHOOSING_MODE
    
    topic = topics[topic_idx]
    context.user_data['bank_current_idx'] = topic_idx
    
    text = f"""🏦 <b>Банк суждений</b>

<b>Тема:</b> {topic['title']}
<b>Блок:</b> {topic['block']}

<b>Задание:</b>
{topic['task_text']}

<b>Эталонные суждения:</b>

"""
    
    for i, example in enumerate(topic.get('example_arguments', []), 1):
        text += f"<b>{i}. {example['type']}</b>\n"
        text += f"<i>{example['argument']}</i>\n\n"
    
    text += "💡 <b>Обратите внимание:</b>\n"
    text += "• Суждения носят абстрактный характер\n"
    text += "• Используются обобщающие слова\n"
    text += "• Нет конкретных примеров и дат"
    
    # Навигация
    kb_buttons = []
    nav_row = []
    
    if topic_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"t20_bank_nav:{topic_idx-1}"))
    
    nav_row.append(InlineKeyboardButton(f"{topic_idx+1}/{len(topics)}", callback_data="noop"))
    
    if topic_idx < len(topics) - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"t20_bank_nav:{topic_idx+1}"))
    
    kb_buttons.append(nav_row)
    kb_buttons.append([InlineKeyboardButton("🔍 Поиск темы", callback_data="t20_bank_search")])
    kb_buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск темы в банке суждений."""
    query = update.callback_query
    await query.answer()
    
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

async def set_strictness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка уровня строгости."""
    global evaluator
    
    query = update.callback_query
    await query.answer()
    
    level_str = query.data.split(":")[1].upper()
    
    try:
        new_level = StrictnessLevel[level_str]
        
        # Пересоздаем evaluator с новым уровнем
        from .evaluator import Task20AIEvaluator, AI_EVALUATOR_AVAILABLE
        
        if AI_EVALUATOR_AVAILABLE:
            evaluator = Task20AIEvaluator(strictness=new_level)
            await query.answer(f"✅ Установлен уровень: {new_level.value}", show_alert=True)
            logger.info(f"Task20 strictness changed to {new_level.value}")
        else:
            await query.answer("❌ AI-проверка недоступна", show_alert=True)
        
        # Возвращаемся в настройки
        return await settings_mode(update, context)
        
    except Exception as e:
        logger.error(f"Error setting strictness: {e}")
        await query.answer("❌ Ошибка изменения настроек", show_alert=True)
        return states.CHOOSING_MODE


async def handle_settings_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик действий в настройках."""
    query = update.callback_query
    
    if query.data == "t20_reset_progress":
        return await reset_progress(update, context)
    elif query.data == "t20_confirm_reset":
        return await confirm_reset(update, context)
    
    return states.CHOOSING_MODE

async def detailed_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная статистика с графиками."""
    query = update.callback_query
    await query.answer()
    
    results = context.user_data.get('task20_results', [])
    
    if len(results) < 5:
        await query.answer("Нужно минимум 5 попыток для детальной статистики", show_alert=True)
        return await my_progress(update, context)
    
    try:
        import matplotlib
        matplotlib.use('Agg')  # Для работы без GUI
        import matplotlib.pyplot as plt
        from io import BytesIO
        
        # Создаем фигуру с несколькими графиками
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(12, 10))
        fig.suptitle('Детальная статистика по заданию 20', fontsize=16)
        
        # График 1: Динамика результатов
        scores = [r['score'] for r in results]
        attempts = list(range(1, len(scores) + 1))
        
        ax1.plot(attempts, scores, 'b-o', linewidth=2, markersize=8)
        ax1.axhline(y=2, color='orange', linestyle='--', alpha=0.7, label='Проходной балл')
        ax1.axhline(y=3, color='green', linestyle='--', alpha=0.7, label='Максимум')
        
        # Добавляем скользящее среднее
        if len(scores) >= 5:
            window_size = 5
            moving_avg = []
            for i in range(len(scores) - window_size + 1):
                moving_avg.append(sum(scores[i:i+window_size]) / window_size)
            ax1.plot(range(window_size, len(scores) + 1), moving_avg, 'r-', linewidth=2, alpha=0.7, label='Среднее за 5 попыток')
        
        ax1.set_xlabel('Попытка')
        ax1.set_ylabel('Баллы')
        ax1.set_title('Динамика результатов')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        ax1.set_ylim(-0.5, 3.5)
        
        # График 2: Распределение баллов
        score_counts = {0: 0, 1: 0, 2: 0, 3: 0}
        for score in scores:
            score_counts[score] += 1
        
        bars = ax2.bar(score_counts.keys(), score_counts.values(), color=['red', 'orange', 'yellow', 'green'])
        ax2.set_xlabel('Баллы')
        ax2.set_ylabel('Количество')
        ax2.set_title('Распределение результатов')
        ax2.set_xticks([0, 1, 2, 3])
        
        # Добавляем проценты на столбцы
        total = len(scores)
        for bar, (score, count) in zip(bars, score_counts.items()):
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height,
                    f'{count}\n({count/total*100:.0f}%)',
                    ha='center', va='bottom')
        
        # График 3: Статистика по блокам
        blocks_data = {}
        for result in results:
            block = result['block']
            if block not in blocks_data:
                blocks_data[block] = []
            blocks_data[block].append(result['score'])
        
        block_names = list(blocks_data.keys())[:5]  # Максимум 5 блоков
        block_avgs = [sum(scores)/len(scores) for block, scores in blocks_data.items()][:5]
        
        bars3 = ax3.bar(range(len(block_names)), block_avgs, color='skyblue')
        ax3.set_xlabel('Блоки')
        ax3.set_ylabel('Средний балл')
        ax3.set_title('Результаты по блокам')
        ax3.set_xticks(range(len(block_names)))
        ax3.set_xticklabels([name[:15] + '...' if len(name) > 15 else name for name in block_names], rotation=45, ha='right')
        ax3.set_ylim(0, 3.5)
        
        # Добавляем значения на столбцы
        for bar in bars3:
            height = bar.get_height()
            ax3.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.2f}',
                    ha='center', va='bottom')
        
        # График 4: Прогресс за последние 30 дней
        from datetime import datetime, timedelta
        
        # Группируем по дням
        daily_scores = {}
        for result in results[-30:]:  # Последние 30 результатов
            try:
                date = datetime.fromisoformat(result['timestamp']).date()
                if date not in daily_scores:
                    daily_scores[date] = []
                daily_scores[date].append(result['score'])
            except:
                continue
        
        if daily_scores:
            dates = sorted(daily_scores.keys())
            daily_avgs = [sum(daily_scores[date])/len(daily_scores[date]) for date in dates]
            
            ax4.plot(dates, daily_avgs, 'g-o', linewidth=2, markersize=8)
            ax4.set_xlabel('Дата')
            ax4.set_ylabel('Средний балл')
            ax4.set_title('Прогресс по дням')
            ax4.tick_params(axis='x', rotation=45)
            ax4.grid(True, alpha=0.3)
            ax4.set_ylim(0, 3.5)
        else:
            ax4.text(0.5, 0.5, 'Недостаточно данных', ha='center', va='center', transform=ax4.transAxes)
        
        plt.tight_layout()
        
        # Сохраняем график
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        # Отправляем график
        await query.message.reply_photo(
            photo=buf,
            caption=f"📊 <b>Детальная статистика</b>\n\n"
                   f"Всего попыток: {len(results)}\n"
                   f"Средний балл: {sum(scores)/len(scores):.2f}/3\n"
                   f"Лучший результат: {max(scores)}/3\n"
                   f"Процент максимальных баллов: {score_counts[3]/total*100:.0f}%",
            parse_mode=ParseMode.HTML
        )
        
    except ImportError:
        await query.answer("Для графиков нужно установить matplotlib: pip install matplotlib", show_alert=True)
        return await my_progress(update, context)
    except Exception as e:
        logger.error(f"Error creating progress chart: {e}")
        await query.answer("Ошибка при создании графика", show_alert=True)
        return await my_progress(update, context)
    
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

async def show_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все достижения."""
    query = update.callback_query
    await query.answer()
    
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
    text += f"\n<b>Прогресс:</b> {len(achievements)}/{len(all_achievements)}"
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t20_progress")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def mistakes_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим работы над ошибками."""
    query = update.callback_query
    await query.answer()
    
    results = context.user_data.get('task20_results', [])
    
    # Находим темы с низкими баллами
    low_score_topics = [r for r in results if r['score'] < 2]
    
    if not low_score_topics:
        await query.edit_message_text(
            "👍 <b>Отличная работа!</b>\n\n"
            "У вас нет тем с низкими баллами для повторения.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")
            ]]),
            parse_mode=ParseMode.HTML
        )
        return states.CHOOSING_MODE
    
    text = f"🔧 <b>Работа над ошибками</b>\n\n"
    text += f"Найдено тем с низкими баллами: {len(low_score_topics)}\n\n"
    text += "Темы для повторения:\n"
    
    for i, result in enumerate(low_score_topics[:5]):  # Показываем до 5 тем
        text += f"• {result['topic_title']} ({result['score']}/3)\n"
    
    text += "\n<i>Выберите тему для повторения или начните со случайной.</i>"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Случайная тема из ошибок", callback_data="t20_random_mistake")],
        [InlineKeyboardButton("📝 Выбрать тему", callback_data="t20_select_mistake")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t20_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def export_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт результатов в CSV."""
    query = update.callback_query
    await query.answer()
    
    results = context.user_data.get('task20_results', [])
    
    if not results:
        await query.answer("Нет результатов для экспорта", show_alert=True)
        return states.CHOOSING_MODE
    
    try:
        import csv
        import io
        
        # Создаем CSV в памяти
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        
        # Заголовки
        writer.writerow(['Дата и время', 'Тема', 'Блок', 'Балл', 'Максимальный балл'])
        
        # Данные
        for result in results:
            timestamp = result.get('timestamp', 'Не указано')
            # Преобразуем timestamp в читаемый формат
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(timestamp)
                formatted_time = dt.strftime('%d.%m.%Y %H:%M')
            except:
                formatted_time = timestamp
            
            writer.writerow([
                formatted_time,
                result.get('topic_title', 'Не указано'),
                result.get('block', 'Не указано'),
                result.get('score', 0),
                result.get('max_score', 3)
            ])
        
        # Получаем CSV как строку
        output.seek(0)
        csv_data = output.getvalue()
        
        # Отправляем файл
        await query.message.reply_document(
            document=io.BytesIO(csv_data.encode('utf-8-sig')),  # utf-8-sig для корректного отображения в Excel
            filename=f"task20_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            caption="📊 Ваши результаты по заданию 20"
        )
        
        await query.answer("✅ Результаты экспортированы")
        
    except Exception as e:
        logger.error(f"Error exporting results: {e}")
        await query.answer("❌ Ошибка при экспорте", show_alert=True)
    
    return states.CHOOSING_MODE

async def choose_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы и показ задания."""
    query = update.callback_query
    await query.answer()
    
    topic_id = int(query.data.split(":")[1])
    topic = task20_data["topic_by_id"].get(topic_id)
    
    if not topic:
        await query.edit_message_text(
            "❌ Тема не найдена",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_select_block")
            ]])
        )
        return states.CHOOSING_MODE
    
    context.user_data['current_topic'] = topic
    
    text = _build_topic_message(topic)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="t20_select_block")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING

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

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа пользователя с AI-проверкой."""
    user_answer = update.message.text
    topic = context.user_data.get('current_topic')
    user_id = update.effective_user.id  # ← ДОБАВИТЬ ЭТУ СТРОКУ ЗДЕСЬ
    
    # Отладочное логирование
    logger.info(f"handle_answer called, evaluator = {evaluator}")
    logger.info(f"evaluator type: {type(evaluator) if evaluator else 'None'}")
    
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 К заданиям", callback_data="t20_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Показываем сообщение о проверке
    thinking_msg = await update.message.reply_text(
        "🤔 Анализирую ваши суждения..."
    )
    
    result: Optional[EvaluationResult] = None
    
    try:
        # Проверяем наличие evaluator
        if not evaluator:
            logger.warning("Evaluator is None, using basic evaluation")
            # Простая проверка без AI
            arguments = [arg.strip() for arg in user_answer.split('\n') if arg.strip()]
            score = min(len(arguments), 3) if len(arguments) <= 3 else 0
            
            feedback = f"📊 <b>Результаты проверки</b>\n\n"
            feedback += f"<b>Тема:</b> {topic['title']}\n"
            feedback += f"<b>Суждений найдено:</b> {len(arguments)}\n\n"
            
            if len(arguments) >= 3:
                feedback += "✅ Вы привели достаточное количество суждений.\n"
            else:
                feedback += "❌ Необходимо привести три суждения.\n"
            
            feedback += "\n⚠️ <i>AI-проверка недоступна. Обратитесь к преподавателю для детальной оценки.</i>"
            
            # НЕ показываем эталонные суждения!
            
            result_data = {
                'topic_id': topic['id'],
                'topic_title': topic['title'],
                'block': topic['block'],
                'answer': user_answer,
                'score': score,
                'max_score': 3,
                'timestamp': datetime.now().isoformat(),
                'arguments_count': len(arguments)
            }
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
                feedback += f"<b>Комментарий:</b>\n{result.feedback}\n"
            
            if result.suggestions:
                feedback += f"\n<b>Рекомендации:</b>\n"
                for suggestion in result.suggestions:
                    feedback += f"• {suggestion}\n"
            
            # НЕ показываем эталонные суждения!
            # Вместо этого добавляем совет если оценка не максимальная
            if result.total_score < result.max_score:
                feedback += "\n💡 <i>Для улучшения результата обратите внимание на рекомендации выше.</i>"
            
            # Данные для сохранения
            result_data = {
                'topic_id': topic['id'],
                'topic_title': topic['title'],
                'block': topic['block'],
                'answer': user_answer,
                'score': result.total_score,
                'max_score': result.max_score,
                'timestamp': datetime.now().isoformat(),
                'ai_analysis': result.detailed_analysis
            }
        
        # Удаляем сообщение "Анализирую..."
        try:
            await thinking_msg.delete()
        except:
            pass
        
        # Сохраняем результат
        if 'task20_results' not in context.user_data:
            context.user_data['task20_results'] = []
        context.user_data['task20_results'].append(result_data)
        await save_stats_by_level(context, user_id, result_data['score'])
                # Проверяем достижения
        new_achievements = await achievements_check(context, user_id)
        
        # Если есть новые достижения, добавляем их в feedback
        if new_achievements:
            feedback += "\n\n🎉 <b>Новые достижения:</b>\n"
            for ach in new_achievements:
                feedback += f"{ach['name']} - {ach['desc']}\n"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="t20_retry")],
            [InlineKeyboardButton("📝 Новая тема", callback_data="t20_new_topic")],
            [InlineKeyboardButton("📊 Мой прогресс", callback_data="t20_progress")],
            [InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")]
        ])
        
        await update.message.reply_text(
            feedback,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Error in handle_answer: {e}")
        
        # Удаляем сообщение "Анализирую..."
        try:
            await thinking_msg.delete()
        except:
            pass
        
        await update.message.reply_text(
            "❌ Произошла ошибка при проверке. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")
            ]])
        )
    
    return states.AWAITING_FEEDBACK

async def handle_bank_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поискового запроса в банке суждений."""
    if not context.user_data.get('waiting_for_bank_search'):
        return
    
    search_query = update.message.text.lower()
    context.user_data['waiting_for_bank_search'] = False
    
    # Ищем подходящие темы
    matching_topics = []
    for idx, topic in enumerate(task20_data.get('topics', [])):
        if (search_query in topic['title'].lower() or 
            search_query in topic.get('task_text', '').lower() or
            search_query in topic.get('block', '').lower()):
            matching_topics.append((idx, topic))
    
    if not matching_topics:
        await update.message.reply_text(
            "❌ Темы не найдены. Попробуйте другой запрос.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 Искать снова", callback_data="t20_bank_search"),
                InlineKeyboardButton("⬅️ Назад", callback_data="t20_examples")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Показываем результаты поиска
    text = f"✅ Найдено тем: {len(matching_topics)}\n\n"
    
    kb_buttons = []
    for idx, (topic_idx, topic) in enumerate(matching_topics[:10]):  # Показываем до 10 результатов
        kb_buttons.append([
            InlineKeyboardButton(
                f"{topic['title']}",
                callback_data=f"t20_bank_nav:{topic_idx}"
            )
        ])
    
    if len(matching_topics) > 10:
        text += f"<i>Показаны первые 10 из {len(matching_topics)} результатов</i>"
    
    kb_buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="t20_examples")])
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
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