import logging
import json
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from datetime import datetime
from core import states
from .evaluator import Task19AIEvaluator

logger = logging.getLogger(__name__)

# Данные заданий
task19_data = {}
evaluator = None

async def init_task19_data():
    """Загрузка данных для задания 19."""
    global task19_data, evaluator
    
    # Загружаем темы и эталоны для задания 19
    data_file = os.path.join(os.path.dirname(__file__), "data", "task19_topics.json")
    
    try:
        if os.path.exists(data_file):
            with open(data_file, "r", encoding="utf-8") as f:
                task19_data = json.load(f)
                logger.info(f"Загружено {len(task19_data.get('topics', []))} тем для задания 19")
        else:
            # Создаем пример структуры данных
            task19_data = {
                "topics": [
                    {
                        "id": 1,
                        "title": "Виды социальных норм",
                        "task_text": "Назовите и проиллюстрируйте примерами три вида социальных норм.",
                        "key_points": ["правовые нормы", "моральные нормы", "обычаи/традиции", "религиозные нормы"],
                        "example_answers": [
                            {
                                "type": "правовые нормы",
                                "example": "Водитель останавливается на красный сигнал светофора, следуя ПДД"
                            }
                        ]
                    }
                ]
            }
            # Сохраняем пример
            os.makedirs(os.path.dirname(data_file), exist_ok=True)
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(task19_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка загрузки данных задания 19: {e}")
        task19_data = {"topics": []}
    
    # Инициализируем AI-оценщик
    evaluator = Task19AIEvaluator()

async def entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход из главного меню."""
    query = update.callback_query
    await query.answer()
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t19_practice")],
        [InlineKeyboardButton("📚 Теория и советы", callback_data="t19_theory")],
        [InlineKeyboardButton("📋 Банк примеров", callback_data="t19_examples")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="t19_progress")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await query.edit_message_text(
        "📝 <b>Задание 19 - Примеры</b>\n\n"
        "В этом задании нужно привести три примера, "
        "иллюстрирующих теоретические положения.\n\n"
        "Выберите режим работы:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def practice_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим практики."""
    query = update.callback_query
    await query.answer()
    
    topics = task19_data.get("topics", [])
    if not topics:
        await query.edit_message_text(
            "❌ Темы для практики не загружены.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
            ]])
        )
        return states.CHOOSING_MODE
    
    # Показываем список тем
    kb_buttons = []
    for i, topic in enumerate(topics[:10]):  # Показываем первые 10
        kb_buttons.append([
            InlineKeyboardButton(
                f"📄 {topic['title']}", 
                callback_data=f"t19_topic:{i}"
            )
        ])
    
    kb_buttons.append([
        InlineKeyboardButton("🎲 Случайная тема", callback_data="t19_nav:random")
    ])
    kb_buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
    ])
    
    await query.edit_message_text(
        "🎯 <b>Выберите тему для практики:</b>",
        reply_markup=InlineKeyboardMarkup(kb_buttons),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_TOPIC

async def select_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор темы для практики."""
    query = update.callback_query
    await query.answer()
    
    topic_idx = int(query.data.split(":")[1])
    topics = task19_data.get("topics", [])
    
    if topic_idx >= len(topics):
        await query.answer("Тема не найдена", show_alert=True)
        return states.CHOOSING_TOPIC
    
    topic = topics[topic_idx]
    context.user_data['current_topic'] = topic
    context.user_data['topic_index'] = topic_idx
    
    await query.edit_message_text(
        f"📝 <b>Задание 19</b>\n\n"
        f"<b>Тема:</b> {topic['title']}\n\n"
        f"<b>Задание:</b> {topic['task_text']}\n\n"
        f"<b>Требования:</b>\n"
        f"• Приведите ТРИ примера\n"
        f"• Каждый пример должен быть конкретным\n"
        f"• Примеры должны иллюстрировать разные аспекты\n\n"
        f"<i>Отправьте ваш ответ одним сообщением.</i>",
        parse_mode=ParseMode.HTML
    )
    
    return states.AWAITING_ANSWER

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа пользователя."""
    user_answer = update.message.text.strip()
    
    if len(user_answer) < 50:
        await update.message.reply_text(
            "❌ Ответ слишком короткий. Приведите три развернутых примера."
        )
        return states.AWAITING_ANSWER
    
    # Получаем текущую тему
    topic = context.user_data.get('current_topic')
    if not topic:
        await update.message.reply_text("❌ Ошибка: тема не выбрана.")
        return ConversationHandler.END
    
    # Показываем сообщение об анализе
    thinking_msg = await update.message.reply_text("🤖 Анализирую ваш ответ...")
    
    try:
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
        
        # Детальный анализ
        if result.detailed_analysis:
            analysis = result.detailed_analysis
            feedback += "<b>Анализ примеров:</b>\n"
            
            for ex in analysis.get('examples_analysis', []):
                num = ex['example_num']
                if ex['is_correct'] and ex['is_relevant'] and ex['is_specific']:
                    feedback += f"✅ Пример {num}: засчитан\n"
                else:
                    feedback += f"❌ Пример {num}: "
                    issues = []
                    if not ex['is_relevant']:
                        issues.append("не соответствует теме")
                    if not ex['is_specific']:
                        issues.append("недостаточно конкретный")
                    if not ex['is_correct']:
                        issues.append("содержит ошибку")
                    feedback += ", ".join(issues) + "\n"
        
        # Фактические ошибки
        if result.factual_errors:
            feedback += "\n<b>❌ Фактические ошибки:</b>\n"
            for error in result.factual_errors[:2]:
                feedback += f"• {error['error']}\n"
                feedback += f"  ✅ Правильно: {error['correction']}\n"
        
        # Персональная обратная связь
        if result.feedback:
            feedback += f"\n💬 <b>Рекомендация:</b>\n{result.feedback}\n"
        
        # Suggestions
        if result.suggestions:
            feedback += "\n💡 <b>Советы:</b>\n"
            for suggestion in result.suggestions[:3]:
                feedback += f"• {suggestion}\n"
        
        # Сохраняем результат
        if 'task19_results' not in context.user_data:
            context.user_data['task19_results'] = []
        
        context.user_data['task19_results'].append({
            'topic': topic['title'],
            'score': result.total_score,
            'max_score': result.max_score,
            'timestamp': datetime.now().isoformat()
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
        await thinking_msg.edit_text(
            "❌ Произошла ошибка при проверке. Попробуйте позже."
        )
    
    return states.CHOOSING_MODE

async def theory_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ теории и советов."""
    query = update.callback_query
    await query.answer()
    
    theory_text = """📚 <b>Как выполнять задание 19</b>

<b>Структура задания:</b>
Нужно привести ТРИ примера, иллюстрирующих теоретическое положение.

<b>Критерии оценки (3 балла):</b>
• По 1 баллу за каждый корректный пример
• Максимум 3 балла за задание

<b>Требования к примерам:</b>
✅ Конкретность (не абстрактные рассуждения)
✅ Соответствие заданию
✅ Разные аспекты явления
✅ Фактическая правильность

<b>Типичные ошибки:</b>
❌ Абстрактные рассуждения вместо примеров
❌ Повторение одного примера разными словами
❌ Примеры не по теме
❌ Фактические ошибки

<b>Совет:</b>
Используйте примеры из разных сфер:
• История и современность
• Разные страны
• Личный социальный опыт
• СМИ и литература"""
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
    ]])
    
    await query.edit_message_text(
        theory_text,
        reply_markup=kb,
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
        
        text = f"""📊 <b>Ваш прогресс по заданию 19</b>

📝 Решено заданий: {total_attempts}
⭐ Средний балл: {avg_score:.1f}/3
📈 Общий результат: {total_score}/{max_possible} ({int(total_score/max_possible*100)}%)

<b>Последние попытки:</b>"""
        
        for result in results[-5:]:
            text += f"\n• {result['topic']}: {result['score']}/3"
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
    ]])
    
    await query.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

# Вспомогательные функции
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню задания 19."""
    return await entry_from_menu(update, context)

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню бота."""
    query = update.callback_query
    await query.answer()
    
    from core.plugin_loader import build_main_menu
    kb = build_main_menu()
    
    await query.edit_message_text(
        "👋 Что хотите потренировать?",
        reply_markup=kb
    )
    
    return ConversationHandler.END

async def cmd_task19(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /task19."""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Практика", callback_data="t19_practice")],
        [InlineKeyboardButton("📚 Теория", callback_data="t19_theory")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])
    
    await update.message.reply_text(
        "📝 <b>Задание 19 - Примеры</b>\n\nВыберите режим:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия."""
    await update.message.reply_text("Действие отменено.")
    return await cmd_task19(update, context)

async def navigate_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Навигация по темам (случайная тема)."""
    query = update.callback_query
    await query.answer()
    
    if "random" in query.data:
        import random
        topics = task19_data.get("topics", [])
        if topics:
            idx = random.randint(0, len(topics) - 1)
            query.data = f"t19_topic:{idx}"
            return await select_topic(update, context)
    
    return states.CHOOSING_TOPIC

async def examples_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ банка примеров."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🏗️ <b>Банк примеров</b>\n\n"
        "Эта функция находится в разработке.\n"
        "Здесь будут собраны лучшие примеры по разным темам.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Назад", callback_data="t19_menu")
        ]]),
        parse_mode=ParseMode.HTML
    )
    return states.CHOOSING_MODE