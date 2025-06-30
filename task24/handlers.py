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
from .checker import PlanBotData, evaluate_plan, FEEDBACK_KB, evaluate_plan_with_ai
from . import keyboards
from core.document_processor import DocumentProcessor, DocumentHandlerMixin
from core.admin_tools import admin_manager, admin_only, get_admin_keyboard_extension
from core.universal_ui import UniversalUIComponents, AdaptiveKeyboards, MessageFormatter
from core.ui_helpers import (
    show_thinking_animation,
    show_extended_thinking_animation,  # Добавить
    show_streak_notification,
    get_personalized_greeting,
    get_motivational_message,
    create_visual_progress
)
from core.plugin_loader import build_main_menu
from core.state_validator import validate_state_transition, state_validator
import math
from core.error_handler import safe_handler, auto_answer_callback

logger = logging.getLogger(__name__)

# Глобальные данные
plan_bot_data = None

async def delete_previous_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, keep_message_id: Optional[int] = None):
    """Удаляет предыдущие сообщения диалога."""
    if not hasattr(context, 'bot') or not context.bot:
        logger.warning("Bot instance not available for message deletion")
        return
    
    # Список ключей с ID сообщений для удаления
    message_keys = [
        'task24_topic_msg_id',      # Сообщение с заданием/темой
        'task24_plan_msg_id',       # Сообщение с планом пользователя
        'task24_thinking_msg_id',   # Сообщение "Анализирую..."
        'task24_result_msg_id'      # Сообщение с результатом (если есть)
    ]
    
    messages_to_delete = []
    deleted_count = 0
    
    for key in message_keys:
        msg_id = context.user_data.get(key)
        if msg_id and msg_id != keep_message_id:
            messages_to_delete.append((key, msg_id))
    
    # Удаляем сообщения
    for key, msg_id in messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            deleted_count += 1
            logger.debug(f"Deleted {key}: {msg_id}")
        except Exception as e:
            logger.debug(f"Failed to delete {key} {msg_id}: {e}")
    
    # Очищаем контекст
    for key in message_keys:
        context.user_data.pop(key, None)
    
    logger.info(f"Task24: Deleted {deleted_count}/{len(messages_to_delete)} messages")

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
    admin_manager._load_admin_ids()
    
    return data_loaded  # Возвращаем статус загрузки

@safe_handler()
async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Точка входа в задание 24 из главного меню."""
    query = update.callback_query
    
    # Инициализация данных если нужно
    if not plan_bot_data:
        await load_data()
    
    # Проверка подписки если включена
    if hasattr(core_utils, 'check_subscription'):
        from core.config import REQUIRED_CHANNEL
        if not await core_utils.check_subscription(query.from_user.id, context.bot):
            await core_utils.send_subscription_required(query, REQUIRED_CHANNEL)
            return ConversationHandler.END
    
    # Инициализация времени сессии
    if 'session_start' not in context.user_data:
        context.user_data['session_start'] = datetime.now()
    
    # Получаем статистику пользователя
    practiced_indices = context.user_data.get('practiced_topics', set())
    total_topics = len(plan_bot_data.topic_list_for_pagination) if plan_bot_data else 0
    results = context.user_data.get('task24_results', [])
    
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r.get('score', 0) for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(practiced_indices) / total_topics * 100) if total_topics > 0 else 0
    }
    
    # Персонализированное приветствие
    greeting = get_personalized_greeting(user_stats)
    text = greeting + MessageFormatter.format_welcome_message(
        "задание 24",
        is_new_user=user_stats['total_attempts'] == 0
    )
    
    # Строим унифицированную клавиатуру
    kb = keyboards.build_main_menu_keyboard(user_stats)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def cmd_start_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start_plan."""
    # Инициализация данных если нужно
    if not plan_bot_data:
        await load_data()
    
    # Получаем статистику пользователя
    practiced_indices = context.user_data.get('practiced_topics', set())
    total_topics = len(plan_bot_data.topic_list_for_pagination) if plan_bot_data else 0
    results = context.user_data.get('task24_results', [])
    
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r.get('score', 0) for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(practiced_indices) / total_topics * 100) if total_topics > 0 else 0
    }
    
    # Персонализированное приветствие
    greeting = get_personalized_greeting(user_stats)
    text = greeting + MessageFormatter.format_welcome_message(
        "задание 24",
        is_new_user=user_stats['total_attempts'] == 0
    )
    
    # Строим унифицированную клавиатуру
    kb = keyboards.build_main_menu_keyboard(user_stats)
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def train_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим тренировки."""
    query = update.callback_query
    
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


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def show_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим просмотра эталонов."""
    query = update.callback_query
    
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
    return states.CHOOSING_TOPIC

@safe_handler()
async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка всех тем."""
    query = update.callback_query
    
    if not plan_bot_data:
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
        InlineKeyboardButton("⬅️ Назад в меню", callback_data="t24_menu")
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

@safe_handler()
@validate_state_transition({states.CHOOSING_TOPIC})
async def select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы."""
    query = update.callback_query
    
    data = query.data
    if not data.startswith("t24_topic_"):
        logger.error(f"Неправильный формат callback_data: {query.data}")
        return

    parts = data[len("t24_topic_"):].split(":")
    if len(parts) < 2:
        logger.error(f"Неправильный формат callback_data: {query.data}")
        return

    mode = parts[0]
    topic_idx = int(parts[1])
    
    # Получаем тему по индексу
    topic_name = plan_bot_data.topic_index_map.get(topic_idx)
    if not topic_name:
        return
    
    # Сохраняем в контекст
    context.user_data['current_topic_index'] = topic_idx
    context.user_data['current_topic'] = topic_name
    
    if mode == 'train':
        # Сохраняем режим тренировки
        context.user_data['mode'] = 'train'
        
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
        
        # ВАЖНО: Сохраняем ID сообщения с заданием
        context.user_data['task24_topic_msg_id'] = query.message.message_id
        
        return states.AWAITING_PLAN
    
    elif mode == 'show':
        # Режим просмотра - показываем эталон
        # ИСПРАВЛЕНО: передаем query вместо update
        return await show_etalon_plan(query, context, topic_idx)

@safe_handler()
@validate_state_transition({states.CHOOSING_TOPIC})
async def start_training_from_etalon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать тренировку после просмотра эталона."""
    query = update.callback_query
    
    # Извлекаем индекс темы
    topic_idx = int(query.data.split(':')[1])
    topic_name = plan_bot_data.topic_index_map.get(topic_idx)
    
    if not topic_name:
        await query.answer("❌ Тема не найдена", show_alert=True)
        return states.CHOOSING_TOPIC
    
    # Устанавливаем режим тренировки
    context.user_data['mode'] = 'train'
    context.user_data['current_topic_index'] = topic_idx
    context.user_data['current_topic'] = topic_name
    
    # Показываем задание
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
    
    context.user_data['task24_topic_msg_id'] = query.message.message_id
    
    return states.AWAITING_PLAN

async def show_etalon_plan(query, context, topic_idx):
    """Показ эталонного плана."""
    topic_name = plan_bot_data.topic_index_map.get(topic_idx)
    if not topic_name:
        await query.answer("❌ Тема не найдена", show_alert=True)
        return states.CHOOSING_TOPIC
    
    plan_data = plan_bot_data.get_plan_data(topic_name)
    if not plan_data:
        await query.answer("❌ План не найден", show_alert=True)
        return states.CHOOSING_TOPIC
    
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
    
    # ИСПРАВЛЕННЫЕ КНОПКИ с короткими callback_data
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Потренироваться с этой темой", callback_data=f"t24_topic_train:{topic_idx}")],
        [InlineKeyboardButton("🎲 Другая тема", callback_data="t24_nav_rnd:show")],  # random -> rnd
        [InlineKeyboardButton("📚 Выбрать тему", callback_data="t24_nav_cb:show")],  # choose_block -> cb
        [InlineKeyboardButton("🏠 В меню", callback_data="t24_menu")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_TOPIC

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def navigate_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по темам."""
    query = update.callback_query
    
    # Проверка загрузки данных
    if not plan_bot_data or not hasattr(plan_bot_data, 'topic_list_for_pagination'):
        await query.edit_message_text(
            "❌ Данные планов не загружены. Обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
            ]])
        )
        return ConversationHandler.END
    
    data = query.data
    if not data.startswith("t24_nav_"):
        logger.error(f"Неправильный формат callback_data: {query.data}")
        return states.CHOOSING_TOPIC

    parts = data[len("t24_nav_"):].split(":")
    action = parts[0]
    
    if action == "choose_block":
        mode = parts[1]
        kb = keyboards.build_block_selection_keyboard(mode)
        await query.edit_message_text(
            "📚 Выберите блок тем:",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    
    elif action == "show_all":
        mode = parts[1]
        page = 0
        practiced = context.user_data.get('practiced_topics', set())
        text, kb = keyboards.build_topic_page_keyboard(
            mode, page, plan_bot_data, practiced
        )
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    
    elif action == "back_to_choice":
        # Возвращаемся к выбору способа поиска темы
        mode = parts[1] if len(parts) > 1 else context.user_data.get('mode', 'show')
        kb = keyboards.build_initial_choice_keyboard(mode)
        await query.edit_message_text(
            f"👁 <b>Режим {'тренировки' if mode == 'train' else 'просмотра эталонов'}</b>\n\n"
            "Как вы хотите выбрать тему?",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        return states.CHOOSING_TOPIC

    elif action == "random":
        mode = parts[1]
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
                return await show_etalon_plan(update, context, idx)

    elif action in ["all", "block"]:
        mode = parts[1]
        page = int(parts[2])
        block_name = parts[3] if len(parts) > 3 else None
        
        practiced = context.user_data.get('practiced_topics', set())
        text, kb = keyboards.build_topic_page_keyboard(
            mode, page, plan_bot_data, practiced, block_name
        )
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    
    elif action == "select_block":
        mode = parts[1]
        block_name = ":".join(parts[2:])
        
        practiced = context.user_data.get('practiced_topics', set())
        text, kb = keyboards.build_topic_page_keyboard(
            mode, 0, plan_bot_data, practiced, block_name
        )
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    
    elif action == "back_to_main":
        mode = parts[1] if len(parts) > 1 else 'train'
        kb = keyboards.build_initial_choice_keyboard(mode)
        await query.edit_message_text(
            f"🎯 <b>Режим {'тренировки' if mode == 'train' else 'просмотра'}</b>\n\n"
            "Как вы хотите выбрать тему?",
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    
    elif action == "t24_back_to_choice":
        return await train_mode(update, context) if context.user_data.get('mode') == 'train' else await show_mode(update, context)
    
    return states.CHOOSING_TOPIC


@safe_handler()
async def handle_plan_enhanced(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка плана пользователя (текст или документ)."""
    
    # Если это документ - перенаправляем
    if update.message.document:
        return await handle_plan_document(update, context)
    
    # Оригинальная логика handle_plan
    user_plan_text = update.message.text.strip()
    
    # Сохраняем ID сообщения с планом пользователя
    context.user_data['task24_plan_msg_id'] = update.message.message_id
    
    if not user_plan_text:
        await update.message.reply_text(
            "❌ Вы прислали пустое сообщение.\n\n"
            "📝 Пожалуйста, отправьте ваш план текстом или документом (PDF, DOCX, TXT)."
        )
        return states.AWAITING_PLAN
    
    # Проверка минимальной длины
    if len(user_plan_text) < 50:
        await update.message.reply_text(
            "❌ План слишком короткий. Пожалуйста, составьте развернутый план.\n\n"
            "💡 Совет: Вы можете отправить план документом, если удобнее."
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
    thinking_msg = await show_extended_thinking_animation(
        update.message,  # ИСПРАВЛЕНО: было user_message 
        "Анализирую план",
        duration=45  # Планы проверяются быстрее
    )
    context.user_data['task24_thinking_msg_id'] = thinking_msg.message_id
    
    # НЕ УДАЛЯЕМ сообщения здесь! Удаление будет происходить при выборе следующего действия
    
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
        k2_match = re.search(r'К2.*?(\d+)/3', feedback)
        
        k1_score = int(k1_match.group(1)) if k1_match else 0
        k2_score = int(k2_match.group(1)) if k2_match else 0
        total_score = k1_score + k2_score
        
        # Сохраняем результат
        context.user_data['last_plan_result'] = {
            'topic': topic_name,
            'k1': k1_score,
            'k2': k2_score,
            'total': total_score,
            'timestamp': datetime.now()
        }
        
        # Добавляем тему в изученные
        if 'practiced_topics' not in context.user_data:
            context.user_data['practiced_topics'] = set()
        context.user_data['practiced_topics'].add(topic_name)
        
        # Удаляем сообщение "Анализирую..."
        try:
            await thinking_msg.delete()
        except Exception as e:
            logger.debug(f"Failed to delete thinking message: {e}")
        
        # Отправляем результат с клавиатурой действий
        result_msg = await update.message.reply_text(
            feedback,
            reply_markup=FEEDBACK_KB,
            parse_mode=ParseMode.HTML
        )
        
        # Сохраняем ID сообщения с результатом
        context.user_data['task24_result_msg_id'] = result_msg.message_id
        save_result(context, topic_name, evaluation_result.score)
        return states.AWAITING_FEEDBACK
        
    except Exception as e:
        logger.error(f"Ошибка при проверке плана: {e}", exc_info=True)
        
        # Удаляем сообщение "Анализирую..."
        try:
            await thinking_msg.delete()
        except Exception as e2:
            logger.debug(f"Failed to delete thinking message: {e2}")
        
        await update.message.reply_text(
            "❌ Произошла ошибка при проверке плана. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Попробовать снова", callback_data="t24_retry"),
                InlineKeyboardButton("📋 К темам", callback_data="t24_back_to_choice")
            ]])
        )
        
        return states.AWAITING_FEEDBACK

@safe_handler()
async def handle_plan_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка плана, присланного документом."""
    
    # Проверяем состояние
    topic_name = context.user_data.get('current_topic')
    if not topic_name:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана. Используйте /start_plan"
        )
        return ConversationHandler.END
    
    # Используем миксин для обработки документа
    extracted_text = await DocumentHandlerMixin.handle_document_answer(
        update, 
        context,
        task_name="план"
    )
    
    if not extracted_text:
        # Ошибка уже показана пользователю
        return states.AWAITING_PLAN
    
    # Валидация содержимого для плана
    is_valid, error_msg = DocumentHandlerMixin.validate_document_content(
        extracted_text,
        task_type="plan"
    )
    
    if not is_valid:
        await update.message.reply_text(f"❌ {error_msg}")
        return states.AWAITING_PLAN
    
    # Сохраняем текст и передаем в обычный обработчик
    # Создаем фиктивное обновление с текстом
    update.message.text = extracted_text
    
    # Вызываем стандартный обработчик планов
    return await handle_plan(update, context)

@safe_handler()
async def next_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к следующей теме."""
    query = update.callback_query
    
    # Удаляем все предыдущие сообщения перед показом выбора новой темы
    await delete_previous_messages(context, query.message.chat_id)
    
    # Возвращаемся к выбору темы в режиме тренировки
    context.user_data['mode'] = 'train'
    kb = keyboards.build_initial_choice_keyboard('train')
    
    # Отправляем новое сообщение с выбором темы
    await query.message.chat.send_message(
        "🎯 <b>Режим тренировки</b>\n\n"
        "Выберите следующую тему:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_TOPIC

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
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
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t24_menu")
        ]])
        await query.edit_message_text(
            criteria_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(criteria_text, parse_mode=ParseMode.HTML)
    
    return states.CHOOSING_MODE

@safe_handler()
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
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t24_menu")
    ]])
    
    await safe_edit_or_reply(query, help_text, kb, ParseMode.HTML)
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def show_block_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику по блокам тем с универсальными компонентами."""
    query = update.callback_query
    
    stats = get_user_stats(context)
    practiced = context.user_data.get('practiced_topics', set())
    
    # Используем универсальное форматирование
    text = MessageFormatter.format_progress_message({
        'total_attempts': len(stats['scores_history']),
        'average_score': stats['average_score'],
        'completed': len(practiced),
        'total': stats['total_topics'],
        'total_time': stats['total_time_minutes'],
        'top_results': [
            {
                'topic': score['topic'],
                'score': score['total'],
                'max_score': 4
            }
            for score in sorted(stats['scores_history'], 
                              key=lambda x: x['total'], reverse=True)[:3]
        ]
    }, "заданию 24")
    
    # Детализация по блокам с визуальными элементами
    text += "\n\n<b>📚 Прогресс по блокам:</b>"
    
    for block_name, topics in plan_bot_data.topics_by_block.items():
        completed = sum(1 for idx, _ in topics if idx in practiced)
        total = len(topics)
        
        # Прогресс-бар для блока
        progress_bar = UniversalUIComponents.create_progress_bar(
            completed, total, width=5, show_percentage=False
        )
        
        # Цветовой индикатор
        color = UniversalUIComponents.get_color_for_score(completed, total)
        
        text += f"\n{color} <b>{block_name}:</b> {progress_bar} {completed}/{total}"
    
    # Используем новую унифицированную клавиатуру
    practiced_indices = context.user_data.get('practiced_topics', set())
    total_topics = len(plan_bot_data.topic_index_map)
    kb = keyboards.build_progress_keyboard(practiced_indices, total_topics)
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE


@safe_handler()
async def show_detailed_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную статистику по всем темам с пагинацией."""
    query = update.callback_query
    
    # Получаем страницу из callback_data (формат: show_detailed_progress:page)
    callback_parts = query.data.split(':')
    page = int(callback_parts[1]) if len(callback_parts) > 1 else 0
    
    practiced = context.user_data.get('practiced_topics', set())
    all_topics = list(plan_bot_data.get_all_topics_list())
    
    # Параметры пагинации
    topics_per_page = 30  # Показываем по 30 тем на страницу
    total_pages = math.ceil(len(all_topics) / topics_per_page)
    
    # Получаем темы для текущей страницы
    start_idx = page * topics_per_page
    end_idx = min(start_idx + topics_per_page, len(all_topics))
    page_topics = all_topics[start_idx:end_idx]
    
    # Формируем текст
    lines = []
    lines.append(f"📋 <b>Детальный прогресс</b> (стр. {page + 1}/{total_pages})")
    lines.append(f"<i>Всего тем: {len(all_topics)}, пройдено: {len(practiced)}</i>\n")
    
    # Группируем по блокам для лучшей читаемости
    current_block = None
    for idx, name in page_topics:
        # Определяем блок темы
        block_name = None
        for block, topics in plan_bot_data.topics_by_block.items():
            if any(t[0] == idx for t in topics):
                block_name = block
                break
        
        # Добавляем заголовок блока если новый
        if block_name != current_block:
            current_block = block_name
            lines.append(f"\n<b>{block_name}:</b>")
        
        # Добавляем тему
        mark = '✅' if idx in practiced else '❌'
        lines.append(f"{mark} {name}")
    
    text = "\n".join(lines)
    
    # Создаем клавиатуру с навигацией
    keyboard = []
    
    # Навигационные кнопки
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"show_detailed_progress:{page-1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️ Вперед", callback_data=f"show_detailed_progress:{page+1}"))
    
    if nav_row:
        keyboard.append(nav_row)
    
    # Кнопка экспорта и возврата
    keyboard.append([
        InlineKeyboardButton("📤 Экспорт в файл", callback_data="export_progress"),
        InlineKeyboardButton("🔙 К статистике", callback_data="t24_progress")
    ])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE


@safe_handler()
async def show_completed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список пройденных тем."""
    query = update.callback_query
    
    scores_history = context.user_data.get('scores_history', [])
    
    if not scores_history:
        text = "📋 <b>Выполненные темы</b>\n\nВы еще не выполняли задания."
    else:
        text = "📋 <b>Выполненные темы</b>\n\n"
        
        for score_data in scores_history[-10:]:  # Последние 10
            score = score_data['total']
            topic = score_data['topic']
            
            # Используем универсальную визуализацию
            score_visual = UniversalUIComponents.create_score_visual(score, 4)
            color = UniversalUIComponents.get_color_for_score(score, 4)
            
            text += f"{color} {topic}: {score_visual}\n"
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t24_progress")
    ]])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE


@safe_handler()
async def show_remaining(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список оставшихся тем с пагинацией."""
    query = update.callback_query
    
    # Получаем страницу из callback_data (формат: show_remaining:page)
    callback_parts = query.data.split(':')
    page = int(callback_parts[1]) if len(callback_parts) > 1 else 0
    
    practiced = context.user_data.get('practiced_topics', set())
    remaining = [(idx, name) for idx, name in plan_bot_data.get_all_topics_list() if idx not in practiced]
    
    if not remaining:
        text = "📝 <b>Оставшиеся темы</b>\n\n✅ Поздравляем! Все темы изучены!"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="t24_progress")]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return states.CHOOSING_MODE
    
    # Параметры пагинации
    topics_per_page = 25
    total_pages = math.ceil(len(remaining) / topics_per_page)
    
    # Получаем темы для текущей страницы
    start_idx = page * topics_per_page
    end_idx = min(start_idx + topics_per_page, len(remaining))
    page_topics = remaining[start_idx:end_idx]
    
    # Формируем текст
    lines = []
    lines.append(f"📝 <b>Оставшиеся темы</b> (стр. {page + 1}/{total_pages})")
    lines.append(f"<i>Осталось изучить: {len(remaining)} тем</i>\n")
    
    # Группируем по блокам
    current_block = None
    for idx, name in page_topics:
        # Определяем блок темы
        block_name = None
        for block, topics in plan_bot_data.topics_by_block.items():
            if any(t[0] == idx for t in topics):
                block_name = block
                break
        
        # Добавляем заголовок блока если новый
        if block_name != current_block:
            current_block = block_name
            lines.append(f"\n<b>{block_name}:</b>")
        
        lines.append(f"• {name}")
    
    text = "\n".join(lines)
    
    # Создаем клавиатуру с навигацией
    keyboard = []
    
    # Навигационные кнопки
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Пред.", callback_data=f"show_remaining:{page-1}"))
    
    nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("След. ➡️", callback_data=f"show_remaining:{page+1}"))
    
    if nav_row:
        keyboard.append(nav_row)
    
    # Кнопка возврата
    keyboard.append([InlineKeyboardButton("🔙 К статистике", callback_data="t24_progress")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return states.CHOOSING_MODE

@safe_handler()
async def reset_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс прогресса с подтверждением."""
    query = update.callback_query
    
    # Проверяем, есть ли флаг подтверждения
    if context.user_data.get('confirm_reset'):
        # Сброс подтвержден
        context.user_data['practiced_topics'] = set()
        context.user_data['scores_history'] = []
        context.user_data['total_time_minutes'] = 0
        context.user_data.pop('confirm_reset', None)
        
        
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
                InlineKeyboardButton("❌ Да, сбросить", callback_data="t24_reset_progress"),
                InlineKeyboardButton("✅ Отмена", callback_data="t24_cancel_reset")
            ]
        ])
        
        await query.edit_message_text(
            warning_text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    
    return states.CHOOSING_MODE

@safe_handler()
async def confirm_reset_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение сброса прогресса."""
    query = update.callback_query
    
    # Сбрасываем прогресс
    context.user_data['practiced_topics'] = set()
    context.user_data['task24_results'] = []  # Сбрасываем историю результатов
    context.user_data['correct_streak'] = 0   # Сбрасываем серию
    
    await query.answer("✅ Прогресс сброшен!", show_alert=True)
    
    # Возвращаемся в меню
    return await return_to_menu(update, context)

@safe_handler()
async def cancel_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена сброса прогресса."""
    query = update.callback_query
    
    context.user_data.pop('confirm_reset', None)
    
    user_id = query.from_user.id
    kb = keyboards.build_main_menu_keyboard()
    
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

@safe_handler()
async def export_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт прогресса пользователя."""
    query = update.callback_query
    
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
    kb = keyboards.build_main_menu_keyboard()
    
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

@safe_handler()
async def search_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск тем по ключевым словам."""
    query = update.callback_query
    
    await query.edit_message_text(
        "🔍 <b>Поиск темы</b>\n\n"
        "Отправьте ключевые слова для поиска.\n"
        "Например: <i>политика партии</i>",
        reply_markup=keyboards.build_search_keyboard(),
        parse_mode=ParseMode.HTML
    )
    return states.AWAITING_SEARCH

def _format_evaluation_feedback(k1: int, k2: int, missing: list, topic_name: str) -> str:
    """Форматирует отзыв о плане используя универсальные компоненты."""
    total_score = k1 + k2
    
    # Используем универсальное форматирование
    text = MessageFormatter.format_result_message(
        score=total_score,
        max_score=4,
        topic=topic_name,
        details={
            "К1 (Раскрытие темы)": f"{k1}/3",
            "К2 (Корректность)": f"{k2}/1"
        }
    )
    
    # Добавляем специфичные для task24 детали
    if k1 < 3 and missing:
        text += "\n\n📝 <b>Пропущенные пункты:</b>"
        for item in missing:
            text += f"\n• {item}"
    
    return text

def save_result(context: ContextTypes.DEFAULT_TYPE, topic_name: str, score: int, max_score: int = 4):
    """Сохранение результата в историю."""
    if 'task24_results' not in context.user_data:
        context.user_data['task24_results'] = []
    
    result = {
        'topic': topic_name,
        'score': score,
        'max_score': max_score,
        'timestamp': datetime.now().isoformat(),
        'topic_index': context.user_data.get('current_topic_index')
    }
    
    context.user_data['task24_results'].append(result)
    
    # Обновляем серию правильных ответов
    if score >= 3:  # Хороший результат
        context.user_data['correct_streak'] = context.user_data.get('correct_streak', 0) + 1
    else:
        context.user_data['correct_streak'] = 0

@safe_handler()
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
                InlineKeyboardButton("🔍 Искать снова", callback_data="t24_search"),
                InlineKeyboardButton("⬅️ Назад", callback_data="t24_menu")
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
                    callback_data=f"t24_topic_{context.user_data.get('mode', 'train')}:{idx}"
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
                    callback_data=f"t24_topic_{context.user_data.get('mode', 'train')}:{idx}"
                )
            ])
    
    kb_buttons.extend([
        [InlineKeyboardButton("🔍 Искать снова", callback_data="t24_search")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="t24_menu")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_TOPIC
    
@safe_handler()
async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню плагина с унифицированным интерфейсом."""
    query = update.callback_query
    
    # Очищаем временные данные
    context.user_data.pop('current_topic_index', None)
    context.user_data.pop('current_topic', None)
    context.user_data.pop('exam_mode', None)
    
    # Получаем статистику пользователя
    practiced_indices = context.user_data.get('practiced_topics', set())
    total_topics = len(plan_bot_data.topic_list_for_pagination) if plan_bot_data else 0
    
    # Получаем историю результатов если есть
    results = context.user_data.get('task24_results', [])
    
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r.get('score', 0) for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(practiced_indices) / total_topics * 100) if total_topics > 0 else 0
    }
    
    # Персонализированное приветствие
    greeting = get_personalized_greeting(user_stats)
    text = greeting + MessageFormatter.format_welcome_message(
        "задание 24",
        is_new_user=user_stats['total_attempts'] == 0
    )
    
    # Используем унифицированную клавиатуру
    kb = keyboards.build_main_menu_keyboard(user_stats)
    
    try:
        await query.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    except telegram.error.BadRequest as e:
        if "Message can't be edited" in str(e) or "Message to edit not found" in str(e):
            await query.message.reply_text(
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
        else:
            raise
    
    return states.CHOOSING_MODE

@safe_handler()
@validate_state_transition({states.CHOOSING_MODE, states.CHOOSING_BLOCK, states.CHOOSING_TOPIC, states.ANSWERING, states.ANSWERING_PARTS})
async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    query = update.callback_query
    
    try:
        # Удаляем все сообщения task24 перед переходом в главное меню
        await delete_previous_messages(context, query.message.chat_id)
        
        # Очищаем контекст пользователя от данных task24
        keys_to_remove = [
            'current_topic_index', 'current_topic', 'exam_mode',
            'mode', 'practiced_topics', 'last_plan_result',
            'task24_topic_msg_id', 'task24_plan_msg_id',
            'task24_thinking_msg_id', 'task24_result_msg_id'
        ]
        for key in keys_to_remove:
            context.user_data.pop(key, None)
        
        # Показываем главное меню
        kb = build_main_menu()
        
        # Отправляем новое сообщение с главным меню
        await query.message.chat.send_message(
            "👋 Что хотите потренировать?",
            reply_markup=kb
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Ошибка при возврате в главное меню: {e}")
        # В случае ошибки просто показываем текст
        await query.message.reply_text(
            "Произошла ошибка. Используйте /start для возврата в главное меню."
        )
        return ConversationHandler.END

async def t24_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повторить попытку составления плана для той же темы."""
    query = update.callback_query
    
    # Удаляем все предыдущие сообщения
    await delete_previous_messages(context, query.message.chat_id)
    
    topic_name = context.user_data.get('current_topic')
    topic_index = context.user_data.get('current_topic_index')
    
    if not topic_name:
        await query.message.chat.send_message(
            "❌ Ошибка: тема не найдена. Выберите тему заново.",
            reply_markup=keyboards.build_initial_choice_keyboard('train')
        )
        return states.CHOOSING_TOPIC
    
    # Отправляем задание заново
    task_text = f"""📝 <b>Задание 24</b>

<b>Тема:</b> {topic_name}

Используя обществоведческие знания, составьте сложный план, позволяющий раскрыть по существу тему «{topic_name}».

<b>Требования:</b>
• Минимум 3 пункта (из них 2 детализированных)
• В каждом детализированном пункте минимум 3 подпункта

<b>Пример структуры:</b>
<code>1. Понятие безработицы
2. Виды безработицы:
   а) фрикционная
   б) структурная
   в) циклическая
3. Последствия безработицы:
   а) для экономики
   б) для общества
   в) для личности</code>

💡 <i>Отправьте ваш план одним сообщением</i>"""
    
    await query.message.chat.send_message(
        task_text,
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_PLAN

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    # Получаем статистику
    practiced_indices = context.user_data.get('practiced_topics', set())
    total_topics = len(plan_bot_data.topic_list_for_pagination) if plan_bot_data else 0
    results = context.user_data.get('task24_results', [])
    
    user_stats = {
        'total_attempts': len(results),
        'average_score': sum(r.get('score', 0) for r in results) / len(results) if results else 0,
        'streak': context.user_data.get('correct_streak', 0),
        'weak_topics_count': 0,
        'progress_percent': int(len(practiced_indices) / total_topics * 100) if total_topics > 0 else 0
    }
    
    # Используем унифицированную клавиатуру
    kb = keyboards.build_main_menu_keyboard(user_stats)
    
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

@admin_only
async def force_reset_user_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительный сброс прогресса пользователя (только для админов)."""
    # Эта функция автоматически проверит права админа
    user_id = int(update.callback_query.data.split(":")[-1])
    
    # Сброс данных пользователя
    if user_id in context.application.user_data:
        context.application.user_data[user_id].clear()
    pass  # или можно добавить логирование

@safe_handler()
async def export_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    user_id = query.from_user.id
    
    # Обычный экспорт для всех пользователей
    stats = get_user_stats(context)
    practiced = context.user_data.get('practiced_topics', set())
    
    # Базовые данные для экспорта
    progress_data = {
        'user_info': {
            'user_id': user_id,
            'export_date': datetime.now().isoformat()
        },
        'statistics': {
            'practiced_topics': list(practiced),
            'total_topics': stats['total_topics'],
            'progress_percent': stats['progress_percent'],
            'average_score': stats['average_score'],
            'total_time_minutes': stats['total_time_minutes']
        },
        'scores_history': stats['scores_history']
    }
    
    # Если админ - добавляем расширенные данные
    if admin_manager.is_admin(user_id):
        progress_data['admin_export'] = True
        progress_data['detailed_topics'] = {}
        
        # Добавляем детализацию по блокам для админов
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
            
            progress_data['detailed_topics'][block_name] = block_data
    
    # Отправляем файл
    from io import BytesIO
    file_data = BytesIO(json.dumps(progress_data, indent=2, ensure_ascii=False).encode('utf-8'))
    file_data.name = f"progress_task24_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    await query.message.reply_document(
        document=file_data,
        caption=(
            f"📤 Ваш прогресс\n"
            f"Пройдено: {stats['progress_percent']}%\n"
            f"Средний балл: {stats['average_score']:.1f}\n"
            + ("\n🔧 Админский экспорт с расширенными данными" if admin_manager.is_admin(user_id) else "")
        )
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

@safe_handler()
async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для callback_query, которые не требуют действий."""
    query = update.callback_query
    await query.answer()
    return  # Возвращаем текущее состояние без изменений