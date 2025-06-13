"""Компоненты пользовательского интерфейса."""

from typing import List, Dict, Optional, Tuple
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime

class UIComponents:
    """Класс для создания красивых UI компонентов."""
    
    @staticmethod
    def create_progress_bar(current: int, total: int, width: int = 10) -> str:
        """Создать визуальный прогресс-бар."""
        if total == 0:
            return "░" * width
        
        percentage = current / total
        filled = int(percentage * width)
        
        # Используем разные символы для разных уровней
        if percentage >= 0.9:
            fill_char = "█"
        elif percentage >= 0.7:
            fill_char = "▓"
        elif percentage >= 0.5:
            fill_char = "▒"
        else:
            fill_char = "░"
        
        bar = fill_char * filled + "░" * (width - filled)
        return f"{bar} {int(percentage * 100)}%"
    
    @staticmethod
    def create_score_visual(score: int, max_score: int = 3) -> str:
        """Визуализация оценки."""
        if score == max_score:
            return "⭐⭐⭐"
        elif score == max_score - 1:
            return "⭐⭐☆"
        elif score == max_score - 2:
            return "⭐☆☆"
        else:
            return "☆☆☆"
    
    @staticmethod
    def create_trend_indicator(trend: str) -> str:
        """Индикатор тренда."""
        indicators = {
            'up': '📈 Растёт',
            'down': '📉 Падает',
            'neutral': '➡️ Стабильно'
        }
        return indicators.get(trend, '➡️ Стабильно')
    
    @staticmethod
    def format_time_spent(minutes: int) -> str:
        """Форматирование времени."""
        if minutes < 60:
            return f"{minutes} мин"
        else:
            hours = minutes // 60
            mins = minutes % 60
            return f"{hours}ч {mins}мин"
    
    @staticmethod
    def create_achievement_badge(achievement: Dict) -> str:
        """Создать бейдж достижения."""
        rarity_colors = {
            'common': '⚪',
            'uncommon': '🟢',
            'rare': '🔵',
            'epic': '🟣',
            'legendary': '🟡'
        }
        
        color = rarity_colors.get(achievement.get('rarity', 'common'), '⚪')
        return f"{color} {achievement['icon']} {achievement['name']}"

class EnhancedKeyboards:
    """Улучшенные клавиатуры."""
    
    @staticmethod
    def create_main_menu_keyboard(user_stats: Dict) -> InlineKeyboardMarkup:
        """Главное меню с индикаторами."""
        buttons = []
        
        # Практика с индикатором прогресса
        practice_text = "💪 Практика"
        if user_stats.get('streak', 0) > 0:
            practice_text += f" (🔥{user_stats['streak']})"
        buttons.append([InlineKeyboardButton(practice_text, callback_data="t20_practice")])
        
        # Теория с индикатором новых материалов
        theory_text = "📚 Теория и советы"
        if user_stats.get('total_attempts', 0) == 0:
            theory_text += " 🆕"
        buttons.append([InlineKeyboardButton(theory_text, callback_data="t20_theory")])
        
        # Банк суждений
        buttons.append([InlineKeyboardButton("🏦 Банк суждений", callback_data="t20_examples")])
        
        # Работа над ошибками с счётчиком
        mistakes_text = "🔧 Работа над ошибками"
        weak_topics_count = user_stats.get('weak_topics_count', 0)
        if weak_topics_count > 0:
            mistakes_text += f" ({weak_topics_count})"
        buttons.append([InlineKeyboardButton(mistakes_text, callback_data="t20_mistakes")])
        
        # Прогресс с процентом
        progress_text = "📊 Мой прогресс"
        if user_stats.get('progress_percent', 0) > 0:
            progress_text += f" ({user_stats['progress_percent']}%)"
        buttons.append([InlineKeyboardButton(progress_text, callback_data="t20_progress")])
        
        buttons.extend([
            [InlineKeyboardButton("⚙️ Настройки", callback_data="t20_settings")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ])
        
        return InlineKeyboardMarkup(buttons)
    
    @staticmethod
    def create_result_keyboard(score: int, max_score: int = 3) -> InlineKeyboardMarkup:
        """Клавиатура после проверки с адаптивными кнопками."""
        buttons = []
        
        if score == max_score:
            # Отличный результат
            buttons.append([
                InlineKeyboardButton("🎉 Новая тема", callback_data="t20_new_topic"),
                InlineKeyboardButton("📊 Прогресс", callback_data="t20_progress")
            ])
        elif score >= max_score * 0.6:
            # Хороший результат
            buttons.append([
                InlineKeyboardButton("🔄 Попробовать снова", callback_data="t20_retry"),
                InlineKeyboardButton("📝 Новая тема", callback_data="t20_new_topic")
            ])
        else:
            # Плохой результат
            buttons.append([
                InlineKeyboardButton("🔄 Попробовать снова", callback_data="t20_retry")
            ])
            buttons.append([
                InlineKeyboardButton("📚 Изучить теорию", callback_data="t20_theory"),
                InlineKeyboardButton("💡 Посмотреть примеры", callback_data="t20_examples")
            ])
        
        buttons.append([InlineKeyboardButton("⬅️ В меню", callback_data="t20_menu")])
        
        return InlineKeyboardMarkup(buttons)