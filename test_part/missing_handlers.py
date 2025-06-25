# test_part/missing_handlers.py
"""
Реализация недостающих callback обработчиков для тестовой части.
"""

import logging
import io
import csv
from datetime import datetime
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from core import states
from core.error_handler import safe_handler
from core.state_validator import validate_state_transition
from core import db
from core.universal_ui import UniversalUIComponents, AdaptiveKeyboards, MessageFormatter
from .utils import get_user_mistakes, format_mistake_stats

logger = logging.getLogger(__name__)


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def detailed_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальный отчет по ошибкам."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем все ошибки пользователя
    mistakes = await get_user_mistakes(user_id)
    
    if not mistakes:
        text = "📊 <b>Детальный отчет</b>\n\nУ вас пока нет ошибок для анализа!"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="test_progress")
        ]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return states.CHOOSING_MODE
    
    # Группируем ошибки по темам
    mistakes_by_topic = {}
    for mistake in mistakes:
        topic = mistake.get('topic', 'Без темы')
        if topic not in mistakes_by_topic:
            mistakes_by_topic[topic] = []
        mistakes_by_topic[topic].append(mistake)
    
    # Формируем отчет
    text = "📊 <b>Детальный анализ ошибок</b>\n\n"
    
    for topic, topic_mistakes in mistakes_by_topic.items():
        text += f"📌 <b>{topic}</b>\n"
        text += f"   Ошибок: {len(topic_mistakes)}\n"
        
        # Показываем типы ошибок
        error_types = {}
        for m in topic_mistakes:
            error_type = m.get('error_type', 'Неверный ответ')
            error_types[error_type] = error_types.get(error_type, 0) + 1
        
        for error_type, count in error_types.items():
            text += f"   • {error_type}: {count}\n"
        text += "\n"
    
    # Рекомендации
    text += "💡 <b>Рекомендации:</b>\n"
    if len(mistakes_by_topic) > 3:
        text += "• Сосредоточьтесь на 2-3 темах с наибольшим количеством ошибок\n"
    text += "• Используйте режим 'Работа над ошибками' для тренировки\n"
    text += "• Изучите теорию по проблемным темам\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Экспорт в CSV", callback_data="export_csv")],
        [InlineKeyboardButton("🔄 Работа над ошибками", callback_data="work_mistakes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="test_progress")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспортирует статистику и ошибки в CSV файл."""
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer("Генерирую отчет...")
    
    # Получаем данные
    mistakes = await get_user_mistakes(user_id)
    stats = await db.get_user_stats(user_id)
    
    # Создаем CSV в памяти
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Заголовок
    writer.writerow(['Экспорт статистики', f'Пользователь ID: {user_id}', f'Дата: {datetime.now().strftime("%Y-%m-%d %H:%M")}'])
    writer.writerow([])
    
    # Общая статистика
    writer.writerow(['Общая статистика'])
    writer.writerow(['Показатель', 'Значение'])
    writer.writerow(['Всего вопросов', stats.get('total', 0)])
    writer.writerow(['Правильных ответов', stats.get('correct', 0)])
    writer.writerow(['Неправильных ответов', stats.get('incorrect', 0)])
    
    if stats.get('total', 0) > 0:
        accuracy = (stats.get('correct', 0) / stats['total']) * 100
        writer.writerow(['Точность (%)', f'{accuracy:.1f}'])
    
    writer.writerow(['Текущая серия', stats.get('streak', 0)])
    writer.writerow(['Рекорд серии', stats.get('max_streak', 0)])
    writer.writerow([])
    
    # Ошибки по темам
    if mistakes:
        writer.writerow(['Анализ ошибок'])
        writer.writerow(['Тема', 'Количество ошибок', 'Тип ошибки'])
        
        mistakes_by_topic = {}
        for mistake in mistakes:
            topic = mistake.get('topic', 'Без темы')
            if topic not in mistakes_by_topic:
                mistakes_by_topic[topic] = []
            mistakes_by_topic[topic].append(mistake)
        
        for topic, topic_mistakes in mistakes_by_topic.items():
            error_types = {}
            for m in topic_mistakes:
                error_type = m.get('error_type', 'Неверный ответ')
                error_types[error_type] = error_types.get(error_type, 0) + 1
            
            for error_type, count in error_types.items():
                writer.writerow([topic, count, error_type])
    
    # Получаем содержимое
    output.seek(0)
    csv_content = output.getvalue()
    
    # Создаем файл для отправки
    bio = io.BytesIO()
    bio.write(csv_content.encode('utf-8-sig'))  # UTF-8 with BOM для Excel
    bio.seek(0)
    bio.name = f'statistics_{user_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    # Отправляем файл
    await query.message.reply_document(
        bio,
        caption="📊 Ваша статистика экспортирована в CSV файл",
        filename=bio.name
    )
    
    return states.CHOOSING_MODE


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def work_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает режим работы над ошибками."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем список ID вопросов с ошибками
    mistake_ids = await db.get_mistake_ids(user_id)
    
    if not mistake_ids:
        text = "🎉 <b>Отлично!</b>\n\nУ вас нет ошибок для проработки!"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ В меню", callback_data="to_test_part_menu")
        ]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return states.CHOOSING_MODE
    
    # Сохраняем режим и список ошибок
    context.user_data['mode'] = 'mistakes'
    context.user_data['mistake_queue'] = list(mistake_ids)
    context.user_data['mistakes_total'] = len(mistake_ids)
    context.user_data['mistakes_completed'] = 0
    context.user_data['current_mistake_index'] = 0
    
    text = f"""🔄 <b>Работа над ошибками</b>

У вас {len(mistake_ids)} вопросов с ошибками.

Сейчас вы будете проходить эти вопросы заново. 
При правильном ответе вопрос будет удален из списка ошибок.

Готовы начать?"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Начать", callback_data="test_start_mistakes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="to_test_part_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет подписку пользователя."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем статус подписки
    user_data = await db.get_user_status(user_id)
    is_subscribed = user_data.get('is_subscribed', False)
    
    if is_subscribed:
        text = """✅ <b>Подписка активна</b>

У вас есть доступ ко всем функциям бота:
• Неограниченное количество вопросов
• Детальная статистика
• Экспорт отчетов
• Приоритетная поддержка"""
    else:
        text = """❌ <b>Подписка не активна</b>

В бесплатной версии доступно:
• До 50 вопросов в месяц
• Базовая статистика
• Основные режимы тренировки

Для полного доступа оформите подписку."""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 Оформить подписку", callback_data="subscribe")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="to_test_part_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
@validate_state_transition({states.CHOOSING_MODE})
async def test_start_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает работу над ошибками."""
    query = update.callback_query
    
    # Отправляем первый вопрос из очереди ошибок
    from .handlers import send_mistake_question
    
    await query.edit_message_text("⏳ Загружаю первый вопрос...")
    await send_mistake_question(query.message, context)
    
    return states.REVIEWING_MISTAKES