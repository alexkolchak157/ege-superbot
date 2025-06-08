"""Обработчики для задания 19."""

import logging
import os
import json
import random
from typing import Optional, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import states
from core.ai_evaluator import Task19Evaluator

logger = logging.getLogger(__name__)

# Глобальное хранилище для данных задания 19
task19_data = {}

# Создаем evaluator заранее
try:
    evaluator = Task19Evaluator()
    logger.info("Task19 evaluator created successfully")
except Exception as e:
    logger.warning(f"Failed to create evaluator: {e}. Will work without AI.")
    evaluator = None


async def init_task19_data():
    """Инициализация данных для задания 19."""
    global task19_data
    
    data_file = os.path.join(os.path.dirname(__file__), "task19_topics.json")
    
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            task19_data = json.load(f)
        logger.info(f"Loaded {len(task19_data.get('topics', []))} topics for task19")
    except Exception as e:
        logger.error(f"Failed to load task19 data: {e}")
        task19_data = {"topics": []}


async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в задание 19 из главного меню."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📝 <b>Задание 19</b>\n\n"
        "В этом задании нужно привести примеры, иллюстрирующие "
        "различные обществоведческие понятия и явления.\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t19_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t19_theory")],
        [InlineKeyboardButton("🏦 Банк примеров", callback_data="t19_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t19_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def cmd_task19(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task19."""
    text = (
        "📝 <b>Задание 19</b>\n\n"
        "В этом задании нужно привести примеры, иллюстрирующие "
        "различные обществоведческие понятия и явления.\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t19_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t19_theory")],
        [InlineKeyboardButton("🏦 Банк примеров", callback_data="t19_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t19_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики."""
    query = update.callback_query
    await query.answer()
    
    if not task19_data.get('topics'):
        await query.edit_message_text(
            "❌ Данные заданий не загружены. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Показываем список тем
    text = "📚 <b>Выберите тему для практики:</b>\n\n"
    
    kb_buttons = []
    for i, topic in enumerate(task19_data['topics']):
        kb_buttons.append([InlineKeyboardButton(
            f"{i+1}. {topic['title']}",
            callback_data=f"t19_topic:{topic['id']}"
        )])
    
    kb_buttons.append([InlineKeyboardButton(
        "🎲 Случайная тема",
        callback_data="t19_random"
    )])
    kb_buttons.append([InlineKeyboardButton(
        "⬅️ Назад",
        callback_data="t19_menu"
    )])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_TOPIC


async def select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор конкретной темы."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "t19_random":
        topic = random.choice(task19_data['topics'])
    else:
        topic_id = int(query.data.split(':')[1])
        topic = next((t for t in task19_data['topics'] if t['id'] == topic_id), None)
    
    if not topic:
        await query.edit_message_text("❌ Тема не найдена")
        return states.CHOOSING_MODE
    
    # Сохраняем текущую тему
    context.user_data['current_topic'] = topic
    
    text = f"""📝 <b>Задание 19</b>

<b>Тема:</b> {topic['title']}

<b>Задание:</b> {topic['task_text']}

<b>Требования:</b>
• Приведите три примера
• Каждый пример должен быть конкретным
• Избегайте абстрактных формулировок
• Указывайте детали (имена, даты, места)

💡 <i>Отправьте ваш ответ одним сообщением</i>"""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Выбрать другую тему", callback_data="t19_practice")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.ANSWERING


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа пользователя."""
    user_answer = update.message.text
    topic = context.user_data.get('current_topic')
    
    if not topic:
        await update.message.reply_text(
            "❌ Ошибка: тема не выбрана. Начните заново.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 К заданиям", callback_data="t19_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Показываем сообщение о проверке
    thinking_msg = await update.message.reply_text(
        "🤔 Анализирую ваш ответ..."
    )
    
    try:
        # Проверяем наличие evaluator
        if not evaluator:
            # Простая проверка без AI
            examples_count = len([line for line in user_answer.split('\n') if line.strip()])
            feedback = f"📊 <b>Результаты проверки</b>\n\n"
            feedback += f"<b>Тема:</b> {topic['title']}\n"
            feedback += f"<b>Примеров найдено:</b> {examples_count}\n\n"
            
            if examples_count >= 3:
                feedback += "✅ Вы привели достаточное количество примеров.\n"
            else:
                feedback += "❌ Необходимо привести три примера.\n"
            
            feedback += "\n⚠️ <i>AI-проверка недоступна. Обратитесь к преподавателю для детальной оценки.</i>"
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
            feedback += f"<b>Комментарий:</b>\n{result.feedback}\n\n"
        
        if result.suggestions:
            feedback += f"<b>Рекомендации:</b>\n"
            for suggestion in result.suggestions:
                feedback += f"• {suggestion}\n"
        
        # Сохраняем результат
        if 'task19_results' not in context.user_data:
            context.user_data['task19_results'] = []
        
        context.user_data['task19_results'].append({
            'topic': topic['title'],
            'score': result.total_score,
            'max_score': result.max_score
        })
        
        # Кнопки
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Другая тема", callback_data="t19_practice"),
                InlineKeyboardButton("📋 Меню", callback_data="t19_menu")
            ],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ])
        
        await thinking_msg.edit_text(
            feedback,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Ошибка при проверке ответа: {e}", exc_info=True)
        
        # Fallback оценка
        examples_count = len([line for line in user_answer.split('\n') if line.strip() and len(line.strip()) > 20])
        
        feedback = f"📊 <b>Результаты проверки</b>\n\n"
        feedback += f"<b>Тема:</b> {topic['title']}\n"
        feedback += f"<b>Примеров найдено:</b> {examples_count}/3\n\n"
        
        if examples_count >= 3:
            feedback += "✅ Количество примеров соответствует требованиям.\n"
        else:
            feedback += "❌ Необходимо привести три развернутых примера.\n"
        
        feedback += "\n⚠️ <i>Произошла ошибка при AI-проверке. Используется упрощенная оценка.</i>"
        
        # Простые кнопки без детального анализа
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Другая тема", callback_data="t19_practice"),
                InlineKeyboardButton("📋 Меню", callback_data="t19_menu")
            ],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ])
        
        await thinking_msg.edit_text(
            feedback,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    
    return states.CHOOSING_MODE


async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ теории и советов."""
    query = update.callback_query
    await query.answer()
    
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


async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ банка примеров."""
    query = update.callback_query
    await query.answer()
    
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

async def bank_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по банку примеров."""
    query = update.callback_query
    await query.answer()
    
    current_idx = int(query.data.split(":")[1])
    topics = task19_data.get('topics', [])
    
    if current_idx >= len(topics):
        current_idx = 0  # Возвращаемся к первой теме
    
    topic = topics[current_idx]
    
    text = f"📚 <b>Банк примеров</b> ({current_idx + 1}/{len(topics)})\n\n"
    text += f"<b>Тема:</b> {topic['title']}\n"
    text += f"<b>Задание:</b> {topic['task_text']}\n\n"
    text += "<b>Эталонные примеры:</b>\n\n"
    
    for i, example in enumerate(topic.get('example_answers', []), 1):
        text += f"{i}. <b>{example['type']}</b>\n"
        text += f"   {example['example']}\n\n"
    
    # Навигация
    kb_buttons = []
    nav_row = []
    
    if current_idx > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"t19_bank_next:{current_idx-1}"))
    
    nav_row.append(InlineKeyboardButton(f"{current_idx+1}/{len(topics)}", callback_data="noop"))
    
    if current_idx < len(topics) - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"t19_bank_next:{current_idx+1}"))
    
    kb_buttons.append(nav_row)
    kb_buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t19_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE


async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прогресса пользователя."""
    query = update.callback_query
    await query.answer()
    
    results = context.user_data.get('task19_results', [])
    
    if not results:
        text = "📊 <b>Ваш прогресс</b>\n\nВы еще не решали задания."
    else:
        total_attempts = len(results)
        total_score = sum(r['score'] for r in results)
        max_possible = sum(r['max_score'] for r in results)
        avg_score = total_score / total_attempts
        
        # Визуальный прогресс-бар
        progress_percent = int(total_score / max_possible * 100) if max_possible > 0 else 0
        filled = "█" * (progress_percent // 10)
        empty = "░" * (10 - progress_percent // 10)
        progress_bar = f"{filled}{empty}"
        
        text = f"""📊 <b>Ваш прогресс по заданию 19</b>

📈 Прогресс: {progress_bar} {progress_percent}%
📝 Решено заданий: {total_attempts}
⭐ Средний балл: {avg_score:.1f}/3
🏆 Общий результат: {total_score}/{max_possible}

<b>Последние попытки:</b>"""
        
        for result in results[-5:]:
            score_emoji = "🟢" if result['score'] == 3 else "🟡" if result['score'] >= 2 else "🔴"
            text += f"\n{score_emoji} {result['topic']}: {result['score']}/3"
        
        # Рекомендации
        if avg_score < 2:
            text += "\n\n💡 <b>Совет:</b> Изучите теорию и примеры эталонных ответов."
        elif avg_score < 2.5:
            text += "\n\n💡 <b>Совет:</b> Обратите внимание на конкретизацию примеров."
        else:
            text += "\n\n🎉 <b>Отлично!</b> Вы хорошо справляетесь с заданием 19!"
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE


async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню."""
    from core.plugin_loader import build_main_menu
    
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👋 Выберите раздел для изучения:",
        reply_markup=build_main_menu()
    )
    return ConversationHandler.END


async def return_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 19."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📝 <b>Задание 19</b>\n\n"
        "В этом задании нужно привести примеры, иллюстрирующие "
        "различные обществоведческие понятия и явления.\n\n"
        "Выберите режим работы:"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t19_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t19_theory")],
        [InlineKeyboardButton("🏦 Банк примеров", callback_data="t19_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t19_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return states.CHOOSING_MODE


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    await update.message.reply_text("Действие отменено.")
    return await cmd_task19(update, context)

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик для неактивных кнопок."""
    query = update.callback_query
    await query.answer()
    # Ничего не делаем, просто отвечаем на callback
