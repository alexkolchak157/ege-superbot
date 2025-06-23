"""
test_part/missing_handlers.py
Реализация недостающих callback обработчиков для тестовой части.
"""

import logging
import io
import csv
from datetime import datetime

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import states
from core.error_handler import safe_handler
from core import db


logger = logging.getLogger(__name__)


async def get_user_mistakes(user_id: int):
    """Возвращает список ошибок пользователя."""
    mistake_ids = await db.get_mistake_ids(user_id)
    mistakes = []
    for q_id in mistake_ids:
        mistakes.append(
            {
                "question_id": q_id,
                "topic": "Тема вопроса",
                "error_type": "Неверный ответ",
                "timestamp": datetime.now().isoformat(),
            }
        )
    return mistakes


@safe_handler()
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
        [InlineKeyboardButton("📥 Экспорт в CSV", callback_data="test_export_csv")],
        [InlineKeyboardButton("🔄 Работа над ошибками", callback_data="test_work_mistakes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="test_progress")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE


@safe_handler()
async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспортирует статистику и ошибки в CSV файл."""
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer("Подготавливаю файл...")
    
    # Получаем данные
    mistakes = await get_user_mistakes(user_id)
    stats = await db.get_user_stats(user_id)
    
    # Создаем CSV в памяти
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Заголовок с информацией
    writer.writerow(['Отчет по тестовой части ЕГЭ'])
    writer.writerow([f'Дата: {datetime.now().strftime("%d.%m.%Y %H:%M")}'])
    writer.writerow([])
    
    # Общая статистика
    writer.writerow(['ОБЩАЯ СТАТИСТИКА'])
    writer.writerow(['Тема', 'Правильных ответов', 'Всего отвечено', 'Процент'])
    
    total_correct = 0
    total_answered = 0
    
    for topic, correct, answered in stats:
        percentage = (correct / answered * 100) if answered > 0 else 0
        writer.writerow([topic, correct, answered, f'{percentage:.1f}%'])
        total_correct += correct
        total_answered += answered
    
    writer.writerow([])
    writer.writerow(['ИТОГО', total_correct, total_answered, 
                    f'{(total_correct/total_answered*100 if total_answered > 0 else 0):.1f}%'])
    
    # Детали ошибок
    if mistakes:
        writer.writerow([])
        writer.writerow(['АНАЛИЗ ОШИБОК'])
        writer.writerow(['ID вопроса', 'Тема', 'Тип ошибки', 'Дата'])
        
        for mistake in mistakes:
            writer.writerow([
                mistake.get('question_id', 'N/A'),
                mistake.get('topic', 'Без темы'),
                mistake.get('error_type', 'Неверный ответ'),
                mistake.get('timestamp', 'N/A')
            ])
    
    # Готовим файл для отправки
    output.seek(0)
    bio = io.BytesIO(output.getvalue().encode('utf-8-sig'))  # UTF-8 with BOM для Excel
    bio.name = f'ege_test_report_{user_id}_{datetime.now().strftime("%Y%m%d")}.csv'
    
    # Отправляем файл
    await query.message.reply_document(
        document=bio,
        caption="📊 Ваш отчет по тестовой части ЕГЭ\n\n"
                "Файл можно открыть в Excel или Google Sheets",
        filename=bio.name
    )
    
    # Возвращаемся в меню прогресса
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="test_progress")
    ]])
    
    await query.message.reply_text(
        "✅ Отчет успешно экспортирован!",
        reply_markup=kb
    )
    
    return states.CHOOSING_MODE


@safe_handler()
async def work_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает режим работы над ошибками."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Получаем список ID вопросов с ошибками
    mistake_ids = await db.get_mistake_ids(user_id)
    
    if not mistake_ids:
        text = "🎉 <b>Отлично!</b>\n\nУ вас нет ошибок для проработки!"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ В меню", callback_data="test_back_to_mode")
        ]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return states.CHOOSING_MODE
    
    # Сохраняем режим и список ошибок
    context.user_data['mode'] = 'mistakes'
    context.user_data['mistake_queue'] = mistake_ids.copy()
    context.user_data['mistakes_total'] = len(mistake_ids)
    context.user_data['mistakes_completed'] = 0
    
    text = f"""🔄 <b>Работа над ошибками</b>

У вас {len(mistake_ids)} вопросов с ошибками.

Сейчас вы будете проходить эти вопросы заново. 
При правильном ответе вопрос будет удален из списка ошибок.

Готовы начать?"""
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Начать", callback_data="test_start_mistakes")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="test_back_to_mode")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


@safe_handler()
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
    
    kb_buttons = []
    if not is_subscribed:
        kb_buttons.append([
            InlineKeyboardButton("💎 Оформить подписку", url="https://example.com/subscribe")
        ])
    
    kb_buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="test_back_to_mode")
    ])
    
    kb = InlineKeyboardMarkup(kb_buttons)
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE
