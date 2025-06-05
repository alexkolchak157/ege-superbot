import logging
from typing import Dict, Any, List, Optional, Tuple
from core.ai_evaluator import BaseAIEvaluator, TaskRequirements, EvaluationResult
from core.prompts import TASK25_SYSTEM_PROMPT, get_task25_prompt, RUSSIAN_CONTEXT_PROMPT

logger = logging.getLogger(__name__)


class Task25AIEvaluator(BaseAIEvaluator):
    """AI-оценщик для задания 25 ЕГЭ по обществознанию"""
    
    def __init__(self):
        requirements = TaskRequirements(
            task_number=25,
            task_name="Обоснование и примеры",
            max_score=6,
            criteria=[
                {
                    "name": "25.1 Обоснование",
                    "max_score": 2,
                    "description": "Теоретическое обоснование"
                },
                {
                    "name": "25.2 Ответ на вопрос",
                    "max_score": 1,
                    "description": "Правильный ответ на вопрос"
                },
                {
                    "name": "25.3 Примеры",
                    "max_score": 3,
                    "description": "Три примера по 1 баллу"
                }
            ],
            description="Обоснуйте... Назовите... Приведите примеры..."
        )
        super().__init__(requirements)
    
    def get_system_prompt(self) -> str:
        return TASK25_SYSTEM_PROMPT + "\n\n" + RUSSIAN_CONTEXT_PROMPT
    
    async def evaluate(
        self, 
        answer: str, 
        topic: str,
        task_parts: Dict[str, str],
        **kwargs
    ) -> EvaluationResult:
        """
        Оценка ответа на задание 25
        
        Args:
            answer: Ответ ученика
            topic: Общая тема задания
            task_parts: Словарь с тремя частями задания
        """
        
        # Разбиваем ответ на части (если ученик структурировал)
        answer_parts = self._parse_answer_structure(answer)
        
        # Проверяем каждую часть отдельно
        part1_result = await self._evaluate_justification(
            answer_parts.get('part1', answer),
            task_parts['part1']
        )
        
        part2_result = await self._evaluate_answer(
            answer_parts.get('part2', answer),
            task_parts['part2']
        )
        
        part3_result = await self._evaluate_examples(
            answer_parts.get('part3', answer),
            task_parts['part3'],
            part2_answer=answer_parts.get('part2', '')
        )
        
        # Собираем общий результат
        scores = {
            "25.1 Обоснование": part1_result['score'],
            "25.2 Ответ на вопрос": part2_result['score'],
            "25.3 Примеры": part3_result['score']
        }
        
        total_score = sum(scores.values())
        
        # Объединяем анализы
        detailed_analysis = {
            'part1_analysis': part1_result['analysis'],
            'part2_analysis': part2_result['analysis'],
            'part3_analysis': part3_result['analysis'],
            'answer_structure': 'structured' if len(answer_parts) > 1 else 'unstructured'
        }
        
        # Проверка фактических ошибок
        factual_errors = await self.check_factual_accuracy(answer, topic)
        
        # Генерация обратной связи
        feedback = await self._generate_comprehensive_feedback(
            scores, detailed_analysis, topic
        )
        
        # Объединяем рекомендации
        suggestions = []
        for part_result in [part1_result, part2_result, part3_result]:
            suggestions.extend(part_result.get('suggestions', []))
        
        return EvaluationResult(
            scores=scores,
            total_score=total_score,
            max_score=6,
            feedback=feedback,
            detailed_analysis=detailed_analysis,
            suggestions=suggestions[:5],  # Ограничиваем количество
            factual_errors=factual_errors
        )
    
    def _parse_answer_structure(self, answer: str) -> Dict[str, str]:
        """Пытается разделить ответ на части"""
        parts = {}
        
        # Ищем явную нумерацию
        import re
        
        # Паттерны для поиска частей
        patterns = [
            (r'1[\)\.](.+?)(?=2[\)\.]|$)', 'part1'),
            (r'2[\)\.](.+?)(?=3[\)\.]|$)', 'part2'),
            (r'3[\)\.](.+?)$', 'part3')
        ]
        
        for pattern, part_name in patterns:
            match = re.search(pattern, answer, re.DOTALL)
            if match:
                parts[part_name] = match.group(1).strip()
        
        # Если не нашли структуру, возвращаем весь ответ
        if not parts:
            parts['full'] = answer
            
        return parts
    
    async def _evaluate_justification(
        self, 
        answer_part: str,
        task_text: str
    ) -> Dict[str, Any]:
        """Оценка части 1 - обоснование (критерий 25.1)"""
        
        prompt = f"""Оцени ОБОСНОВАНИЕ (часть 1 задания 25).

ТРЕБОВАНИЕ: {task_text}

ОТВЕТ УЧЕНИКА:
{answer_part}

КРИТЕРИИ ОЦЕНКИ ОБОСНОВАНИЯ (макс. 2 балла):
2 балла:
- Несколько связанных распространённых предложений
- Опора на обществоведческие знания
- Раскрыты причинно-следственные/функциональные связи
- Нет ошибок и неточностей

1 балл:
- В целом корректное обоснование
- Есть отдельные неточности, НЕ искажающие суть
- ИЛИ не полностью раскрыты связи

0 баллов:
- Обоснование в одном предложении
- ИЛИ без опоры на теорию
- ИЛИ на бытовом уровне

ФОРМАТ ОТВЕТА JSON:
{{
    "sentences_count": число,
    "has_theory_base": true/false,
    "reveals_connections": true/false,
    "has_errors": true/false,
    "error_details": ["список ошибок"],
    "score": 0/1/2,
    "feedback": "краткий комментарий"
}}"""

        result = await self.ai_service.get_json_completion(
            prompt,
            system_prompt=self.get_system_prompt(),
            temperature=0.2
        )
        
        if not result:
            return {'score': 0, 'analysis': {}, 'suggestions': []}
        
        return {
            'score': result.get('score', 0),
            'analysis': result,
            'suggestions': self._get_justification_suggestions(result)
        }
    
    async def _evaluate_answer(
        self,
        answer_part: str,
        task_text: str
    ) -> Dict[str, Any]:
        """Оценка части 2 - ответ на вопрос (критерий 25.2)"""
        
        prompt = f"""Оцени ОТВЕТ НА ВОПРОС (часть 2 задания 25).

ВОПРОС: {task_text}

ОТВЕТ УЧЕНИКА:
{answer_part}

КРИТЕРИИ (макс. 1 балл):
1 балл:
- Указано правильное количество требуемых элементов
- Все элементы корректны
- Нет неверных позиций
- Ответ дан в явном виде как самостоятельный элемент

0 баллов:
- Неправильное количество элементов
- ИЛИ есть неверные позиции
- ИЛИ ответ не выделен явно

ЕСЛИ ВОПРОС О РОССИИ - проверь актуальность и правильность фактов!

ФОРМАТ ОТВЕТА JSON:
{{
    "required_elements": число,
    "provided_elements": число,
    "elements_list": ["список элементов"],
    "incorrect_elements": ["неверные элементы"],
    "is_explicit": true/false,
    "score": 0/1,
    "feedback": "комментарий"
}}"""

        result = await self.ai_service.get_json_completion(
            prompt,
            system_prompt=self.get_system_prompt(),
            temperature=0.1  # Низкая для фактической точности
        )
        
        if not result:
            return {'score': 0, 'analysis': {}, 'suggestions': []}
        
        return {
            'score': result.get('score', 0),
            'analysis': result,
            'suggestions': self._get_answer_suggestions(result)
        }
    
    async def _evaluate_examples(
        self,
        answer_part: str,
        task_text: str,
        part2_answer: str = ""
    ) -> Dict[str, Any]:
        """Оценка части 3 - примеры (критерий 25.3)"""
        
        # Добавляем контекст из части 2 если есть
        context = ""
        if part2_answer:
            context = f"\nКОНТЕКСТ из части 2: {part2_answer}"
        
        prompt = f"""Оцени ПРИМЕРЫ (часть 3 задания 25).

ТРЕБОВАНИЕ: {task_text}
{context}

ОТВЕТ УЧЕНИКА:
{answer_part}

КРИТЕРИИ (макс. 3 балла):
- По 1 баллу за каждый корректный пример
- Примеры должны быть развёрнутыми
- Должны соответствовать элементам из части 2
- Часто требуется российский контекст

ПРАВИЛА:
- Если есть дополнительные примеры с ошибками:
  * 2+ ошибки = 0 баллов за всё
  * 1 ошибка = -1 балл от результата

ФОРМАТ ОТВЕТА JSON:
{{
    "total_examples": число,
    "examples_analysis": [
        {{
            "num": 1,
            "text": "краткое описание",
            "is_developed": true/false,
            "is_relevant": true/false,
            "matches_part2": true/false,
            "has_russian_context": true/false,
            "is_correct": true/false
        }}
    ],
    "extra_examples_errors": число,
    "valid_examples": число,
    "score": 0-3,
    "feedback": "комментарий"
}}"""

        result = await self.ai_service.get_json_completion(
            prompt,
            system_prompt=self.get_system_prompt(),
            temperature=0.2
        )
        
        if not result:
            return {'score': 0, 'analysis': {}, 'suggestions': []}
        
        # Корректируем балл с учётом правил
        score = result.get('score', 0)
        if result.get('extra_examples_errors', 0) >= 2:
            score = 0
        elif result.get('extra_examples_errors', 0) == 1:
            score = max(0, score - 1)
        
        return {
            'score': score,
            'analysis': result,
            'suggestions': self._get_examples_suggestions(result)
        }
    
    async def _generate_comprehensive_feedback(
        self,
        scores: Dict[str, int],
        analysis: Dict[str, Any],
        topic: str
    ) -> str:
        """Генерация общей обратной связи по заданию 25"""
        
        total = sum(scores.values())
        
        system_prompt = """Ты - опытный преподаватель, даёшь обратную связь по заданию 25.
Будь конкретным и конструктивным. Учитывай, что это самое сложное задание ЕГЭ."""
        
        prompt = f"""Задание 25 по теме "{topic}"
Оценка: {total}/6 баллов

Детализация:
- Обоснование: {scores['25.1 Обоснование']}/2
- Ответ на вопрос: {scores['25.2 Ответ на вопрос']}/1  
- Примеры: {scores['25.3 Примеры']}/3

Напиши обратную связь (3-4 предложения):
1. Что удалось лучше всего
2. Главная проблема (если есть)
3. Конкретный совет для повышения балла
4. Мотивация

НЕ дублируй баллы - они уже показаны."""
        
        result = await self.ai_service.get_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.7
        )
        
        return result["text"] if result["success"] else "Выполнено задание 25."
    
    def _get_justification_suggestions(self, analysis: Dict) -> List[str]:
        """Рекомендации по улучшению обоснования"""
        suggestions = []
        
        if analysis.get('sentences_count', 0) < 3:
            suggestions.append("Развивайте обоснование в нескольких предложениях")
        
        if not analysis.get('has_theory_base'):
            suggestions.append("Используйте теоретические понятия курса обществознания")
        
        if not analysis.get('reveals_connections'):
            suggestions.append("Раскройте причинно-следственные связи")
        
        return suggestions
    
    def _get_answer_suggestions(self, analysis: Dict) -> List[str]:
        """Рекомендации по улучшению ответа на вопрос"""
        suggestions = []
        
        if not analysis.get('is_explicit'):
            suggestions.append("Выделите ответ на вопрос как отдельный элемент")
        
        if analysis.get('incorrect_elements'):
            suggestions.append("Проверьте фактическую точность ответов")
        
        return suggestions
    
    def _get_examples_suggestions(self, analysis: Dict) -> List[str]:
        """Рекомендации по улучшению примеров"""
        suggestions = []
        
        examples = analysis.get('examples_analysis', [])
        
        if any(not ex.get('is_developed') for ex in examples):
            suggestions.append("Формулируйте примеры более развёрнуто")
        
        if any(not ex.get('matches_part2') for ex in examples):
            suggestions.append("Примеры должны соответствовать указанным в п.2 элементам")
        
        return suggestions