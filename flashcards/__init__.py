"""
Модуль карточек (Flashcards) для заучивания материала ЕГЭ.

Поддерживает:
- Колоды карточек по Конституции РФ (задание 23)
- Глоссарий терминов по обществознанию
- Алгоритм интервального повторения SM-2
- Интеграция со стриками
"""

from .plugin import FlashcardsPlugin, plugin
from .handlers import init_flashcards_data

__all__ = [
    'FlashcardsPlugin',
    'plugin',
    'init_flashcards_data',
]
