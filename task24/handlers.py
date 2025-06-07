import logging
import json
import os
import telegram
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from datetime import datetime
from typing import Set, Dict, List, Optional
from core import states
from core import utils as core_utils
from .checker import PlanBotData, evaluate_plan, FEEDBACK_KB
from . import keyboards

logger = logging.getLogger(__name__)

# Глобальные данные
plan_bot_data = None

# Список ID администраторов (добавьте свои ID)
ADMIN_IDS = []
admin_ids_str = os.getenv('TASK24_ADMIN_IDS', '')
if admin_ids_str:
    try:
        ADMIN_IDS = [int(id_str.strip()) for id_str in admin_ids_str.split(',') if id_str.strip()]
    except ValueError:
        logger.warning("Неверный формат TASK24_ADMIN_IDS в переменных окружения")

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором."""
    return user_id in ADMIN_IDS

def admin_only(func):
    """Декоратор для функций, доступных только администраторам."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id or not is_admin(user_id):
            if update.callback_query:
                await update.callback_query.answer("❌ Эта функция доступна только администраторам", show_alert=True)
            else:
                await update.message.reply_text("❌ Эта функция доступна только администраторам")
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)
    return wrapper

def get_user_stats(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, any]:
    """Получение статистики пользователя."""
    practiced = context.user_data.get('practiced_topics', set())
    total_topics = len(plan_bot_data.topic_list_for_pagination) if plan_bot_data else 0
    
    # История оценок
    scores_history = context.user_data.get('scores_history', [])
    
    # Время работы
    start_time = context.user_data.get('session_start', None)
    total_time = context.user_data.get('total_time_minutes', 0)
    
    return {
        'practiced_count': len(practiced),
        'total_topics': total_topics,
        'progress_percent': int(len(practiced) / total_topics * 100) if total_topics > 0 else 0,
        'scores_history': scores_history,
        'average_score': sum(s['total'] for s in scores_history) / len(scores_history) if scores_history else 0,
        'total_time_minutes': total_time
    }
    
def get_user_stats_from_data(user_data: dict, plan_bot_data) -> Dict[str, any]:
    """Получение статистики из user_data напрямую (для админских функций)."""
    practiced = user_data.get('practiced_topics', set())
    total_topics = len(plan_bot_data.topic_list_for_pagination) if plan_bot_data else 0
    
    scores_history = user_data.get('scores_history', [])
    
    return {
        'practiced_count': len(practiced),
        'total_topics': total_topics,
        'progress_percent': int(len(practiced) / total_topics * 100) if total_topics > 0 else 0,
        'scores_history': scores_history,
        'average_score': sum(s['total'] for s in scores_history) / len(scores_history) if scores_history else 0,
        'total_time_minutes': user_data.get('total_time_minutes', 0)
    }

def load_admin_ids():
    """Загрузка списка администраторов из конфига."""
    global ADMIN_IDS
    
    # Сначала пробуем загрузить из переменных окружения
    admin_ids_str = os.getenv('TASK24_ADMIN_IDS', '')
    if admin_ids_str:
        try:
            ADMIN_IDS = [int(id_str.strip()) for id_str in admin_ids_str.split(',') if id_str.strip()]
            logger.info(f"Загружено {len(ADMIN_IDS)} администраторов из переменных окружения")
            return
        except ValueError:
            logger.warning("Неверный формат TASK24_ADMIN_IDS в переменных окружения")
    
    # Затем пробуем загрузить из файла
    try:
        config_file = os.path.join(os.path.dirname(__file__), 'admin_config.json')
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
                ADMIN_IDS = config.get('admin_ids', [])
                logger.info(f"Загружено {len(ADMIN_IDS)} администраторов из файла")
        else:
            # Создаем файл с примером
            example_config = {
                "admin_ids": [],
                "comment": "Добавьте сюда ID администраторов Telegram"
            }
            with open(config_file, 'w') as f:
                json.dump(example_config, f, indent=4)
            logger.info(f"Создан пример файла конфигурации: {config_file}")
    except Exception as e:
        logger.error(f"Ошибка загрузки админов из файла: {e}")
    
    if not ADMIN_IDS:
        logger.warning("Список администраторов пуст - админские функции отключены")

def save_score_to_history(context: ContextTypes.DEFAULT_TYPE, topic: str, k1: int, k2: int):
    """Сохранение оценки в историю."""
    if 'scores_history' not in context.user_data:
        context.user_data['scores_history'] = []
    
    context.user_data['scores_history'].append({
        'topic': topic,
        'k1': k1,
        'k2': k2,
        'total': k1 + k2,
        'timestamp': datetime.now().isoformat()
    })

def init_data():
    """Загрузка данных планов с улучшенной обработкой ошибок."""
    global plan_bot_data
    
    # Список возможных путей к файлу данных
    possible_paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "plans_data_with_blocks.json"),
        os.path.join(os.path.dirname(__file__), "data", "plans_data_with_blocks.json"),
        os.path.join(os.path.dirname(__file__), "plans_data_with_blocks.json"),
        "plans_data_with_blocks.json",
        "data/plans_data_with_blocks.json"
    ]
    
    data_loaded = False
    for data_file in possible_paths:
        try:
            if os.path.exists(data_file):
                logger.info(f"Пытаемся загрузить данные из: {data_file}")
                with open(data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # Проверяем структуру данных
                if isinstance(data, dict) and ("plans" in data or "blocks" in data):
                    plan_bot_data = PlanBotData(data)
                    logger.info(f"Данные планов загружены успешно из {data_file}")
                    logger.info(f"Загружено тем: {len(plan_bot_data.topic_list_for_pagination)}")
                    data_loaded = True
                    break
                elif isinstance(data, list):
                    # Старый формат - список тем
                    plan_bot_data = PlanBotData(data)
                    logger.info(f"Данные планов (старый формат) загружены из {data_file}")
                    data_loaded = True
                    break
                else:
                    logger.warning(f"Неправильная структура данных в {data_file}")
                    
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка разбора JSON в {data_file}: {e}")
        except Exception as e:
            logger.error(f"Ошибка загрузки {data_file}: {e}")
    
    if not data_loaded:
        logger.error("Не удалось загрузить данные планов из всех возможных путей")
        logger.error(f"Проверенные пути: {possible_paths}")
        # Создаем пустой объект данных для избежания ошибок
        plan_bot_data = PlanBotData({"plans": {}, "blocks": {}})
    
    # Загружаем список администраторов
    load_admin_ids()
    
    return data_loaded  # Возвращаем статус загрузки

async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход из главного меню."""
    query = update.callback_query
    await query.answer()
    
    # Проверка наличия данных планов
    if not plan_bot_data or not plan_bot_data.topic_list_for_pagination:
        await query.edit_message_text(
            "❌ Данные планов не загружены. Обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]]),
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END
    
    # Проверка подписки если включена
    if hasattr(core_utils, 'check_subscription'):
        from core.config import REQUIRED_CHANNEL
        if not await core_utils.check_subscription(query.from_user.id, context.bot):
            await core_utils.send_subscription_required(query, REQUIRED_CHANNEL)
            return ConversationHandler.END
    
    # Инициализация времени сессии
    if 'session_start' not in context.user_data:
        context.user_data['session_start'] = datetime.now()
    
    # Строим клавиатуру с учетом прав пользователя
    user_id = query.from_user.id
    kb = keyboards.build_main_menu_keyboard() if not is_admin(user_id) else build_admin_menu_keyboard()
    
    await query.edit_message_text(
        "📝 <b>Задание 24 - составление сложного плана</b>\n\n"
        "Выберите режим работы:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

def build_admin_menu_keyboard() -> InlineKeyboardMarkup:
    """Расширенная клавиатура для администраторов."""
    keyboard = [
        [InlineKeyboardButton("💪 Тренироваться", callback_data="start_train")],
        [InlineKeyboardButton("👀 Посмотреть эталоны", callback_data="start_show")],
        [InlineKeyboardButton("🎯 Режим экзамена", callback_data="start_exam")],
        [InlineKeyboardButton("🔍 Поиск темы", callback_data="search_topics")],
        [InlineKeyboardButton("📜 Список всех тем", callback_data="show_list")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="show_progress")],
        [InlineKeyboardButton("📋 Критерии оценки", callback_data="show_criteria")],
        [InlineKeyboardButton("❓ Помощь", callback_data="show_help")],
        [InlineKeyboardButton("🔄 Сбросить прогресс", callback_data="reset_progress")],
        [InlineKeyboardButton("📤 Экспорт прогресса", callback_data="export_progress")],
        # Админские функции
        [InlineKeyboardButton("👥 Статистика пользователей", callback_data="admin_stats")],
        [InlineKeyboardButton("📈 Активность", callback_data="admin_activity")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def cmd_start_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start_plan."""
    # Инициализация времени сессии
    if 'session_start' not in context.user_data:
        context.user_data['session_start'] = datetime.now()
    
    user_id = update.effective_user.id
    kb = keyboards.build_main_menu_keyboard() if not is_admin(user_id) else build_admin_menu_keyboard()
    
    await update.message.reply_text(
        "📝 <b>Задание 24 - составление сложного плана</b>\n\n"
        "Выберите режим работы:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def train_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим тренировки."""
    query = update.callback_query
    await query.answer()
    
    if not plan_bot_data or not plan_bot_data.topic_list_for_pagination:
        await query.edit_message_text(
            "❌ Данные планов не загружены. Обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]])
        )
        return ConversationHandler.END  # ← Исправлено: только в случае ошибки
    
    context.user_data['mode'] = 'train'
    
    kb = keyboards.build_initial_choice_keyboard('train')
    await query.edit_message_text(
        "🎯 <b>Режим тренировки</b>\n\n"
        "Как вы хотите выбрать тему?",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_TOPIC  # ← Исправлено: возвращаем правильное состояние


async def show_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим просмотра эталонов."""
    query = update.callback_query
    await query.answer()
    
    if not plan_bot_data or not plan_bot_data.topic_list_for_pagination:
        await query.edit_message_text(
            "❌ Данные планов не загружены. Обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]])
        )
        return ConversationHandler.END  # ← Исправлено: только в случае ошибки
    
    context.user_data['mode'] = 'show'
    
    kb = keyboards.build_initial_choice_keyboard('show')
    await query.edit_message_text(
        "👁 <b>Режим просмотра эталонов</b>\n\n"
        "Как вы хотите выбрать тему?",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_TOPIC  # ← Исправлено: возвращаем правильное состояние

async def exam_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим экзамена - случайная тема без возможности выбора."""
    query = update.callback_query
    await query.answer()
    
    if not plan_bot_data or not plan_bot_data.topic_list_for_pagination:
        await query.edit_message_text(
            "❌ Данные планов не загружены. Обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]])
        )
        return ConversationHandler.END
    
    import random
    all_topics = plan_bot_data.get_all_topics_list()
    practiced = context.user_data.get('practiced_topics', set())
    
    # Приоритет непройденным темам
    unpracticed = [(idx, topic) for idx, topic in all_topics if idx not in practiced]
    
    if not unpracticed and not all_topics:
        await query.edit_message_text(
            "❌ Нет доступных тем для экзамена.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="start_button")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Выбираем тему
    topics_pool = unpracticed if unpracticed else all_topics
    idx, topic = random.choice(topics_pool)
    
    context.user_data['current_topic_index'] = idx
    context.user_data['current_topic'] = topic
    context.user_data['exam_mode'] = True
    
    status = "🆕 новая тема" if idx not in practiced else "🔁 повторение"
    
    await query.edit_message_text(
        f"🎯 <b>Режим экзамена</b> ({status})\n\n"
        f"📝 <b>Тема:</b> {topic}\n\n"
        "Составьте план. У вас одна попытка!\n\n"
        "<b>💡 Примеры форматов подпунктов:</b>\n"
        "• <code>Виды: фрикционная; структурная; циклическая</code>\n"
        "• <code>а) первый подпункт б) второй в) третий</code>\n"
        "• <code>- подпункт 1\n- подпункт 2</code>\n\n"
        "<i>Отправьте /cancel для отмены.</i>",
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_PLAN

async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка всех тем."""
    query = update.callback_query
    await query.answer()
    
    if not plan_bot_data:
        await query.answer("Данные не загружены", show_alert=True)
        return states.CHOOSING_MODE
    
    all_topics = plan_bot_data.get_all_topics_list()
    
    # Формируем текст списка
    text = "📚 <b>Доступные темы для планов:</b>\n\n"
    practiced = context.user_data.get('practiced_topics', set())
    
    current_block = None
    for idx, topic_name in all_topics:
        # Находим блок для темы
        topic_block = None
        for block, topics in plan_bot_data.topics_by_block.items():
            if any(t[1] == topic_name for t in topics):
                topic_block = block
                break
        
        # Добавляем заголовок блока если изменился
        if topic_block != current_block:
            current_block = topic_block
            text += f"\n<b>{current_block}:</b>\n"
        
        marker = "✅ " if idx in practiced else "▫️ "
        text += f"{marker}{idx + 1}. {topic_name}\n"
    
    # Добавляем статистику
    total = len(all_topics)
    completed = len(practiced)
    text += f"\n📊 Пройдено: {completed}/{total} ({int(completed/total*100) if total > 0 else 0}%)"
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад в меню", callback_data="start_button")
    ]])
    
    # Отправляем или редактируем
    if len(text) > 4000:
        # Если текст слишком длинный, отправляем файлом
        from io import BytesIO
        file_data = BytesIO(text.encode('utf-8'))
        file_data.name = "topics_list.txt"
        
        # Удаляем старое сообщение
        try:
            await query.message.delete()
        except:
            pass
        
        await query.message.reply_document(
            document=file_data,
            caption="📚 Список всех тем (файл из-за большого размера)",
            reply_markup=kb
        )
    else:
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except telegram.error.BadRequest as e:
            if "There is no text in the message to edit" in str(e) or "Message can't be edited" in str(e):
                try:
                    await query.message.delete()
                except:
                    pass
                
                await query.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            else:
                raise
    
    return states.CHOOSING_MODE

async def select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split(":")
    if len(parts) < 3:
        logger.error(f"Неправильный формат callback_data: {query.data}")
        return
    
    mode = parts[1]
    topic_idx = int(parts[2])
    
    # Получаем тему по индексу
    topic_name = plan_bot_data.topic_index_map.get(topic_idx)
    if not topic_name:
        await query.answer("Тема не найдена", show_alert=True)
        return
    
    # Сохраняем в контекст
    context.user_data['current_topic_index'] = topic_idx
    context.user_data['current_topic'] = topic_name
    
    if mode == 'train':
        # Режим тренировки - просим прислать план
        await query.message.edit_text(
            f"📝 <b>Тема:</b> {topic_name}\n\n"
            "Составьте и отправьте сложный план по этой теме.\n\n"
            "<b>Требования ЕГЭ 2025:</b>\n"
            "• Минимум 3 пункта, раскрывающих тему\n"
            "• Минимум 3 из них должны быть детализированы\n"
            "• В каждом пункте минимум 3 подпункта\n\n"
            "<b>Форматы написания подпунктов:</b>\n"
            "✅ <code>1. Виды: фрикционная; структурная; циклическая</code>\n"
            "✅ <code>2. Последствия:\n   а) для экономики\n   б) для общества</code>\n"
            "✅ <code>3. Меры борьбы:\n   - программы занятости\n   - переквалификация</code>\n\n"
            "<i>💡 Можете использовать любой удобный формат!</i>\n\n"
            "<i>Отправьте /cancel для отмены</i>",
            parse_mode=ParseMode.HTML
        )
        return states.AWAITING_PLAN
    
    elif mode == 'show':
        # Режим просмотра - показываем эталон
        return await show_etalon_plan(query, context, topic_idx)

async def show_etalon_plan(query, context, topic_idx):
    """Показ эталонного плана."""
    topic_name = plan_bot_data.topic_index_map.get(topic_idx)
    if not topic_name:
        await query.answer("Тема не найдена", show_alert=True)
        return
    
    plan_data = plan_bot_data.get_plan_data(topic_name)
    if not plan_data:
        await query.answer("Данные плана не найдены", show_alert=True)
        return
    
    # Формируем текст эталона
    text = f"📋 <b>Эталонный план</b>\n<b>Тема:</b> {topic_name}\n\n"
    
    # Проверяем наличие готового текста
    if 'full_plan' in plan_data:
        text += plan_data['full_plan']
    elif 'etalon_plan_text' in plan_data:
        text += plan_data['etalon_plan_text']
    else:
        # Генерируем из points_data
        points_data = plan_data.get('points_data', [])
        for i, point in enumerate(points_data, 1):
            if isinstance(point, dict):
                point_text = point.get('point_text', '')
                is_key = "⭐ " if point.get('is_potentially_key') else ""
                text += f"{i}. {is_key}{point_text}\n"
                
                # Добавляем подпункты если есть
                subpoints = point.get('sub_points', point.get('subpoints', []))
                for j, subpoint in enumerate(subpoints):
                    text += f"   {chr(ord('а') + j)}) {subpoint}\n"
    
    # Добавляем пояснения по обязательным пунктам
    obligatory_count = sum(1 for p in plan_data.get('points_data', []) 
                          if isinstance(p, dict) and p.get('is_potentially_key'))
    if obligatory_count > 0:
        text += f"\n⭐ <i>Обязательных пунктов: {obligatory_count}</i>"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Потренироваться", callback_data=f"topic:train:{topic_idx}")],
        [InlineKeyboardButton("⬅️ К выбору темы", callback_data=f"nav:back_to_choice:{context.user_data.get('mode')}")],
        [InlineKeyboardButton("🏠 В меню", callback_data="start_button")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_TOPIC

async def navigate_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по темам."""
    query = update.callback_query
    await query.answer()
    
    # Проверка загрузки данных
    if not plan_bot_data or not hasattr(plan_bot_data, 'topic_list_for_pagination'):
        await query.edit_message_text(
            "❌ Данные планов не загружены. Обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]])
        )
        return ConversationHandler.END
    
    parts = query.data.split(":")
    action = parts[1]
    
    if action == "choose_block":
        mode = parts[2]
        kb = keyboards.build_block_selection_keyboard(mode)
        await query.edit_message_text(
            "📚 Выберите блок тем:",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    
    elif action == "show_all":
        mode = parts[2]
        page = 0
        practiced = context.user_data.get('practiced_topics', set())
        text, kb = keyboards.build_topic_page_keyboard(
            mode, page, plan_bot_data, practiced
        )
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    
    elif action == "random":
        mode = parts[2]
        import random
        all_topics = plan_bot_data.get_all_topics_list()
        practiced = context.user_data.get('practiced_topics', set())
        
        # Приоритет непройденным темам
        unpracticed = [(idx, topic) for idx, topic in all_topics if idx not in practiced]
        topics_pool = unpracticed if unpracticed else all_topics
        
        if topics_pool:
            idx, topic_name = random.choice(topics_pool)
            
            # Сохраняем в контекст
            context.user_data['current_topic_index'] = idx
            context.user_data['current_topic'] = topic_name
            
            if mode == 'train':
                # Режим тренировки - просим прислать план
                await query.edit_message_text(
                    f"📝 <b>Тема:</b> {topic_name}\n\n"
                    "Составьте и отправьте сложный план по этой теме.\n\n"
                    "<b>Требования ЕГЭ 2025:</b>\n"
                    "• Минимум 3 пункта, раскрывающих тему\n"
                    "• Минимум 3 из них должны быть детализированы\n"
                    "• В каждом пункте минимум 3 подпункта\n\n"
                    "<b>Форматы написания подпунктов:</b>\n"
                    "✅ <code>1. Виды: фрикционная; структурная; циклическая</code>\n"
                    "✅ <code>2. Последствия:\n   а) для экономики\n   б) для общества</code>\n"
                    "✅ <code>3. Меры борьбы:\n   - программы занятости\n   - переквалификация</code>\n\n"
                    "<i>💡 Можете использовать любой удобный формат!</i>\n\n"
                    "<i>Отправьте /cancel для отмены</i>",
                    parse_mode=ParseMode.HTML
                )
                return states.AWAITING_PLAN
            
            elif mode == 'show':
                # Режим просмотра - показываем эталон
                return await show_etalon_plan(query, context, idx)
        else:
            await query.answer("Нет доступных тем", show_alert=True)
    
    elif action in ["all", "block"]:
        mode = parts[2]
        page = int(parts[3])
        block_name = parts[4] if len(parts) > 4 else None
        
        practiced = context.user_data.get('practiced_topics', set())
        text, kb = keyboards.build_topic_page_keyboard(
            mode, page, plan_bot_data, practiced, block_name
        )
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    
    elif action == "select_block":
        mode = parts[2]
        block_name = ":".join(parts[3:])
        
        practiced = context.user_data.get('practiced_topics', set())
        text, kb = keyboards.build_topic_page_keyboard(
            mode, 0, plan_bot_data, practiced, block_name
        )
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    
    elif action == "back_to_main":
        mode = parts[2] if len(parts) > 2 else 'train'
        kb = keyboards.build_initial_choice_keyboard(mode)
        await query.edit_message_text(
            f"🎯 <b>Режим {'тренировки' if mode == 'train' else 'просмотра'}</b>\n\n"
            "Как вы хотите выбрать тему?",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    
    elif action == "back_to_choice":
        return await train_mode(update, context) if context.user_data.get('mode') == 'train' else await show_mode(update, context)
    
    return states.CHOOSING_TOPIC

async def handle_plan_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка присланного плана."""
    user_plan_text = update.message.text.strip()
    
    if not user_plan_text:
        await update.message.reply_text(
            "❌ Вы прислали пустое сообщение. Пожалуйста, отправьте ваш план."
        )
        return states.AWAITING_PLAN
    
    # Проверка минимальной длины
    if len(user_plan_text) < 50:
        await update.message.reply_text(
            "❌ План слишком короткий. Пожалуйста, составьте развернутый план."
        )
        return states.AWAITING_PLAN
    
    # Получаем данные темы
    topic_index = context.user_data.get('current_topic_index')
    topic_name = context.user_data.get('current_topic')
    
    if not topic_name:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана. Используйте /start_plan"
        )
        return ConversationHandler.END
    
    # Получаем эталонные данные
    ideal_plan_data = plan_bot_data.get_plan_data(topic_name)
    if not ideal_plan_data:
        await update.message.reply_text(
            "❌ Ошибка: не найдены эталонные данные для темы."
        )
        return ConversationHandler.END
    
    # Отправляем сообщение "Анализирую..."
    # Отправляем сообщение "Анализирую..."
    thinking_msg = await update.message.reply_text("🧠 Анализирую ваш план...")
    
    try:
        # Проверяем, включена ли AI-проверка
        use_ai = context.bot_data.get('use_ai_checking', True)
        
        # Оцениваем план с AI
        if 'evaluate_plan_with_ai' in globals():
            feedback = await evaluate_plan_with_ai(
                user_plan_text,
                ideal_plan_data,
                plan_bot_data,
                topic_name,
                use_ai=use_ai
            )
        else:
            # Fallback на обычную проверку
            feedback = evaluate_plan(
                user_plan_text,
                ideal_plan_data,
                plan_bot_data,
                topic_name
            )
        
        # Извлекаем баллы из фидбека для статистики
        import re
        k1_match = re.search(r'К1.*?(\d+)/3', feedback)
        k2_match = re.search(r'К2.*?(\d+)/1', feedback)
        k1 = int(k1_match.group(1)) if k1_match else 0
        k2 = int(k2_match.group(1)) if k2_match else 0
        
        # Сохраняем результат
        if topic_index is not None:
            practiced = context.user_data.setdefault('practiced_topics', set())
            practiced.add(topic_index)
            
            # Сохраняем в историю оценок
            save_score_to_history(context, topic_name, k1, k2)
            
            # Обновляем статистику времени
            if 'session_start' in context.user_data:
                session_time = (datetime.now() - context.user_data['session_start']).total_seconds() / 60
                context.user_data['total_time_minutes'] = context.user_data.get('total_time_minutes', 0) + session_time
                context.user_data['session_start'] = datetime.now()
        
        # Добавляем информацию об эталоне в экзаменационном режиме
        if context.user_data.get('exam_mode'):
            feedback += "\n\n" + "━" * 30 + "\n"
            feedback += "📋 <b>Посмотреть эталонный план?</b>"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("👀 Показать эталон", callback_data=f"topic:show:{topic_index}")],
                [InlineKeyboardButton("🔄 Ещё тема", callback_data="next_topic")],
                [InlineKeyboardButton("🏠 В меню", callback_data="start_button")]
            ])
            context.user_data['exam_mode'] = False
        else:
            kb = FEEDBACK_KB
        
        await thinking_msg.edit_text(
            feedback,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Ошибка при оценке плана: {e}", exc_info=True)
        await thinking_msg.edit_text(
            "❌ Произошла ошибка при анализе плана. Попробуйте еще раз."
        )
    
    return states.CHOOSING_TOPIC

async def next_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к следующей теме."""
    query = update.callback_query
    await query.answer()
    
    # Возвращаемся к выбору темы в режиме тренировки
    context.user_data['mode'] = 'train'
    kb = keyboards.build_initial_choice_keyboard('train')
    await query.edit_message_text(
        "🎯 <b>Режим тренировки</b>\n\n"
        "Выберите следующую тему:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_TOPIC

async def show_criteria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ критериев оценки."""
    criteria_text = """<b>📋 Критерии оценивания задания 24 (ЕГЭ 2025)</b>

<b>К1 - Раскрытие темы по существу</b> (макс. 3 балла):

<b>3 балла:</b>
• План содержит не менее 3 пунктов, раскрывающих тему
• Минимум 3 ключевых пункта детализированы в подпунктах
• Каждый пункт содержит минимум 3 подпункта

<b>2 балла:</b>
• Найдено минимум 3 ключевых пункта
• Только 2 из них детализированы правильно

<b>1 балл:</b>
• Найдено минимум 3 ключевых пункта
• Только 1 из них детализирован правильно

<b>0 баллов:</b>
• Найдено менее 3 ключевых пунктов, раскрывающих тему
• Или план не соответствует требованиям

<b>К2 - Корректность формулировок</b> (макс. 1 балл):
• 1 балл выставляется только при К1 = 3
• Формулировки должны быть точными и без ошибок

<i>⚠️ Важно: Для получения баллов план должен содержать МИНИМУМ 3 ключевых пункта из эталона!</i>"""
    
    query = update.callback_query
    if query:
        await query.answer()
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="back_main")
        ]])
        await query.edit_message_text(
            criteria_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(criteria_text, parse_mode=ParseMode.HTML)
    
    return states.CHOOSING_MODE

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ помощи."""
    help_text = """<b>❓ Помощь по заданию 24</b>

<b>Режимы работы:</b>
• 💪 <b>Тренировка</b> - составьте план, получите оценку
• 👀 <b>Просмотр</b> - изучайте эталонные планы
• 🎯 <b>Экзамен</b> - случайная тема для проверки
• 🔍 <b>Поиск</b> - найдите тему по ключевым словам

<b>Как составить план на максимальный балл:</b>
1. Включите ВСЕ ключевые аспекты темы
2. Детализируйте минимум 3 пункта подпунктами
3. Минимум 3 подпункта в каждом пункте
4. Используйте точные формулировки

<b>Форматы плана (выберите удобный!):</b>

<b>Классический:</b>
<code>1. Первый пункт
   а) подпункт
   б) подпункт  
   в) подпункт</code>

<b>Через точку с запятой:</b>
<code>1. Виды безработицы: фрикционная; структурная; циклическая; сезонная
2. Последствия: снижение доходов; социальная напряженность; рост преступности</code>

<b>Смешанный:</b>
<code>1. Понятие безработицы
2. Виды: фрикционная; структурная; циклическая
3. Меры борьбы:
   - программы занятости
   - переквалификация
   - общественные работы</code>

<b>Команды:</b>
/start_plan - начать работу
/criteria - критерии оценки
/cancel - отменить действие"""
    
    query = update.callback_query
    await query.answer()
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="start_button")
    ]])
    
    await safe_edit_or_reply(query, help_text, kb, ParseMode.HTML)
    return states.CHOOSING_MODE

async def show_block_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ статистики по блокам и общего прогресса."""
    query = update.callback_query
    await query.answer()
    
    practiced = context.user_data.get('practiced_topics', set())
    stats = get_user_stats(context)
    
    text = "📊 <b>Ваш прогресс:</b>\n\n"
    
    # Общая статистика
    text += f"✅ Пройдено тем: {stats['practiced_count']}/{stats['total_topics']} ({stats['progress_percent']}%)\n"
    
    # Визуальная шкала прогресса
    filled = "█" * (stats['progress_percent'] // 10)
    empty = "░" * (10 - stats['progress_percent'] // 10)
    text += f"Прогресс: {filled}{empty}\n"
    
    # Средний балл
    if stats['scores_history']:
        text += f"📈 Средний балл: {stats['average_score']:.1f}/4\n"
        
        # Распределение оценок
        score_dist = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
        for score in stats['scores_history']:
            score_dist[score['total']] += 1
        
        text += "\n<b>Распределение оценок:</b>\n"
        for score, count in sorted(score_dist.items(), reverse=True):
            if count > 0:
                text += f"{'⭐' * score if score > 0 else '😔'} {score} балла: {count} раз\n"
    
    # Время работы
    if stats['total_time_minutes'] > 0:
        hours = int(stats['total_time_minutes'] // 60)
        minutes = int(stats['total_time_minutes'] % 60)
        text += f"\n⏱ Время работы: {hours}ч {minutes}мин\n"
    
    text += "\n<b>Статистика по блокам:</b>\n"
    
    for block_name, topics in plan_bot_data.topics_by_block.items():
        total = len(topics)
        completed = sum(1 for idx, _ in topics if idx in practiced)
        progress = int(completed / total * 100) if total > 0 else 0
        
        # Эмодзи в зависимости от прогресса
        emoji = "✅" if progress == 100 else "🟡" if progress >= 50 else "🔴"
        
        text += f"\n{emoji} <b>{block_name}:</b> {completed}/{total} ({progress}%)"
    
    # Рекомендации
    if stats['progress_percent'] < 100:
        text += "\n\n💡 <b>Рекомендация:</b> "
        if stats['progress_percent'] < 30:
            text += "Отличное начало! Продолжайте тренироваться."
        elif stats['progress_percent'] < 70:
            text += "Хороший прогресс! Не останавливайтесь."
        else:
            text += "Вы почти у цели! Осталось совсем немного."
    else:
        text += "\n\n🎉 <b>Поздравляем!</b> Вы изучили все темы!"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Экспорт прогресса", callback_data="export_progress")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="start_button")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE

async def reset_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс прогресса с подтверждением."""
    query = update.callback_query
    await query.answer()
    
    # Проверяем, есть ли флаг подтверждения
    if context.user_data.get('confirm_reset'):
        # Сброс подтвержден
        context.user_data['practiced_topics'] = set()
        context.user_data['scores_history'] = []
        context.user_data['total_time_minutes'] = 0
        context.user_data.pop('confirm_reset', None)
        
        await query.answer("✅ Прогресс сброшен!", show_alert=True)
        
        # Возвращаемся в меню
        kb = keyboards.build_main_menu_keyboard()
        await query.edit_message_text(
            "📝 <b>Задание 24 - составление сложного плана</b>\n\n"
            "Прогресс успешно сброшен. Выберите режим:",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    else:
        # Запрашиваем подтверждение
        context.user_data['confirm_reset'] = True
        
        stats = get_user_stats(context)
        warning_text = f"⚠️ <b>Вы уверены?</b>\n\n"
        warning_text += f"Будет удалено:\n"
        warning_text += f"• Прогресс по {stats['practiced_count']} темам\n"
        warning_text += f"• История из {len(stats['scores_history'])} оценок\n"
        warning_text += f"• Статистика времени\n\n"
        warning_text += "Это действие нельзя отменить!"
        
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("❌ Да, сбросить", callback_data="reset_progress"),
                InlineKeyboardButton("✅ Отмена", callback_data="cancel_reset")
            ]
        ])
        
        await query.edit_message_text(
            warning_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    
    return states.CHOOSING_MODE

async def cancel_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена сброса прогресса."""
    query = update.callback_query
    await query.answer("Сброс отменен")
    
    context.user_data.pop('confirm_reset', None)
    
    user_id = query.from_user.id
    kb = keyboards.build_main_menu_keyboard() if not is_admin(user_id) else build_admin_menu_keyboard()
    
    menu_text = (
        "📝 <b>Задание 24 - составление сложного плана</b>\n\n"
        "Выберите режим работы:"
    )
    
    try:
        await query.edit_message_text(
            menu_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    except telegram.error.BadRequest as e:
        if "There is no text in the message to edit" in str(e) or "Message can't be edited" in str(e):
            try:
                await query.message.delete()
            except:
                pass
            
            await query.message.reply_text(
                menu_text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
        else:
            raise
    
    return states.CHOOSING_MODE

async def export_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт прогресса пользователя."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    username = query.from_user.username or "Unknown"
    practiced = context.user_data.get('practiced_topics', set())
    stats = get_user_stats(context)
    
    # Создаем подробный отчет
    progress_data = {
        'user_info': {
            'user_id': user_id,
            'username': username,
            'export_date': datetime.now().isoformat()
        },
        'statistics': {
            'practiced_topics': list(practiced),  # Преобразуем set в list
            'total_topics': stats['total_topics'],
            'progress_percent': stats['progress_percent'],
            'average_score': stats['average_score'],
            'total_time_minutes': stats['total_time_minutes']
        },
        'scores_history': stats['scores_history'],
        'topics_by_block': {}
    }
    
    # Добавляем детализацию по блокам
    for block_name, topics in plan_bot_data.topics_by_block.items():
        block_data = {
            'total': len(topics),
            'completed': sum(1 for idx, _ in topics if idx in practiced),
            'topics': []
        }
        
        for idx, topic in topics:
            topic_data = {
                'index': idx,
                'name': topic,
                'completed': idx in practiced,
                'scores': [s for s in stats['scores_history'] if s['topic'] == topic]
            }
            block_data['topics'].append(topic_data)
        
        progress_data['topics_by_block'][block_name] = block_data
    
    # Отправляем файл
    from io import BytesIO
    file_data = BytesIO(json.dumps(progress_data, indent=2, ensure_ascii=False).encode('utf-8'))
    file_data.name = f"my_progress_task24_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    # Удаляем старое сообщение перед отправкой документа
    try:
        await query.message.delete()
    except:
        pass
    
    # Отправляем документ с кнопкой возврата
    kb = keyboards.build_main_menu_keyboard() if not is_admin(user_id) else build_admin_menu_keyboard()
    
    await query.message.reply_document(
        document=file_data,
        caption=(
            f"📤 Ваш прогресс\n"
            f"Пройдено: {stats['progress_percent']}%\n"
            f"Средний балл: {stats['average_score']:.1f}\n\n"
            f"Используйте кнопки ниже для навигации:"
        ),
        reply_markup=kb
    )
    
    return states.CHOOSING_MODE

async def search_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск тем по ключевым словам."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔍 <b>Поиск темы</b>\n\n"
        "Отправьте ключевые слова для поиска.\n"
        "Например: <i>политика партии</i>",
        reply_markup=keyboards.build_search_keyboard(),
        parse_mode=ParseMode.HTML
    )
    return states.AWAITING_SEARCH

async def handle_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поискового запроса."""
    search_text = update.message.text.lower()
    results = []
    
    # Поиск по названиям тем
    for idx, topic in plan_bot_data.topic_list_for_pagination:
        if search_text in topic.lower():
            results.append((idx, topic, "exact"))
    
    # Поиск по индексу
    search_words = search_text.split()
    for word in search_words:
        if word in plan_bot_data.search_index:
            for idx in plan_bot_data.search_index[word]:
                topic = plan_bot_data.topic_index_map[idx]
                if (idx, topic, "exact") not in results:
                    results.append((idx, topic, "partial"))
    
    # Ограничиваем количество результатов
    results = results[:15]
    
    if not results:
        await update.message.reply_text(
            "❌ По вашему запросу ничего не найдено.\n"
            "Попробуйте:\n"
            "• Использовать другие ключевые слова\n"
            "• Проверить правописание\n"
            "• Использовать более общие термины",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 Искать снова", callback_data="search_topics"),
                InlineKeyboardButton("⬅️ Назад", callback_data="start_button")
            ]]),
            parse_mode=ParseMode.HTML
        )
        return states.CHOOSING_MODE
    
    # Показываем результаты
    text = f"🔍 <b>Найдено тем: {len(results)}</b>\n\n"
    
    # Группируем по типу совпадения
    exact_matches = [(idx, topic) for idx, topic, match_type in results if match_type == "exact"]
    partial_matches = [(idx, topic) for idx, topic, match_type in results if match_type == "partial"]
    
    kb_buttons = []
    
    if exact_matches:
        text += "📌 <b>Точные совпадения:</b>\n"
        for idx, topic in exact_matches[:5]:
            kb_buttons.append([
                InlineKeyboardButton(
                    f"📄 {topic[:50]}{'...' if len(topic) > 50 else ''}",
                    callback_data=f"topic:{context.user_data.get('mode', 'train')}:{idx}"
                )
            ])
    
    if partial_matches and len(kb_buttons) < 10:
        if exact_matches:
            text += "\n📎 <b>Частичные совпадения:</b>\n"
        for idx, topic in partial_matches[:5]:
            if len(kb_buttons) >= 10:
                break
            kb_buttons.append([
                InlineKeyboardButton(
                    f"📄 {topic[:50]}{'...' if len(topic) > 50 else ''}",
                    callback_data=f"topic:{context.user_data.get('mode', 'train')}:{idx}"
                )
            ])
    
    kb_buttons.extend([
        [InlineKeyboardButton("🔍 Искать снова", callback_data="search_topics")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="start_button")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_TOPIC
    
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню плагина."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    kb = keyboards.build_main_menu_keyboard() if not is_admin(user_id) else build_admin_menu_keyboard()
    
    menu_text = (
        "📝 <b>Задание 24 - составление сложного плана</b>\n\n"
        "Выберите режим работы:"
    )
    
    try:
        # Пытаемся отредактировать сообщение
        await query.edit_message_text(
            menu_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    except telegram.error.BadRequest as e:
        # Если не удалось отредактировать (например, это было сообщение с документом)
        if "There is no text in the message to edit" in str(e) or "Message can't be edited" in str(e):
            # Удаляем старое сообщение и отправляем новое
            try:
                await query.message.delete()
            except:
                pass  # Игнорируем ошибки удаления
            
            await query.message.reply_text(
                menu_text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
        else:
            # Если другая ошибка - пробрасываем её дальше
            raise
    
    # Очищаем временные данные
    context.user_data.pop('current_topic_index', None)
    context.user_data.pop('current_topic', None)
    context.user_data.pop('exam_mode', None)
    return states.CHOOSING_MODE

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    query = update.callback_query
    await query.answer()
    
    # Сохраняем время сессии
    if 'session_start' in context.user_data:
        session_time = (datetime.now() - context.user_data['session_start']).total_seconds() / 60
        context.user_data['total_time_minutes'] = context.user_data.get('total_time_minutes', 0) + session_time
    
    # Импортируем функцию построения главного меню
    from core.plugin_loader import build_main_menu
    kb = build_main_menu()
    
    menu_text = "👋 Что хотите потренировать?"
    
    try:
        # Пытаемся отредактировать сообщение
        await query.edit_message_text(
            menu_text,
            reply_markup=kb
        )
    except telegram.error.BadRequest as e:
        # Если не удалось отредактировать
        if "There is no text in the message to edit" in str(e) or "Message can't be edited" in str(e):
            # Удаляем старое сообщение и отправляем новое
            try:
                await query.message.delete()
            except:
                pass
            
            await query.message.reply_text(
                menu_text,
                reply_markup=kb
            )
        else:
            raise
    
    # Очищаем временные данные, но сохраняем прогресс
    temp_keys = ['current_topic_index', 'current_topic', 'mode', 'exam_mode', 'session_start', 'confirm_reset']
    for key in temp_keys:
        context.user_data.pop(key, None)
    
    return ConversationHandler.END

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    user_id = update.effective_user.id
    kb = keyboards.build_main_menu_keyboard() if not is_admin(user_id) else build_admin_menu_keyboard()
    
    await update.message.reply_text(
        "❌ Действие отменено.\n\nВыберите режим:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    # Очищаем временные данные
    context.user_data.pop('current_topic_index', None)
    context.user_data.pop('current_topic', None)
    context.user_data.pop('exam_mode', None)
    
    return states.CHOOSING_MODE

async def cmd_criteria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /criteria - показ критериев оценки."""
    await show_criteria(update, context)
    return states.CHOOSING_MODE

# ==================== АДМИНСКИЕ ФУНКЦИИ ====================

@admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика всех пользователей (только для админов)."""
    query = update.callback_query
    await query.answer()
    
    # Проверка наличия данных
    if not plan_bot_data:
        await query.edit_message_text(
            "❌ Данные планов не загружены. Статистика недоступна.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="start_button")
            ]]),
            parse_mode=ParseMode.HTML
        )
        return states.CHOOSING_MODE
    
    # Получаем данные всех пользователей из бота
    application = context.application
    
    # Собираем статистику
    total_users = 0
    active_users = 0
    total_attempts = 0
    all_scores = []
    users_by_progress = {
        '0-25%': 0,
        '26-50%': 0,
        '51-75%': 0,
        '76-99%': 0,
        '100%': 0
    }
    
    # Проходим по всем пользовательским данным
    for user_id, user_data in application.user_data.items():
        if 'practiced_topics' in user_data:
            total_users += 1
            
            # Используем функцию get_user_stats_from_data
            user_stats = get_user_stats_from_data(user_data, plan_bot_data)
            progress = user_stats['progress_percent']
            
            # Распределение по прогрессу
            if progress == 0:
                users_by_progress['0-25%'] += 1
            elif progress <= 25:
                users_by_progress['0-25%'] += 1
            elif progress <= 50:
                users_by_progress['26-50%'] += 1
            elif progress <= 75:
                users_by_progress['51-75%'] += 1
            elif progress < 100:
                users_by_progress['76-99%'] += 1
            else:
                users_by_progress['100%'] += 1
            
            # Активные пользователи (есть история оценок)
            if user_stats['scores_history']:
                active_users += 1
                total_attempts += len(user_stats['scores_history'])
                all_scores.extend([s['total'] for s in user_stats['scores_history']])
    
    # Формируем отчет
    text = "👥 <b>Статистика пользователей</b>\n\n"
    text += f"📊 Всего пользователей: {total_users}\n"
    text += f"🎯 Активных (с попытками): {active_users}\n"
    text += f"📝 Всего попыток: {total_attempts}\n"
    
    if all_scores:
        avg_score = sum(all_scores) / len(all_scores)
        text += f"⭐ Средний балл: {avg_score:.2f}/4\n"
    
    text += "\n<b>Распределение по прогрессу:</b>\n"
    for range_name, count in users_by_progress.items():
        if count > 0:
            emoji = '🟢' if '100%' in range_name else '🟡' if '76' in range_name else '🟠' if '51' in range_name else '🔴'
            text += f"{emoji} {range_name}: {count} чел.\n"
    
    # Топ тем
    text += "\n<b>Популярные темы:</b>\n"
    topic_attempts = {}
    
    for user_id, user_data in application.user_data.items():
        for score in user_data.get('scores_history', []):
            topic = score.get('topic', 'Unknown')
            topic_attempts[topic] = topic_attempts.get(topic, 0) + 1
    
    # Топ-5 тем
    if topic_attempts:
        top_topics = sorted(topic_attempts.items(), key=lambda x: x[1], reverse=True)[:5]
        for i, (topic, attempts) in enumerate(top_topics, 1):
            # Обрезаем длинные названия тем
            display_topic = topic[:40] + '...' if len(topic) > 40 else topic
            text += f"{i}. {display_topic} ({attempts} попыток)\n"
    else:
        text += "Нет данных о попытках\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Активность по дням", callback_data="admin_activity")],
        [InlineKeyboardButton("📤 Экспорт данных", callback_data="admin_export")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="start_button")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE

@admin_only
async def admin_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """График активности пользователей по дням."""
    query = update.callback_query
    await query.answer()
    
    # Собираем активность по дням
    from collections import defaultdict
    daily_activity = defaultdict(int)
    daily_users = defaultdict(set)
    
    application = context.application
    
    for user_id, user_data in application.user_data.items():
        for score in user_data.get('scores_history', []):
            timestamp = score.get('timestamp')
            if timestamp:
                try:
                    date = datetime.fromisoformat(timestamp).date()
                    daily_activity[date] += 1
                    daily_users[date].add(user_id)
                except:
                    pass
    
    # Формируем отчет
    text = "📈 <b>Активность по дням</b>\n\n"
    
    if not daily_activity:
        text += "Нет данных об активности."
    else:
        # Последние 14 дней
        sorted_days = sorted(daily_activity.keys(), reverse=True)[:14]
        
        for date in sorted_days:
            attempts = daily_activity[date]
            users = len(daily_users[date])
            
            # Визуализация
            bar_length = min(attempts // 2, 20)
            bar = "▓" * bar_length + "░" * (20 - bar_length)
            
            text += f"<code>{date.strftime('%d.%m')} {bar}</code>\n"
            text += f"      Попыток: {attempts}, Юзеров: {users}\n"
        
        # Общая статистика
        total_days = len(daily_activity)
        total_attempts = sum(daily_activity.values())
        avg_daily = total_attempts / total_days if total_days > 0 else 0
        
        text += f"\n<b>За {total_days} дней:</b>\n"
        text += f"📊 Всего попыток: {total_attempts}\n"
        text += f"📈 Среднее в день: {avg_daily:.1f}\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Статистика юзеров", callback_data="admin_stats")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="start_button")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE

@admin_only
async def admin_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт всех данных для анализа."""
    query = update.callback_query
    await query.answer("Подготовка данных...")
    
    application = context.application
    
    # Создаем структуру для экспорта
    export_data = {
        'export_date': datetime.now().isoformat(),
        'total_users': 0,
        'active_users': 0,
        'users': {}
    }
    
    # Собираем все данные
    for user_id, user_data in application.user_data.items():
        if 'practiced_topics' in user_data:
            export_data['total_users'] += 1
            
            user_stats = get_user_stats_from_data(user_data, plan_bot_data)
            
            # Проверяем, активен ли пользователь
            if user_data.get('scores_history'):
                export_data['active_users'] += 1
            
            export_data['users'][str(user_id)] = {
                'practiced_topics': list(user_data.get('practiced_topics', set())),
                'progress_percent': user_stats['progress_percent'],
                'scores_history': user_data.get('scores_history', []),
                'total_time_minutes': user_data.get('total_time_minutes', 0),
                'average_score': user_stats['average_score']
            }
    
    # Отправляем файл
    from io import BytesIO
    file_data = BytesIO(json.dumps(export_data, indent=2, ensure_ascii=False).encode('utf-8'))
    file_data.name = f"task24_full_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    # Удаляем старое сообщение
    try:
        await query.message.delete()
    except:
        pass
    
    # Получаем правильную клавиатуру для админа
    kb = build_admin_menu_keyboard()
    
    await query.message.reply_document(
        document=file_data,
        caption=(
            f"📤 Полный экспорт данных\n"
            f"Пользователей: {export_data['total_users']}\n"
            f"Активных: {export_data['active_users']}\n"
            f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Используйте кнопки ниже для навигации:"
        ),
        reply_markup=kb
    )
    
    return states.CHOOSING_MODE


async def safe_edit_or_reply(query, text: str, reply_markup=None, parse_mode=ParseMode.HTML):
    """
    Безопасно редактирует сообщение или отправляет новое, если редактирование невозможно.
    
    Args:
        query: CallbackQuery объект
        text: Текст сообщения
        reply_markup: Клавиатура (опционально)
        parse_mode: Режим парсинга (по умолчанию HTML)
    """
    try:
        # Пытаемся отредактировать сообщение
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except telegram.error.BadRequest as e:
        # Если не удалось отредактировать
        if "There is no text in the message to edit" in str(e) or "Message can't be edited" in str(e):
            # Удаляем старое сообщение и отправляем новое
            try:
                await query.message.delete()
            except:
                pass  # Игнорируем ошибки удаления
            
            await query.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        else:
            # Если другая ошибка - пробрасываем её дальше
            raise
# Вспомогательная функция для обработки noop
async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик для неактивных кнопок."""
    query = update.callback_query
    await query.answer()
    # Не меняем состояние, просто отвечаем на callback
    return None