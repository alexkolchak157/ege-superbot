import random
import re
import logging
import csv
from io import StringIO, BytesIO
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional, Set

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest

# Исправленные импорты
from core.config import REQUIRED_CHANNEL  # из core
from core import db  # из core

try:
    from .topic_data import TOPIC_NAMES
except ImportError:
    logging.error("Не найден файл topic_data.py или словарь TOPIC_NAMES в нем.")
    TOPIC_NAMES = {}

from .loader import QUESTIONS_DATA

logger = logging.getLogger(__name__)

# Пулл фраз для правильных ответов
CORRECT_PHRASES = [
    "✅ Правильно!",
    "✅ Отлично!",
    "✅ Верно!",
    "✅ Точно!",
    "✅ Превосходно!",
    "✅ Так держать!",
    "✅ Молодец!",
    "✅ Великолепно!",
    "✅ Именно так!",
    "✅ Безупречно!",
    "✅ Супер!",
    "✅ Блестяще!",
    "✅ Замечательно!",
    "✅ Прекрасно!",
    "✅ Восхитительно!",
]

# Пулл фраз для неправильных ответов
INCORRECT_PHRASES = [
    "❌ Неправильно!",
    "❌ Не совсем так!",
    "❌ Попробуйте еще раз!",
    "❌ Ошибочка вышла!",
    "❌ Не угадали!",
    "❌ Промах!",
    "❌ Мимо!",
    "❌ Не то!",
    "❌ Увы, нет!",
    "❌ К сожалению, неверно!",
]

# Специальные фразы для длинных стриков
STREAK_MILESTONE_PHRASES = {
    5: "🔥 Горячая серия!",
    10: "🚀 Невероятная серия!",
    15: "💎 Бриллиантовая серия!",
    20: "⭐ Звездная серия!",
    25: "🏆 Чемпионская серия!",
    30: "👑 Королевская серия!",
    50: "🌟 ЛЕГЕНДАРНАЯ СЕРИЯ!",
    100: "💫 МИФИЧЕСКАЯ СЕРИЯ!"
}

def get_random_correct_phrase() -> str:
    """Возвращает случайную фразу для правильного ответа."""
    return random.choice(CORRECT_PHRASES)

def get_random_incorrect_phrase() -> str:
    """Возвращает случайную фразу для неправильного ответа."""
    return random.choice(INCORRECT_PHRASES)

def get_streak_milestone_phrase(streak: int) -> str:
    """Возвращает специальную фразу для достижения определенного стрика."""
    for milestone in sorted(STREAK_MILESTONE_PHRASES.keys(), reverse=True):
        if streak >= milestone:
            return STREAK_MILESTONE_PHRASES[milestone]
    return ""

async def safe_edit_message(
    update: Update, 
    new_text: str, 
    reply_markup=None, 
    parse_mode=None
) -> bool:
    """
    Безопасно редактирует сообщение, игнорируя ошибку "не изменено".
    
    Returns:
        bool: True если сообщение отредактировано, False если не изменилось
    """
    query = update.callback_query
    if not query:
        return False
        
    try:
        await query.edit_message_text(
            new_text, 
            reply_markup=reply_markup, 
            parse_mode=parse_mode
        )
        return True
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            logger.debug(f"Message not modified for user {query.from_user.id}")
            return False
        else:
            # Если это другая ошибка - пробрасываем
            raise

# Вспомогательные функции
async def choose_question(user_id: int, questions: list) -> dict:
    """Выбор вопроса с учетом отвеченных."""
    if not questions:
        return None
    
    try:
        # Получаем отвеченные
        answered_ids = await db.get_answered_question_ids(user_id)
        
        # Фильтруем
        available = [q for q in questions if q['id'] not in answered_ids]
        
        # Если все отвечены - сбрасываем
        if not available:
            await db.reset_answered_questions(user_id)
            available = questions
        
        return random.choice(available) if available else None
    
    except Exception as e:
        logger.error(f"Error choosing question for user {user_id}: {e}")
        return random.choice(questions) if questions else None

async def safe_answer_callback(update: Update, text: str = None, show_alert: bool = False):
    """Безопасно отвечает на callback query."""
    if update.callback_query:
        try:
            await update.callback_query.answer(text, show_alert=show_alert)
        except Exception as e:
            logger.warning(f"Failed to answer callback query: {e}")

def create_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """Создаёт универсальную клавиатуру возврата в главное меню."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ])

async def check_subscription(user_id: int, bot, channel: str = None) -> bool:
    """Проверка подписки на канал."""
    # Временно отключаем проверку для тестирования
    return True
    
    # Когда будете готовы включить проверку, раскомментируйте код ниже:
    """
    if not channel:
        channel = REQUIRED_CHANNEL
        
    if not channel:
        logger.warning("Канал для проверки подписки не указан")
        return True
    
    try:
        from telegram.constants import ChatMemberStatus
        
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        
        # Проверяем статус
        if hasattr(member, 'status'):
            return member.status in [
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
                ChatMemberStatus.CREATOR
            ]
        
        # Старый способ для совместимости
        status = getattr(member, 'status', None)
        if status:
            return status.lower() in ['member', 'administrator', 'creator', 'owner']
            
        return False
        
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return True  # В случае ошибки пропускаем
    """

async def send_subscription_required(update_or_query, channel: str):
    """Отправка сообщения о необходимости подписки."""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подписаться", url=f"https://t.me/{channel.lstrip('@')}")],
        [InlineKeyboardButton("🔄 Я подписался", callback_data="check_subscription")]
    ])
    
    text = f"Для доступа к боту необходимо подписаться на канал {channel}"
    
    try:
        if hasattr(update_or_query, 'message'):
            # Это Update
            await update_or_query.message.reply_text(text, reply_markup=kb)
        else:
            # Это CallbackQuery
            await update_or_query.edit_message_text(text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Error sending subscription required message: {e}")

def normalize_answer(answer: str, question_type: str) -> str:
    """Нормализация ответа для сравнения."""
    if not answer:
        return ""
    
    processed = answer.strip().replace(" ", "").replace(",", "")
    
    if question_type == "multiple_choice":
        # Сортируем цифры
        digits = "".join(filter(str.isdigit, processed))
        return "".join(sorted(set(digits)))
    elif question_type in ["matching", "sequence", "single_choice"]:
        # Только цифры в порядке ввода
        return "".join(filter(str.isdigit, processed))
    else:
        # Текстовый ответ
        return processed.lower()

def format_question_text(question_data: dict) -> str:
    """Форматирование текста вопроса."""
    if not question_data:
        return "❌ Ошибка: данные вопроса отсутствуют"
    
    q_type = question_data.get('type')
    block = question_data.get('block', 'N/A')
    topic = question_data.get('topic', 'N/A')
    exam_num = question_data.get('exam_number')
    
    # Заголовок с эмодзи
    text = f"📚 <b>Блок:</b> {block}\n"
    text += f"📖 <b>Тема:</b> {topic}\n"
    if exam_num:
        text += f"📝 <b>Задание ЕГЭ:</b> №{exam_num}\n"
    text += "━" * 30 + "\n\n"
    
    # Вопрос
    if q_type == "matching":
        text += f"❓ <b>{question_data.get('instruction', 'Установите соответствие')}</b>\n\n"
        
        # Первая колонка
        col1_header = question_data.get('column1_header', 'СТОЛБЕЦ 1')
        col1_options = question_data.get('column1_options', {})
        text += f"<b>{col1_header}:</b>\n"
        for letter, option in sorted(col1_options.items()):
            text += f"<b>{letter})</b> {option}\n"
        
        # Вторая колонка
        text += "\n"
        col2_header = question_data.get('column2_header', 'СТОЛБЕЦ 2')
        col2_options = question_data.get('column2_options', {})
        text += f"<b>{col2_header}:</b>\n"
        for digit, option in sorted(col2_options.items(), key=lambda x: int(x[0])):
            text += f"<b>{digit}.</b> {option}\n"
        
        text += f"\n✍️ <i>Введите {len(col1_options)} цифр ответа без пробелов</i>"
    
    else:
        question_text = question_data.get('question', '')
        question_text = md_to_html(question_text)
        parts = question_text.split('\n', 1)
        instruction = parts[0]
        options = parts[1] if len(parts) > 1 else ''
        
        text += f"❓ <b>{instruction}</b>\n\n"
        
        # Форматируем варианты ответов
        if options:
            lines = options.split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    text += "\n"
                    continue
                    
                # Проверяем, начинается ли строка с цифры и скобки/точки
                if re.match(r'^\*?\*?\d+[).]', line):
                    # Это вариант ответа
                    # Конвертируем markdown в HTML
                    line = md_to_html(line)
                    # Добавляем отступ и форматирование
                    text += f"  {line}\n"
                else:
                    # Это продолжение текста
                    text += f"{line}\n"
        
        # Подсказка по вводу
        text += "\n"
        if q_type == "multiple_choice":
            text += "✍️ <i>Введите цифры верных ответов без пробелов</i>"
        elif q_type == "single_choice":
            text += "✍️ <i>Введите одну цифру верного ответа</i>"
        elif q_type == "sequence":
            text += "✍️ <i>Введите цифры в правильной последовательности</i>"
        else:
            text += "✍️ <i>Введите ваш ответ</i>"
    
    return text

def format_plan_with_emojis(plan_text: str) -> str:
    """Форматирование плана с эмодзи."""
    if not plan_text:
        return ""
    
    lines = plan_text.split('\n')
    formatted = []
    digit_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            formatted.append("")
            continue
        
        # Пункты
        point_match = re.match(r'^(\d+)[.)]\s*(.*)', stripped)
        if point_match:
            num = int(point_match.group(1))
            text = point_match.group(2)
            emoji = digit_emojis[num-1] if 0 < num <= len(digit_emojis) else f"{num}."
            formatted.append(f"{emoji} {text}")
            continue
        
        # Подпункты
        subpoint_match = re.match(r'^[а-яa-z][.)]\s*(.*)', stripped)
        if subpoint_match:
            text = subpoint_match.group(1)
            formatted.append(f"  🔸 {text}")
            continue
        
        # Маркеры
        if stripped.startswith(('-', '*')):
            text = stripped[1:].strip()
            formatted.append(f"  🔹 {text}")
            continue
        
        formatted.append(line)
    
    return "\n".join(formatted)

def format_progress_bar(current: int, total: int, width: int = 10) -> str:
    """Создает визуальный прогресс-бар."""
    if total == 0:
        return f"[{'░' * width}] 0% (0/0)"
    
    # Автоматически увеличиваем ширину для малого количества вопросов
    if total <= 10 and width == 10:
        width = 15
    
    # Используем round для более точного отображения прогресса
    filled = round(width * current / total)
    bar = "█" * filled + "░" * (width - filled)
    percentage = round(100 * current / total)
    
    return f"[{bar}] {percentage}% ({current}/{total})"

def find_question_by_id(question_id: str) -> Optional[Dict[str, Any]]:
    """Ищет вопрос по ID используя кеш если доступен."""
    if not question_id:
        return None
    
    # Используем кеш для быстрого поиска если он доступен
    try:
        from .cache import questions_cache
        if questions_cache:
            cached_question = questions_cache.get_by_id(question_id)
            if cached_question:
                return cached_question
    except ImportError:
        pass
    
    # Если кеш не доступен или не построен, ищем по-старому
    if not QUESTIONS_DATA:
        return None
        
    for block_data in QUESTIONS_DATA.values():
        for topic_questions in block_data.values():
            for question in topic_questions:
                if isinstance(question, dict) and question.get("id") == question_id:
                    return question
    
    logging.warning(f"Вопрос с ID {question_id} не найден.")
    return None

async def export_user_stats_csv(user_id: int) -> str:
    """Экспортирует статистику пользователя в CSV."""
    try:
        stats = await db.get_user_stats(user_id)
        mistake_ids = await db.get_mistake_ids(user_id)
        streaks = await db.get_user_streaks(user_id)
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow(["Тема", "Название темы", "Правильных", "Всего", "Процент", "Блок"])
        
        # Данные по темам
        total_correct = 0
        total_answered = 0
        
        for topic, correct, total in stats:
            percentage = (correct / total * 100) if total > 0 else 0
            topic_name = TOPIC_NAMES.get(topic, topic)
            
            # Находим блок для темы
            block_name = "Неизвестный"
            for block, topics in QUESTIONS_DATA.items():
                if topic in topics:
                    block_name = block
                    break
            
            writer.writerow([topic, topic_name, correct, total, f"{percentage:.1f}%", block_name])
            total_correct += correct
            total_answered += total
        
        # Добавляем общую статистику
        writer.writerow([])  # Пустая строка
        writer.writerow(["ИТОГО", "", total_correct, total_answered, 
                        f"{(total_correct/total_answered*100 if total_answered > 0 else 0):.1f}%", ""])
        
        # Добавляем сводку
        writer.writerow([])  # Пустая строка
        writer.writerow(["=== СВОДКА ==="])
        writer.writerow(["Параметр", "Значение"])
        writer.writerow(["Дней подряд", streaks.get('current_daily', 0)])
        writer.writerow(["Рекорд дней", streaks.get('max_daily', 0)])
        writer.writerow(["Правильных подряд", streaks.get('current_correct', 0)])
        writer.writerow(["Рекорд правильных", streaks.get('max_correct', 0)])
        writer.writerow(["Ошибок к исправлению", len(mistake_ids)])
        
        # Добавляем список ошибок
        if mistake_ids:
            writer.writerow([])
            writer.writerow(["=== ВОПРОСЫ С ОШИБКАМИ ==="])
            writer.writerow(["ID вопроса", "Блок", "Тема", "Номер ЕГЭ"])
            
            for mistake_id in mistake_ids:
                question = find_question_by_id(mistake_id)
                if question:
                    writer.writerow([
                        mistake_id,
                        question.get('block', 'N/A'),
                        question.get('topic', 'N/A'),
                        question.get('exam_number', 'N/A')
                    ])
        
        return output.getvalue()
    
    except Exception as e:
        logger.error(f"Error exporting stats for user {user_id}: {e}")
        raise

async def generate_detailed_report(user_id: int) -> str:
    """Генерирует детальный текстовый отчет о прогрессе."""
    try:
        stats = await db.get_user_stats(user_id)
        mistake_ids = await db.get_mistake_ids(user_id)
        streaks = await db.get_user_streaks(user_id)
        
        report = "📊 <b>ДЕТАЛЬНЫЙ ОТЧЕТ О ПРОГРЕССЕ</b>\n"
        report += "━" * 30 + "\n\n"
        
        # Стрики
        report += "🔥 <b>Стрики:</b>\n"
        report += f"📅 Дней подряд: {streaks.get('current_daily', 0)} (рекорд: {streaks.get('max_daily', 0)})\n"
        report += f"✨ Правильных подряд: {streaks.get('current_correct', 0)} (рекорд: {streaks.get('max_correct', 0)})\n\n"
        
        # Статистика по блокам
        if stats:
            report += "📚 <b>Статистика по блокам:</b>\n\n"
            
            # Группируем по блокам
            blocks_stats = {}
            for topic, correct, total in stats:
                block_name = "Неизвестный блок"
                for block, topics in QUESTIONS_DATA.items():
                    if topic in topics:
                        block_name = block
                        break
                
                if block_name not in blocks_stats:
                    blocks_stats[block_name] = {
                        'correct': 0, 
                        'total': 0,
                        'topics': []
                    }
                
                blocks_stats[block_name]['correct'] += correct
                blocks_stats[block_name]['total'] += total
                
                percentage = (correct / total * 100) if total > 0 else 0
                topic_name = TOPIC_NAMES.get(topic, topic)
                
                emoji = "🟢" if percentage >= 80 else "🟡" if percentage >= 50 else "🔴"
                blocks_stats[block_name]['topics'].append(
                    f"{emoji} {topic}: {topic_name} - {correct}/{total} ({percentage:.0f}%)"
                )
            
            # Выводим по блокам
            for block_name, data in sorted(blocks_stats.items()):
                block_percentage = (data['correct'] / data['total'] * 100) if data['total'] > 0 else 0
                block_bar = format_progress_bar(data['correct'], data['total'], width=15)
                
                report += f"<b>{block_name}</b>\n"
                report += f"{block_bar}\n"
                
                # Сортируем темы по проценту (от худших к лучшим)
                sorted_topics = sorted(data['topics'], key=lambda x: float(x.split('(')[-1].rstrip('%)').strip()))
                for topic_line in sorted_topics[:5]:  # Показываем топ-5 худших
                    report += f"  {topic_line}\n"
                
                if len(sorted_topics) > 5:
                    report += f"  <i>... и еще {len(sorted_topics) - 5} тем</i>\n"
                report += "\n"
        
        # Рекомендации
        report += "💡 <b>Рекомендации:</b>\n"
        
        if mistake_ids:
            report += f"• У вас {len(mistake_ids)} вопросов с ошибками. Используйте /mistakes для работы над ними\n"
        
        if stats:
            # Находим самые слабые темы
            weak_topics = []
            for topic, correct, total in stats:
                percentage = (correct / total * 100) if total > 0 else 0
                if percentage < 50 and total >= 3:  # Минимум 3 вопроса для статистики
                    topic_name = TOPIC_NAMES.get(topic, topic)
                    weak_topics.append((topic_name, percentage))
            
            if weak_topics:
                weak_topics.sort(key=lambda x: x[1])
                report += f"• Обратите внимание на темы: {', '.join([t[0] for t in weak_topics[:3]])}\n"
        
        if streaks.get('current_daily', 0) == 0:
            report += "• Начните регулярно заниматься, чтобы не терять навыки\n"
        elif streaks.get('current_daily', 0) < 7:
            report += "• Продолжайте заниматься каждый день для закрепления знаний\n"
        else:
            report += "• Отличная работа! Продолжайте в том же духе\n"
        
        return report
    
    except Exception as e:
        logger.error(f"Error generating report for user {user_id}: {e}")
        raise

async def purge_old_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, keep_id: Optional[int] = None):
    """
    Удаляет все сохранённые сообщения из контекста.
    
    Args:
        context: Контекст бота
        chat_id: ID чата
        keep_id: ID сообщения, которое НЕ нужно удалять (например, loading message)
    """
    # Проверяем наличие bot instance
    if not hasattr(context, 'bot') or not context.bot:
        logger.warning("Bot instance not available for message deletion")
        return
    
    # Список всех ключей, содержащих ID сообщений
    message_keys = [
        'current_question_message_id',
        'answer_message_id', 
        'feedback_message_id'
    ]
    
    # Собираем все ID для удаления
    messages_to_delete = []
    
    for key in message_keys:
        msg_id = context.user_data.get(key)
        if msg_id and msg_id != keep_id:
            messages_to_delete.append(msg_id)
    
    # Добавляем дополнительные сообщения (пояснения и т.д.)
    extra_messages = context.user_data.get('extra_messages_to_delete', [])
    messages_to_delete.extend([msg_id for msg_id in extra_messages if msg_id != keep_id])
    
    # Удаляем сообщения
    for msg_id in messages_to_delete:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            logger.debug(f"Deleted message {msg_id}")
        except Exception as e:
            logger.warning(f"Failed to delete message {msg_id}: {e}")
    
    # Очищаем контекст
    for key in message_keys:
        context.user_data.pop(key, None)
    context.user_data['extra_messages_to_delete'] = []

def md_to_html(text: str) -> str:
    """
    Конвертирует markdown-подобную разметку в HTML.
    
    Args:
        text: Текст с markdown разметкой
        
    Returns:
        Текст с HTML разметкой
    """
    if not text:
        return ""
    
    import re
    
    # Заменяем **текст** на <b>текст</b>
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    
    # Заменяем *текст* на <i>текст</i>
    text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text)
    
    # Заменяем маркеры списков в начале строк
    text = re.sub(r'^[\*\-]\s+', '• ', text, flags=re.MULTILINE)
    
    # Заменяем _текст_ на <u>текст</u>
    text = re.sub(r'_([^_]+)_', r'<u>\1</u>', text)
    
    return text

def get_plugin_keyboard_pattern(plugin_code: str) -> str:
    """Возвращает паттерн для callback_data плагина."""
    return f"^choose_{plugin_code}$"

class TestPartCallbackData:
    """Стандартные callback_data для test_part плагина."""
    
    # Основные действия
    TEST_TO_MAIN_MENU = "to_main_menu"
    TEST_TO_MENU = "to_menu"
    TEST_CANCEL = "cancel"
    
    # Навигация по режимам
    TEST_MODE_RANDOM = "mode:random"
    TEST_MODE_TOPIC = "mode:choose_topic"
    TEST_MODE_EXAM_NUM = "mode:choose_exam_num"
    
    # Действия после ответа
    TEST_NEXT_RANDOM = "next_random"
    TEST_NEXT_TOPIC = "next_topic"
    TEST_CHANGE_TOPIC = "change_topic"
    
    # Работа с ошибками
    TEST_SHOW_EXPLANATION = "show_explanation"
    TEST_NEXT_MISTAKE = "next_mistake"
    TEST_SKIP_MISTAKE = "skip_mistake"
    TEST_EXIT_MISTAKES = "exit_mistakes"
    
    @classmethod
    def get_plugin_entry(cls, plugin_code: str) -> str:
        """Возвращает callback_data для входа в плагин."""
        return f"choose_{plugin_code}"

# Алиас для совместимости (если где-то импортируется CallbackData)
CallbackData = TestPartCallbackData
