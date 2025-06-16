"""Утилиты для работы с заданием 25."""

import random
import logging
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class TopicSelector:
    """Класс для интеллектуального выбора тем."""
    
    def __init__(self, topics: List[Dict]):
        """
        Инициализация селектора тем.
        
        Args:
            topics: Список всех доступных тем
        """
        self.topics = topics
        self.topic_by_id = {topic['id']: topic for topic in topics}
        self.used_topics: Dict[int, Set[str]] = {}  # user_id -> set of topic_ids
        self.topic_history: Dict[int, List[Dict]] = {}  # user_id -> list of attempts
        
    def get_random_topic(self, user_id: int, exclude_recent: int = 5) -> Optional[Dict]:
        """
        Получить случайную тему с учётом истории пользователя.
        
        Args:
            user_id: ID пользователя
            exclude_recent: Количество последних тем для исключения
            
        Returns:
            Словарь с данными темы или None
        """
        if not self.topics:
            return None
        
        # Получаем историю пользователя
        user_history = self.topic_history.get(user_id, [])
        recent_topic_ids = [h['topic_id'] for h in user_history[-exclude_recent:]]
        
        # Фильтруем доступные темы
        available_topics = [
            topic for topic in self.topics 
            if topic['id'] not in recent_topic_ids
        ]
        
        # Если все темы недавно использовались, берём из всех
        if not available_topics:
            available_topics = self.topics
        
        # Выбираем случайную тему
        selected = random.choice(available_topics)
        
        # Записываем в историю
        self._add_to_history(user_id, selected['id'])
        
        return selected
    
    def get_topic_by_difficulty(self, user_id: int, difficulty: str) -> Optional[Dict]:
        """
        Получить тему определённой сложности.
        
        Args:
            user_id: ID пользователя
            difficulty: Уровень сложности (easy, medium, hard)
            
        Returns:
            Словарь с данными темы или None
        """
        filtered_topics = [
            topic for topic in self.topics
            if topic.get('difficulty', 'medium') == difficulty
        ]
        
        if not filtered_topics:
            logger.warning(f"No topics found for difficulty: {difficulty}")
            return self.get_random_topic(user_id)
        
        # Выбираем из отфильтрованных
        return random.choice(filtered_topics)
    
    def get_topic_by_block(self, user_id: int, block_name: str) -> Optional[Dict]:
        """
        Получить тему из определённого блока.
        
        Args:
            user_id: ID пользователя
            block_name: Название блока
            
        Returns:
            Словарь с данными темы или None
        """
        filtered_topics = [
            topic for topic in self.topics
            if topic.get('block') == block_name
        ]
        
        if not filtered_topics:
            logger.warning(f"No topics found for block: {block_name}")
            return None
        
        return random.choice(filtered_topics)
    
    def get_recommended_topic(self, user_id: int, user_stats: Dict) -> Optional[Dict]:
        """
        Получить рекомендованную тему на основе статистики пользователя.
        
        Args:
            user_id: ID пользователя
            user_stats: Статистика решений пользователя
            
        Returns:
            Словарь с данными темы или None
        """
        # Анализируем слабые места пользователя
        weak_blocks = self._analyze_weak_areas(user_stats)
        
        if weak_blocks:
            # Выбираем тему из слабого блока
            block = random.choice(weak_blocks)
            return self.get_topic_by_block(user_id, block)
        
        # Если слабых мест нет, даём случайную тему повышенной сложности
        return self.get_topic_by_difficulty(user_id, 'hard')
    
    def _add_to_history(self, user_id: int, topic_id: str):
        """Добавить тему в историю пользователя."""
        if user_id not in self.topic_history:
            self.topic_history[user_id] = []
        
        self.topic_history[user_id].append({
            'topic_id': topic_id,
            'timestamp': datetime.now()
        })
        
        # Ограничиваем размер истории
        if len(self.topic_history[user_id]) > 50:
            self.topic_history[user_id] = self.topic_history[user_id][-50:]
    
    def _analyze_weak_areas(self, user_stats: Dict) -> List[str]:
        """
        Анализировать слабые области пользователя.
        
        Args:
            user_stats: Статистика по темам
            
        Returns:
            Список блоков, где у пользователя низкие результаты
        """
        weak_blocks = []
        block_scores = {}
        
        # Группируем результаты по блокам
        for topic_id, stats in user_stats.items():
            if topic_id in self.topic_by_id and stats.get('scores'):
                topic = self.topic_by_id[topic_id]
                block = topic.get('block', 'unknown')
                
                if block not in block_scores:
                    block_scores[block] = []
                
                # Берём последний результат
                block_scores[block].append(stats['scores'][-1])
        
        # Находим блоки со средним баллом < 3
        for block, scores in block_scores.items():
            if scores:
                avg_score = sum(scores) / len(scores)
                if avg_score < 3:
                    weak_blocks.append(block)
        
        return weak_blocks
    
    def get_statistics(self, user_id: int) -> Dict:
        """
        Получить статистику по использованию тем.
        
        Args:
            user_id: ID пользователя
            
        Returns:
            Словарь со статистикой
        """
        user_history = self.topic_history.get(user_id, [])
        
        # Считаем использование по блокам
        block_usage = {}
        for record in user_history:
            topic_id = record['topic_id']
            if topic_id in self.topic_by_id:
                topic = self.topic_by_id[topic_id]
                block = topic.get('block', 'unknown')
                block_usage[block] = block_usage.get(block, 0) + 1
        
        return {
            'total_attempts': len(user_history),
            'unique_topics': len(set(r['topic_id'] for r in user_history)),
            'block_usage': block_usage,
            'last_attempt': user_history[-1]['timestamp'] if user_history else None
        }


def format_topic_for_display(topic: Dict) -> str:
    """
    Форматировать тему для отображения пользователю.
    
    Args:
        topic: Словарь с данными темы
        
    Returns:
        Отформатированная строка
    """
    parts = []
    
    # Заголовок
    parts.append(f"<b>{topic.get('title', 'Без названия')}</b>")
    
    # Текст задания
    task_text = topic.get('task_text', '')
    if task_text:
        parts.append(f"\n{task_text}")
    
    # Части задания
    topic_parts = topic.get('parts', {})
    if topic_parts:
        parts.append("\n<b>Задание состоит из частей:</b>")
        
        if topic_parts.get('part1'):
            parts.append(f"1️⃣ {topic_parts['part1']}")
        if topic_parts.get('part2'):
            parts.append(f"2️⃣ {topic_parts['part2']}")
        if topic_parts.get('part3'):
            parts.append(f"3️⃣ {topic_parts['part3']}")
    
    # Метаинформация
    meta_parts = []
    if 'block' in topic:
        meta_parts.append(f"Блок: {topic['block']}")
    if 'difficulty' in topic:
        difficulty_emoji = {
            'easy': '🟢',
            'medium': '🟡',
            'hard': '🔴'
        }
        emoji = difficulty_emoji.get(topic['difficulty'], '⚪')
        meta_parts.append(f"Сложность: {emoji}")
    
    if meta_parts:
        parts.append(f"\n<i>{' • '.join(meta_parts)}</i>")
    
    return '\n'.join(parts)


def validate_answer_structure(answer: str) -> Dict[str, any]:
    """
    Проверить структуру ответа на соответствие требованиям.
    
    Args:
        answer: Ответ пользователя
        
    Returns:
        Словарь с результатами проверки
    """
    # Разбиваем на абзацы
    paragraphs = [p.strip() for p in answer.split('\n\n') if p.strip()]
    
    # Проверяем минимальную длину
    min_length = 150  # символов
    
    # Проверяем наличие ключевых слов для каждой части
    part1_keywords = ['обоснование', 'объяснение', 'потому что', 'так как', 'поскольку']
    part2_keywords = ['ответ', 'да', 'нет', 'считаю', 'полагаю']
    part3_keywords = ['пример', 'например', 'во-первых', 'во-вторых', 'в-третьих', '1)', '2)', '3)']
    
    has_part1 = any(keyword in answer.lower() for keyword in part1_keywords)
    has_part2 = len(paragraphs) >= 2
    has_part3 = any(keyword in answer.lower() for keyword in part3_keywords)
    
    # Считаем примеры
    example_count = 0
    for marker in ['1)', '2)', '3)', 'во-первых', 'во-вторых', 'в-третьих', 'пример']:
        example_count += answer.lower().count(marker)
    
    return {
        'total_length': len(answer),
        'paragraph_count': len(paragraphs),
        'meets_min_length': len(answer) >= min_length,
        'has_reasoning': has_part1,
        'has_answer': has_part2,
        'has_examples': has_part3,
        'example_count': min(example_count, 3),
        'structure_ok': len(paragraphs) >= 3 and len(answer) >= min_length
    }