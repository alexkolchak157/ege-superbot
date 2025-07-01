# core/ui_helpers.py
"""Дополнительные UI/UX хелперы для улучшения интерфейса"""

import asyncio
import random
from datetime import datetime
from typing import Dict, Optional, Set
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

# Глобальный набор для хранения активных задач анимации
_active_animation_tasks: Set[asyncio.Task] = set()

def _create_animation_task(coro):
    """Создает задачу анимации и сохраняет ссылку на неё."""
    task = asyncio.create_task(coro)
    _active_animation_tasks.add(task)
    
    # Удаляем задачу из набора после завершения
    task.add_done_callback(_active_animation_tasks.discard)
    
    return task

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

async def show_extended_thinking_animation(message: Message, text: str = "Проверяю ваш ответ", 
                                         duration: int = 40) -> Message:
    """
    Показывает длительную анимированную проверку для AI-оценки.
    
    Args:
        message: Сообщение для ответа
        text: Текст анимации
        duration: Длительность анимации в секундах (по умолчанию 40)
        
    Returns:
        Message: Отправленное сообщение с анимацией
    """
    # Расширенный набор эмодзи для разнообразия
    emojis = ["🔍", "📝", "🤔", "💭", "📊", "✨", "🧐", "📖", "🎯", "⚡"]
    dots_sequence = [".", "..", "..."]
    
    # Отправляем начальное сообщение
    thinking_msg = await message.reply_text(f"{emojis[0]} {text}{dots_sequence[0]}")
    
    # Создаем фоновую задачу для анимации
    async def animate():
        update_interval = 1.5  # Обновление каждые 1.5 секунды
        iterations = int(duration / update_interval)
        
        for i in range(iterations):
            # Меняем эмодзи каждые 3 итерации (примерно каждые 4.5 секунды)
            emoji_index = (i // 3) % len(emojis)
            emoji = emojis[emoji_index]
            
            # Точки меняются каждую итерацию
            dots = dots_sequence[i % len(dots_sequence)]
            
            try:
                # Добавляем вариативность в текст для некоторых итераций
                if i % 10 == 5:  # Каждые ~15 секунд
                    variation_text = "Анализирую детали"
                elif i % 10 == 8:  # Каждые ~12 секунд с смещением
                    variation_text = "Почти готово"
                else:
                    variation_text = text
                
                await thinking_msg.edit_text(f"{emoji} {variation_text}{dots}")
                await asyncio.sleep(update_interval)
                
            except Exception as e:
                # Сообщение было удалено или произошла ошибка
                logger.debug(f"Animation stopped: {e}")
                break
    
    # Запускаем анимацию в фоне с сохранением ссылки
    _create_animation_task(animate())
    
    return thinking_msg


async def show_ai_evaluation_animation(message: Message, duration: int = 40) -> Message:
    """
    Специальная анимация для AI-проверки с подробными статусами.
    
    Args:
        message: Сообщение для ответа
        duration: Общая длительность анимации в секундах
        
    Returns:
        Message: Сообщение с анимацией
    """
    # Фазы проверки с соответствующими эмодзи
    phases = [
        ("🔍", "Анализирую ваш ответ"),
        ("📝", "Проверяю соответствие критериям"),
        ("🤔", "Оцениваю полноту ответа"),
        ("💭", "Проверяю фактическую точность"),
        ("📊", "Подсчитываю баллы"),
        ("✨", "Формирую обратную связь")
    ]
    
    dots_sequence = [".", "..", "..."]
    
    # Отправляем начальное сообщение
    emoji, text = phases[0]
    thinking_msg = await message.reply_text(f"{emoji} {text}{dots_sequence[0]}")
    
    # Рассчитываем время для каждой фазы
    phase_duration = duration / len(phases)
    updates_per_phase = max(3, int(phase_duration / 1.5))  # Минимум 3 обновления на фазу
    
    # Создаём корутину для анимации
    async def run_animation():
        try:
            for phase_idx, (emoji, phase_text) in enumerate(phases):
                for update_idx in range(updates_per_phase):
                    dots = dots_sequence[update_idx % len(dots_sequence)]
                    
                    try:
                        # В конце каждой фазы добавляем галочку
                        if update_idx == updates_per_phase - 1 and phase_idx < len(phases) - 1:
                            await thinking_msg.edit_text(f"{emoji} {phase_text}... ✓")
                            await asyncio.sleep(0.7)
                        else:
                            await thinking_msg.edit_text(f"{emoji} {phase_text}{dots}")
                            await asyncio.sleep(1.3)
                            
                    except Exception as e:
                        logger.debug(f"Animation update failed: {e}")
                        return
            
            # Финальное сообщение
            try:
                await thinking_msg.edit_text("✅ Проверка завершена!")
                await asyncio.sleep(0.5)
            except:
                pass
                
        except Exception as e:
            logger.error(f"Animation error: {e}")
    
    # Запускаем анимацию как фоновую задачу с сохранением ссылки
    _create_animation_task(run_animation())
    
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
        15: ("🔥🔥🔥", "Две недели! Вы в ударе!"),
        20: ("🏆", "20 дней! Легендарно!"),
        30: ("💎", "Месяц подряд! Невероятно!"),
        50: ("👑", "50 дней! Вы мастер!"),
        100: ("🌟", "100 дней! Эпический стрик!")
    }
    
    # Находим подходящий milestone
    emoji = "🔥"
    message_text = "Отличная серия!"
    
    for milestone, (milestone_emoji, milestone_text) in sorted(milestones.items(), reverse=True):
        if value >= milestone:
            emoji = milestone_emoji
            message_text = milestone_text
            break
    
    notification_text = f"{emoji} <b>Стрик {value}!</b>\n{message_text}"
    
    # Отправляем уведомление
    notification = await update.effective_message.reply_text(
        notification_text,
        parse_mode=ParseMode.HTML
    )
    
    # Удаляем через 5 секунд
    async def delete_notification():
        await asyncio.sleep(5)
        try:
            await notification.delete()
        except:
            pass
    
    _create_animation_task(delete_notification())

def get_personalized_greeting(user_name: str, user_stats: Dict[str, Any]) -> str:
    """
    Возвращает персонализированное приветствие.
    
    Args:
        user_name: Имя пользователя
        user_stats: Статистика пользователя
        
    Returns:
        str: Персонализированное приветствие
    """
    hour = datetime.now().hour
    
    # Определяем время суток
    if 5 <= hour < 12:
        time_greeting = "Доброе утро"
        emoji = "☀️"
    elif 12 <= hour < 17:
        time_greeting = "Добрый день"
        emoji = "🌤"
    elif 17 <= hour < 22:
        time_greeting = "Добрый вечер"
        emoji = "🌆"
    else:
        time_greeting = "Доброй ночи"
        emoji = "🌙"
    
    # Получаем стрик
    streak = user_stats.get('daily_streak', 0)
    
    greeting = f"{emoji} {time_greeting}, {user_name}!\n"
    
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
        total: Общее значение
        
    Returns:
        str: Визуальная шкала прогресса
    """
    if total == 0:
        return "⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜"
    
    percentage = current / total
    filled = int(percentage * 10)
    
    bar = "🟩" * filled + "⬜" * (10 - filled)
    
    return f"{bar} {int(percentage * 100)}%"

def get_achievement_emoji(achievement_type: str) -> str:
    """
    Возвращает эмодзи для достижения.
    
    Args:
        achievement_type: Тип достижения
        
    Returns:
        str: Соответствующий эмодзи
    """
    achievement_emojis = {
        'first_answer': '🎯',
        'perfect_score': '⭐',
        'streak_3': '🔥',
        'streak_7': '🔥🔥',
        'streak_30': '🔥🔥🔥',
        'completed_10': '📚',
        'completed_50': '📖',
        'completed_100': '🎓',
        'speed_demon': '⚡',
        'perfectionist': '💎',
        'explorer': '🗺',
        'champion': '🏆',
        'legend': '👑'
    }
    
    return achievement_emojis.get(achievement_type, '🏅')

# Функция очистки завершенных задач (опционально)
async def cleanup_completed_animation_tasks():
    """Очищает завершенные задачи анимации из набора."""
    global _active_animation_tasks
    completed = {task for task in _active_animation_tasks if task.done()}
    _active_animation_tasks -= completed
    logger.debug(f"Cleaned up {len(completed)} completed animation tasks")