# core/ui_helpers.py
"""Дополнительные UI/UX хелперы для улучшения интерфейса"""

import asyncio
import random
from datetime import datetime
from typing import Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

async def show_thinking_animation(message: Message, text: str = "Анализирую") -> Message:
    """
    Показывает анимированное сообщение обработки.
    
    Args:
        message: Сообщение для ответа
        text: Текст анимации
        
    Returns:
        Message: Отправленное сообщение с анимацией
    """
    animations = ["🤔", "🧐", "💭", "✨"]
    thinking_msg = await message.reply_text(f"{animations[0]} {text}...")
    
    # Простая анимация без фоновой задачи
    try:
        for i in range(1, min(4, len(animations))):
            await asyncio.sleep(0.5)
            await thinking_msg.edit_text(f"{animations[i]} {text}...")
    except:
        # Игнорируем ошибки редактирования
        pass
    
    return thinking_msg

async def show_streak_notification(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                 streak_type: str, value: int):
    """
    Показывает красивое уведомление о стриках.
    
    Args:
        update: Update объект
        context: Контекст
        streak_type: Тип стрика ('correct', 'daily')
        value: Значение стрика
    """
    milestones = {
        3: ("🔥", "Отличное начало!"),
        5: ("🔥🔥", "Продолжайте в том же духе!"),
        7: ("🔥🔥", "Неделя подряд!"),
        10: ("🔥🔥🔥", "Десятка! Впечатляет!"),
        14: ("🔥🔥🔥", "Две недели! Вы молодец!"),
        20: ("⭐", "20 подряд! Фантастика!"),
        30: ("🏆", "Месяц занятий! Невероятно!"),
        50: ("🌟", "50 дней! Вы настоящий герой!"),
        100: ("💎", "100 дней! Легендарное достижение!")
    }
    
    if value in milestones:
        emoji, text = milestones[value]
        
        if streak_type == 'correct':
            title = f"{value} правильных ответов подряд!"
        else:
            title = f"{value} дней подряд!"
        
        notification = f"""
{emoji} <b>Новый рекорд!</b>

🎯 <b>{title}</b>
{text}

Продолжайте в том же духе! 💪
"""
        
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎉 Супер!", callback_data="streak_ok")
        ]])
        
        msg = await update.effective_message.reply_text(
            notification,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
        
        # Автоудаление через 10 секунд
        if context.job_queue:
            async def delete_msg(ctx: ContextTypes.DEFAULT_TYPE) -> None:
                try:
                    await msg.delete()
                except Exception:
                    pass

            context.job_queue.run_once(
                delete_msg,
                when=10,
                name=f"delete_streak_{msg.message_id}"
            )

def get_personalized_greeting(user_stats: Dict) -> str:
    """
    Возвращает персонализированное приветствие.
    
    Args:
        user_stats: Статистика пользователя
        
    Returns:
        str: Персонализированное приветствие
    """
    hour = datetime.now().hour
    attempts = user_stats.get('total_attempts', 0)
    streak = user_stats.get('streak', 0)
    
    # Приветствие по времени суток
    if 5 <= hour < 12:
        time_greeting = "Доброе утро"
    elif 12 <= hour < 17:
        time_greeting = "Добрый день"
    elif 17 <= hour < 23:
        time_greeting = "Добрый вечер"
    else:
        time_greeting = "Доброй ночи"
    
    # Статус пользователя
    if attempts == 0:
        status = "новичок"
        emoji = "🌱"
    elif attempts < 10:
        status = "ученик"
        emoji = "📚"
    elif attempts < 50:
        status = "практикант"
        emoji = "🎯"
    elif attempts < 100:
        status = "знаток"
        emoji = "🏆"
    else:
        status = "эксперт"
        emoji = "🌟"
    
    greeting = f"{time_greeting}! {emoji}\n"
    
    if streak > 0:
        greeting += f"🔥 Ваш стрик: {streak} дней\n"
    
    return greeting

def get_motivational_message(score: int, max_score: int) -> str:
    """
    Возвращает мотивационное сообщение в зависимости от результата.
    
    Args:
        score: Полученный балл
        max_score: Максимальный балл
        
    Returns:
        str: Мотивационное сообщение
    """
    percentage = score / max_score if max_score > 0 else 0
    
    motivational_quotes = {
        1.0: [
            "Безупречно! Вы настоящий мастер! 🌟",
            "Идеальная работа! Так держать! 🎯",
            "Вау! Это было великолепно! 🏆",
            "Превосходно! Вы показали класс! ⭐",
            "Блестяще! Продолжайте в том же духе! 💎"
        ],
        0.8: [
            "Отличная работа! Еще чуть-чуть до совершенства! 💪",
            "Почти идеально! Вы на верном пути! 🎯",
            "Супер! Осталось совсем немного! ⭐",
            "Здорово! Вы почти у цели! 🚀",
            "Молодец! Еще немного практики! 📈"
        ],
        0.6: [
            "Хороший результат! Продолжайте практиковаться! 📈",
            "Неплохо! Каждая попытка делает вас лучше! 💡",
            "Движетесь в правильном направлении! 🚀",
            "Хорошая работа! Есть куда расти! 🌱",
            "Достойно! Практика приведет к совершенству! 🎯"
        ],
        0.4: [
            "Не сдавайтесь! Практика - путь к успеху! 💪",
            "Каждая ошибка - это урок! Продолжайте! 📚",
            "Вы становитесь лучше с каждой попыткой! 🌱",
            "Не опускайте руки! У вас все получится! 🌟",
            "Продолжайте стараться! Успех не за горами! 🏃"
        ],
        0: [
            "Это только начало вашего пути! Не останавливайтесь! 🌟",
            "Помните: все эксперты когда-то были новичками! 🚀",
            "Главное - не сдаваться! У вас все получится! 💪",
            "Первый шаг самый трудный! Вы молодец, что пробуете! 🌱",
            "Каждая попытка приближает вас к цели! Вперед! 🎯"
        ]
    }
    
    # Выбираем подходящую категорию
    for threshold, quotes in sorted(motivational_quotes.items(), reverse=True):
        if percentage >= threshold:
            return random.choice(quotes)
    
    return random.choice(motivational_quotes[0])

def create_visual_progress(current: int, total: int) -> str:
    """
    Создает визуальный прогресс с эмодзи.
    
    Args:
        current: Текущее значение
        total: Максимальное значение
        
    Returns:
        str: Визуальный прогресс
    """
    if total == 0:
        return "⚪⚪⚪⚪⚪"
    
    percentage = current / total
    filled = int(percentage * 5)
    
    progress = ""
    for i in range(5):
        if i < filled:
            progress += "🟢"
        else:
            progress += "⚪"
    
    return progress

# Дополнительные хелперы

def format_time_difference(timestamp: str) -> str:
    """
    Форматирует разницу во времени в читаемый вид.
    
    Args:
        timestamp: ISO формат времени
        
    Returns:
        str: Отформатированная разница
    """
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        diff = datetime.now() - dt
        
        if diff.days > 0:
            return f"{diff.days} дн. назад"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{hours} ч. назад"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{minutes} мин. назад"
        else:
            return "только что"
    except:
        return "недавно"

def get_achievement_emoji(achievement_type: str) -> str:
    """
    Возвращает эмодзи для типа достижения.
    
    Args:
        achievement_type: Тип достижения
        
    Returns:
        str: Эмодзи
    """
    emojis = {
        'first_perfect': '🌟',
        'streak_3': '🔥',
        'streak_7': '🔥🔥',
        'streak_30': '🏆',
        'all_topics': '🎓',
        'speed_demon': '⚡',
        'perfectionist': '💎',
        'explorer': '🗺️',
        'dedicated': '💪',
        'master': '👑'
    }
    
    return emojis.get(achievement_type, '🏅')

# Экспорт всех функций
__all__ = [
    'show_thinking_animation',
    'show_streak_notification',
    'get_personalized_greeting',
    'get_motivational_message',
    'create_visual_progress',
    'format_time_difference',
    'get_achievement_emoji'
]
