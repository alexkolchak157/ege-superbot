"""Утилиты для модуля task25."""

import random
from typing import List, Dict, Optional, Set
from difflib import SequenceMatcher

class TopicSelector:
    """Класс для умного выбора тем."""
    
    def __init__(self, topics: List[Dict]):
        self.topics = topics
        self.topic_by_id = {t['id']: t for t in topics}
        self.topics_by_block = self._group_by_block(topics)
    
    def _group_by_block(self, topics: List[Dict]) -> Dict[str, List[Dict]]:
        """Группирует темы по блокам."""
        grouped = {}
        for topic in topics:
            block = topic.get('block', 'Другое')
            if block not in grouped:
                grouped[block] = []
            grouped[block].append(topic)
        return grouped
    
    def get_random_topic(
        self, 
        block: Optional[str] = None,
        exclude_ids: Optional[Set[int]] = None
    ) -> Optional[Dict]:
        """Возвращает случайную тему."""
        if block:
            pool = self.topics_by_block.get(block, [])
        else:
            pool = self.topics
        
        if exclude_ids:
            pool = [t for t in pool if t['id'] not in exclude_ids]
        
        return random.choice(pool) if pool else None
    
    def search_topics(self, query: str, threshold: float = 0.6) -> List[Dict]:
        """Поиск тем по запросу."""
        query_lower = query.lower()
        results = []
        
        for topic in self.topics:
            # Ищем в названии
            title_score = SequenceMatcher(
                None, 
                query_lower, 
                topic.get('title', '').lower()
            ).ratio()
            
            # Ищем в тексте задания
            task_score = 0
            task_text = topic.get('task_text', '').lower()
            if query_lower in task_text:
                task_score = 0.8
            else:
                task_score = SequenceMatcher(
                    None, 
                    query_lower, 
                    task_text[:200]  # Первые 200 символов
                ).ratio() * 0.5
            
            # Максимальный счёт
            score = max(title_score, task_score)
            
            if score >= threshold:
                results.append((score, topic))
        
        # Сортируем по релевантности
        results.sort(key=lambda x: x[0], reverse=True)
        
        return [topic for _, topic in results[:10]]  # Топ-10
    
    def get_recommended_topics(
        self, 
        completed_ids: Set[int],
        last_topic_id: Optional[int] = None,
        limit: int = 3
    ) -> List[Dict]:
        """Рекомендует следующие темы на основе прогресса."""
        # Непройденные темы
        not_completed = [
            t for t in self.topics 
            if t['id'] not in completed_ids
        ]
        
        if not not_completed:
            # Если всё пройдено, предлагаем повторить сложные
            return random.sample(self.topics, min(limit, len(self.topics)))
        
        # Если есть последняя тема, ищем похожие
        if last_topic_id and last_topic_id in self.topic_by_id:
            last_topic = self.topic_by_id[last_topic_id]
            last_block = last_topic.get('block')
            
            # Приоритет темам из того же блока
            same_block = [
                t for t in not_completed 
                if t.get('block') == last_block
            ]
            
            if same_block:
                recommendations = random.sample(
                    same_block, 
                    min(limit, len(same_block))
                )
                
                # Добавляем из других блоков если нужно
                if len(recommendations) < limit:
                    other_blocks = [
                        t for t in not_completed 
                        if t.get('block') != last_block
                    ]
                    if other_blocks:
                        additional = random.sample(
                            other_blocks,
                            min(limit - len(recommendations), len(other_blocks))
                        )
                        recommendations.extend(additional)
                
                return recommendations
        
        # Иначе просто случайные непройденные
        return random.sample(not_completed, min(limit, len(not_completed)))


def format_score_emoji(score: int, max_score: int) -> str:
    """Возвращает эмодзи в зависимости от результата."""
    percentage = (score / max_score) * 100 if max_score > 0 else 0
    
    if percentage >= 90:
        return "🏆"
    elif percentage >= 75:
        return "✨"
    elif percentage >= 60:
        return "👍"
    elif percentage >= 40:
        return "💪"
    else:
        return "📚"


def split_answer_parts(answer: str) -> Dict[str, str]:
    """Пытается разделить ответ на три части."""
    # Ищем маркеры частей
    lines = answer.strip().split('\n')
    
    parts = {
        'part1': '',
        'part2': '',
        'part3': ''
    }
    
    current_part = None
    current_text = []
    
    for line in lines:
        line_lower = line.lower().strip()
        
        # Определяем начало новой части
        if any(marker in line_lower for marker in ['обоснован', '1)', '1.', 'часть 1']):
            if current_part and current_text:
                parts[current_part] = '\n'.join(current_text).strip()
            current_part = 'part1'
            current_text = []
            # Если маркер в отдельной строке, пропускаем её
            if len(line.strip()) < 20:
                continue
        
        elif any(marker in line_lower for marker in ['ответ', '2)', '2.', 'часть 2']):
            if current_part and current_text:
                parts[current_part] = '\n'.join(current_text).strip()
            current_part = 'part2'
            current_text = []
            if len(line.strip()) < 20:
                continue
        
        elif any(marker in line_lower for marker in ['пример', '3)', '3.', 'часть 3']):
            if current_part and current_text:
                parts[current_part] = '\n'.join(current_text).strip()
            current_part = 'part3'
            current_text = []
            if len(line.strip()) < 20:
                continue
        
        # Добавляем строку к текущей части
        if current_part:
            current_text.append(line)
    
    # Сохраняем последнюю часть
    if current_part and current_text:
        parts[current_part] = '\n'.join(current_text).strip()
    
    # Если не удалось разделить, пытаемся по пустым строкам
    if not any(parts.values()):
        sections = answer.strip().split('\n\n')
        if len(sections) >= 3:
            parts['part1'] = sections[0]
            parts['part2'] = sections[1]
            parts['part3'] = '\n\n'.join(sections[2:])
    
    return parts


def validate_topic_data(topic: Dict) -> bool:
    """Проверяет корректность данных темы."""
    required_fields = ['id', 'title', 'task_text', 'block']
    
    for field in required_fields:
        if field not in topic or not topic[field]:
            return False
    
    # Проверяем наличие примеров ответов
    if 'example_answers' in topic:
        examples = topic['example_answers']
        if not isinstance(examples, dict):
            return False
        
        # Проверяем структуру примеров
        if 'part1' in examples and not isinstance(examples['part1'], dict):
            return False
        if 'part2' in examples and not isinstance(examples['part2'], dict):
            return False
        if 'part3' in examples and not isinstance(examples['part3'], list):
            return False
    
    return True