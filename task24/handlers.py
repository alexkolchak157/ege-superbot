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
from core.document_processor import DocumentProcessor, DocumentHandlerMixin
from core.admin_tools import admin_manager, admin_only, get_admin_keyboard_extension

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
    kb = keyboards.build_main_menu_keyboard()
    # Добавляем админские кнопки если пользователь - админ
    if admin_manager.is_admin(user_id):
        admin_buttons = get_admin_keyboard_extension(user_id)
        # InlineKeyboardMarkup.inline_keyboard возвращает кортеж кортежей, поэтому
        # создаем новую клавиатуру на основе существующей и админских кнопок
        keyboard_rows = [list(row) for row in kb.inline_keyboard]
        keyboard_rows.extend(admin_buttons)
        kb = InlineKeyboardMarkup(keyboard_rows)
    
    await query.edit_message_text(
        "📝 <b>Задание 24 - составление сложного плана</b>\n\n"
        "Выберите режим работы:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def cmd_start_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start_plan."""
    # Инициализация времени сессии
    if 'session_start' not in context.user_data:
        context.user_data['session_start'] = datetime.now()
    
    user_id = update.effective_user.id
    kb = keyboards.build_main_menu_keyboard()
    
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
    thinking_msg = await update.message.reply_text("🧠 Анализирую ваш план...")
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
                InlineKeyboardButton("🔄 Попробовать снова", callback_data="retry_plan"),
                InlineKeyboardButton("📋 К темам", callback_data="back_to_choice")
            ]])
        )
        
        return states.AWAITING_FEEDBACK

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

async def next_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к следующей теме."""
    query = update.callback_query
    await query.answer()
    
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
    
    # Удаляем все предыдущие сообщения перед показом меню
    await delete_previous_messages(context, query.message.chat_id)
    
    user_id = query.from_user.id
    kb = keyboards.build_main_menu_keyboard()
    
    menu_text = (
        "📝 <b>Задание 24 - составление сложного плана</b>\n\n"
        "Выберите режим работы:"
    )
    
    # Отправляем новое сообщение с меню
    await query.message.chat.send_message(
        menu_text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    # Очищаем временные данные
    context.user_data.pop('current_topic_index', None)
    context.user_data.pop('current_topic', None)
    context.user_data.pop('exam_mode', None)
    
    return states.CHOOSING_MODE

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    query = update.callback_query
    await query.answer()
    
    try:
        # Удаляем все сообщения task24 перед переходом в главное меню
        await delete_previous_messages(context, query.message.chat_id)
        
        # Импортируем функцию главного меню
        from core.plugin_loader import build_main_menu
        
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

async def retry_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повторить попытку составления плана для той же темы."""
    query = update.callback_query
    await query.answer()
    
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
    user_id = update.effective_user.id
    
    # ОБНОВЛЕННЫЙ КОД
    kb = keyboards.build_main_menu_keyboard()
    if admin_manager.is_admin(user_id):
        admin_buttons = get_admin_keyboard_extension(user_id)
        keyboard_rows = [list(row) for row in kb.inline_keyboard]
        keyboard_rows.extend(admin_buttons)
        kb = InlineKeyboardMarkup(keyboard_rows)
    
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
        await update.callback_query.answer("✅ Прогресс пользователя сброшен", show_alert=True)
    else:
        await update.callback_query.answer("❌ Пользователь не найден", show_alert=True)


# Пример функции, которая проверяет админские права внутри
async def export_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт прогресса."""
    query = update.callback_query
    await query.answer()
    
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
# Вспомогательная функция для обработки noop
async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик для неактивных кнопок."""
    query = update.callback_query
    await query.answer()
    # Не меняем состояние, просто отвечаем на callback
    return None
