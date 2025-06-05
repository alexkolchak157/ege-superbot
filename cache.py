from collections import defaultdict
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)

class QuestionsCache:
    """Кеш для быстрого доступа к вопросам."""
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._by_topic: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._by_exam_num: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        self._by_block: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._is_built = False
        
    def build_from_data(self, questions_data: Dict[str, Dict[str, List[Dict[str, Any]]]]):
        """Строит индексы для быстрого поиска."""
        self.clear()
        
        for block, topics in questions_data.items():
            for topic, questions in topics.items():
                for question in questions:
                    qid = question.get('id')
                    if qid:
                        self._cache[qid] = question
                        self._by_topic[topic].append(question)
                        self._by_block[block].append(question)
                        exam_num = question.get('exam_number')
                        if isinstance(exam_num, int):
                            self._by_exam_num[exam_num].append(question)
        
        self._is_built = True
        logger.info(f"Cache built: {len(self._cache)} questions indexed")
    
    def get_by_id(self, question_id: str) -> Optional[Dict[str, Any]]:
        """Получить вопрос по ID."""
        return self._cache.get(question_id)
    
    def get_by_topic(self, topic: str) -> List[Dict[str, Any]]:
        """Получить все вопросы темы."""
        return self._by_topic.get(topic, [])
    
    def get_by_exam_num(self, exam_num: int) -> List[Dict[str, Any]]:
        """Получить все вопросы по номеру ЕГЭ."""
        return self._by_exam_num.get(exam_num, [])
    
    def get_by_block(self, block: str) -> List[Dict[str, Any]]:
        """Получить все вопросы блока."""
        return self._by_block.get(block, [])
    
    def get_all_exam_numbers(self) -> List[int]:
        """Получить все доступные номера ЕГЭ."""
        return sorted(list(self._by_exam_num.keys()))
    
    def clear(self):
        """Очистить кеш."""
        self._cache.clear()
        self._by_topic.clear()
        self._by_exam_num.clear()
        self._by_block.clear()
        self._is_built = False

# Глобальный экземпляр кеша
questions_cache = QuestionsCache()