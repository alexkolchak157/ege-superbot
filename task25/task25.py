"""
Модуль для оценивания задания 25 ЕГЭ по обществознанию.

Задание 25 - составное задание высокого уровня сложности, включающее:
1. Обоснование тезиса (0-2 балла)
2. Ответ на вопрос с перечислением элементов (0-1 балл) 
3. Примеры для каждого элемента (0-3 балла)
Максимальный балл: 6
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import re
from base_evaluator import BaseEvaluator, EvaluationResult, TaskInfo
from task25_evaluator import evaluate_task25


@dataclass
class Task25Components:
    """Компоненты ответа на задание 25."""
    justification: Optional[str] = None  # Обоснование
    answer_elements: List[str] = []  # Элементы ответа на вопрос
    examples: List[str] = []  # Примеры


class Task25Evaluator(BaseEvaluator):
    """Оценивание задания 25 - составное задание с обоснованием и примерами."""
    
    def __init__(self, task_info: TaskInfo):
        super().__init__(task_info)
        self.max_score = 6
        self.criteria_weights = {
            '25.1': 2,  # Обоснование
            '25.2': 1,  # Ответ на вопрос
            '25.3': 3   # Примеры
        }
    
    def parse_answer_structure(self, answer: str) -> Task25Components:
        """Разбор структуры ответа на компоненты."""
        components = Task25Components()
        
        # Нормализация текста
        answer = answer.strip()
        
        # Паттерны для выделения частей ответа
        patterns = {
            'justification': [
                r'(?:1\)|1\.|1[\s\)])[^2\)2\.3\)3\.]*?(?=(?:2\)|2\.|2[\s\)])|$)',
                r'(?:^|(?<=\n))(?:Обоснование:|Обосновываю:|Обосную)[^\n]*(?:\n(?![2-3]\)|[2-3]\.|Ответ|Пример)[^\n]*)*'
            ],
            'answer': [
                r'(?:2\)|2\.|2[\s\)])[^1\)1\.3\)3\.]*?(?=(?:3\)|3\.|3[\s\)])|$)',
                r'(?:Ответ на вопрос:|Элементы:|Способы:|Мотивы:|Функции:)[^\n]*(?:\n(?![1,3]\)|[1,3]\.|Пример|Обоснование)[^\n]*)*'
            ],
            'examples': [
                r'(?:3\)|3\.|3[\s\)])[^1\)1\.2\)2\.]*?$',
                r'(?:Примеры:|Например:|Иллюстрирую:)[^\n]*(?:\n(?![1-2]\)|[1-2]\.|Обоснование|Ответ)[^\n]*)*'
            ]
        }
        
        # Извлечение обоснования
        for pattern in patterns['justification']:
            match = re.search(pattern, answer, re.MULTILINE | re.DOTALL | re.IGNORECASE)
            if match:
                components.justification = match.group().strip()
                # Удаляем номер пункта
                components.justification = re.sub(r'^(?:1\)|1\.|1[\s\)])\s*', '', components.justification)
                break
        
        # Извлечение ответа на вопрос
        for pattern in patterns['answer']:
            match = re.search(pattern, answer, re.MULTILINE | re.DOTALL | re.IGNORECASE)
            if match:
                answer_text = match.group().strip()
                answer_text = re.sub(r'^(?:2\)|2\.|2[\s\)])\s*', '', answer_text)
                components.answer_elements = self._extract_list_items(answer_text)
                break
        
        # Извлечение примеров
        for pattern in patterns['examples']:
            match = re.search(pattern, answer, re.MULTILINE | re.DOTALL | re.IGNORECASE)
            if match:
                examples_text = match.group().strip()
                examples_text = re.sub(r'^(?:3\)|3\.|3[\s\)])\s*', '', examples_text)
                components.examples = self._extract_list_items(examples_text)
                break
        
        return components
    
    def _extract_list_items(self, text: str) -> List[str]:
        """Извлечение элементов списка из текста."""
        items = []
        
        # Удаляем вводные фразы
        text = re.sub(r'^(?:Ответ на вопрос:|Элементы:|Способы:|Мотивы:|Функции:|Примеры:|Например:)\s*', '', text, flags=re.IGNORECASE)
        
        # Паттерны для различных форматов списков
        patterns = [
            (r'[а-яА-Я]\)\s*([^а-яА-Я\)]+)', 1),  # а) элемент
            (r'(?:^|\n)\d+\)\s*([^\n]+?)(?=\n\d+\)|$)', 1),  # 1) элемент
            (r'(?:^|\n)[-–—•]\s*([^\n]+?)(?=\n[-–—•]|$)', 1),  # - элемент
            (r'(?:^|\n)(\d+\.\s*[^\n]+?)(?=\n\d+\.|$)', 1),  # 1. элемент
        ]
        
        for pattern, group in patterns:
            matches = re.findall(pattern, text, re.MULTILINE | re.DOTALL)
            if matches:
                items = [m.strip() if isinstance(m, str) else m[group-1].strip() for m in matches]
                items = [item for item in items if len(item) > 10]
                if items:
                    break
        
        # Если не нашли структурированный список, пробуем по точкам с запятой или точкам
        if not items:
            # Сначала пробуем точку с запятой
            parts = text.split(';')
            if len(parts) > 1:
                items = [p.strip() for p in parts if len(p.strip()) > 20]
            else:
                # Затем по точкам, но осторожно
                sentences = re.split(r'(?<=[.!?])\s+', text)
                items = [s.strip() for s in sentences if len(s.strip()) > 20 and not s.strip().endswith(':')]
        
        return items[:6]  # Ограничиваем количество элементов
    
    def evaluate(self, answer: str) -> EvaluationResult:
        """Основной метод оценивания задания 25."""
        # Используем AI для оценки
        ai_result = evaluate_task25(
            task_prompt=self.task_info.prompt,
            student_answer=answer,
            reference_answer=self.task_info.reference_answer
        )
        
        # Извлекаем оценки по критериям
        criteria_scores = {
            '25.1': ai_result.get('score_25_1', 0),
            '25.2': ai_result.get('score_25_2', 0),
            '25.3': ai_result.get('score_25_3', 0)
        }
        
        total_score = sum(criteria_scores.values())
        
        # Формируем обратную связь
        feedback_parts = []
        
        # Обоснование
        feedback_parts.append(f"**Критерий 25.1 (Обоснование): {criteria_scores['25.1']}/2**")
        feedback_parts.append(ai_result.get('feedback_25_1', 'Нет обратной связи'))
        
        # Ответ на вопрос
        feedback_parts.append(f"\n**Критерий 25.2 (Ответ на вопрос): {criteria_scores['25.2']}/1**")
        feedback_parts.append(ai_result.get('feedback_25_2', 'Нет обратной связи'))
        
        # Примеры
        feedback_parts.append(f"\n**Критерий 25.3 (Примеры): {criteria_scores['25.3']}/3**")
        feedback_parts.append(ai_result.get('feedback_25_3', 'Нет обратной связи'))
        
        # Общие рекомендации
        if ai_result.get('recommendations'):
            feedback_parts.append(f"\n**Рекомендации:**")
            feedback_parts.append(ai_result['recommendations'])
        
        return EvaluationResult(
            score=total_score,
            max_score=self.max_score,
            feedback='\n'.join(feedback_parts),
            criteria_scores=criteria_scores
        )