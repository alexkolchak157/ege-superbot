import logging
from typing import Dict, Any, List, Optional
from core.ai_evaluator import BaseAIEvaluator, TaskRequirements, EvaluationResult
from core.prompts import TASK20_SYSTEM_PROMPT, get_task20_prompt

logger = logging.getLogger(__name__)


class Task20AIEvaluator(BaseAIEvaluator):
    """AI-оценщик для задания 20 ЕГЭ по обществознанию"""
    
    def __init__(self):
        requirements = TaskRequirements(
            task_number=20,
            task_name="Формулирование суждений",
            max_score=3,
            criteria=[
                {
                    "name": "Корректность суждений",
                    "max_score": 3,
                    "description": "По 1 баллу за каждое корректное суждение"
                }
            ],
            description="Сформулируйте три суждения о..."
        )
        super().__init__(requirements)
    
    def get_system_prompt(self) -> str:
        return TASK20_SYSTEM_PROMPT
    
    async def evaluate(
        self, 
        answer: str, 
        topic: str,
        task_text: str,
        context_info: Dict[str, Any] = None,
        **kwargs
    ) -> EvaluationResult:
        """
        Оценка ответа на задание 20
        
        Ключевое отличие от задания 19:
        - Требуются НЕ примеры, а суждения/объяснения
        - Более абстрактный, теоретический характер
        - Элементы обобщения
        """
        
        evaluation_prompt = f"""Проверь ответ на задание 20 ЕГЭ.

ЗАДАНИЕ: {task_text}
Тема: "{topic}"

ОТВЕТ УЧЕНИКА:
{answer}

КРИТЕРИИ ОЦЕНКИ ЗАДАНИЯ 20:
1. Требуется ТРИ суждения/объяснения (НЕ примеры!)
2. Суждения должны быть:
   - Теоретическими (содержать обобщения)
   - Корректными с точки зрения обществознания
   - Логичными и непротиворечивыми
   - Содержательными (не банальными)
   - Соответствующими теме

ВАЖНО: 
- Суждение ≠ конкретный пример
- Суждение = обобщённое утверждение, закономерность, объяснение

АЛГОРИТМ ПРОВЕРКИ:
1. Определи количество суждений
2. Проверь каждое суждение на соответствие критериям
3. Особое внимание: не путает ли ученик суждения с примерами

ФОРМАТ ОТВЕТА JSON:
{{
    "total_statements_count": число,
    "statements_analysis": [
        {{
            "statement_num": 1,
            "text": "краткое содержание суждения",
            "is_theoretical": true/false,
            "is_correct": true/false,
            "is_logical": true/false,
            "is_meaningful": true/false,
            "is_relevant": true/false,
            "is_example_not_statement": true/false,
            "issue": "описание проблемы или null"
        }}
    ],
    "valid_statements_count": число,
    "score": число от 0 до 3,
    "main_issues": ["список проблем"],
    "suggestions": ["рекомендации"]
}}"""

        # Добавляем контекстную информацию если есть
        if context_info:
            evaluation_prompt += f"\n\nДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ:\n{context_info}"
        
        result = await self.ai_service.get_json_completion(
            get_task20_prompt(task_text, answer),
            system_prompt=self.get_system_prompt(),
            temperature=0.2
        )
        
        if not result:
            return self._get_fallback_result()
        
        # Расчёт финального балла
        score = self._calculate_score(result)
        
        # Проверка фактических ошибок
        factual_errors = await self.check_factual_accuracy(answer, topic)
        
        # Персонализированная обратная связь
        feedback = await self._generate_feedback(answer, score, result)
        
        return EvaluationResult(
            scores={"Корректность суждений": score},
            total_score=score,
            max_score=3,
            feedback=feedback,
            detailed_analysis=result,
            suggestions=result.get("suggestions", []),
            factual_errors=factual_errors
        )
    
    def _calculate_score(self, analysis: Dict[str, Any]) -> int:
        """Расчёт балла с учётом правил задания 20"""
        
        # Проверяем дополнительные суждения на ошибки
        statements = analysis.get("statements_analysis", [])
        
        # Если есть дополнительные суждения (больше 3)
        if len(statements) > 3:
            # Проверяем дополнительные на ошибки
            extra_statements = statements[3:]
            errors_count = 0
            
            for stmt in extra_statements:
                if (not stmt.get("is_correct", False) or 
                    not stmt.get("is_logical", False) or
                    stmt.get("is_example_not_statement", False)):
                    errors_count += 1
            
            # Применяем правила ЕГЭ
            if errors_count >= 2:
                return 0
            elif errors_count == 1:
                # Снижаем на 1 балл
                base_score = min(analysis.get("valid_statements_count", 0), 3)
                return max(0, base_score - 1)
        
        # Стандартный подсчёт
        return min(analysis.get("valid_statements_count", 0), 3)
    
    async def _generate_feedback(
        self, 
        answer: str,
        score: int,
        analysis: Dict[str, Any]
    ) -> str:
        """Генерация обратной связи для задания 20"""
        
        system_prompt = """Ты - преподаватель обществознания.
Дай краткую обратную связь по заданию 20. Будь конструктивным."""
        
        # Анализ основных проблем
        main_problem = ""
        if any(s.get("is_example_not_statement") for s in analysis.get("statements_analysis", [])):
            main_problem = "путаете суждения с конкретными примерами"
        elif score < 3:
            main_problem = "не все суждения корректны или обоснованы"
        
        prompt = f"""Задание 20 - формулирование суждений.
Оценка: {score}/3

Главная проблема: {main_problem or 'нет'}

Составь обратную связь (2-3 предложения):
1. Что удалось
2. Главный недочёт (если есть)
3. Совет для улучшения"""
        
        result = await self.ai_service.get_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.7
        )
        
        return result["text"] if result["success"] else ""
    
    def _get_fallback_result(self) -> EvaluationResult:
        return EvaluationResult(
            scores={"Корректность суждений": 1},
            total_score=1,
            max_score=3,
            feedback="Требуется дополнительная проверка преподавателем.",
            detailed_analysis={},
            suggestions=[
                "Формулируйте обобщённые суждения, а не примеры",
                "Используйте теоретические понятия курса",
                "Обосновывайте причинно-следственные связи"
            ],
            factual_errors=[]
        )
