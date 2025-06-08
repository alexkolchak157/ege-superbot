"""AI-оценщик для задания 19."""

import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Безопасный импорт базовых классов
try:
    from core.ai_evaluator import (
        BaseAIEvaluator,
        EvaluationResult,
        TaskRequirements,
    )
    AI_EVALUATOR_AVAILABLE = True
except ImportError:
    logger.warning("AI evaluator base classes not available")
    AI_EVALUATOR_AVAILABLE = False
    
    # Заглушки для работы без AI
    @dataclass
    class TaskRequirements:
        task_number: int
        task_name: str
        max_score: int
        criteria: List[Dict]
        description: str
    
    @dataclass
    class EvaluationResult:
        scores: Dict[str, int]
        total_score: int
        max_score: int
        feedback: str
        detailed_analysis: Optional[Dict] = None
        suggestions: Optional[List[str]] = None
        factual_errors: Optional[List[str]] = None
    
    class BaseAIEvaluator:
        def __init__(self, requirements: TaskRequirements):
            self.requirements = requirements


class Task19AIEvaluator(BaseAIEvaluator):
    """AI-оценщик для задания 19 ЕГЭ по обществознанию"""
    
    def __init__(self):
        requirements = TaskRequirements(
            task_number=19,
            task_name="Примеры социальных объектов",
            max_score=3,
            criteria=[
                {
                    "name": "Правильность примеров",
                    "max_score": 3,
                    "description": "По 1 баллу за каждый корректный пример (максимум 3)"
                }
            ],
            description="Приведите три примера, иллюстрирующих..."
        )
        super().__init__(requirements)
        
        # Проверяем доступность AI сервиса
        self.ai_available = False
        if AI_EVALUATOR_AVAILABLE:
            try:
                # Проверяем, что AI сервис инициализирован
                if hasattr(self, 'ai_service') and self.ai_service:
                    self.ai_available = True
            except:
                pass
    
    def get_system_prompt(self) -> str:
        return """Ты - эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 19.

КРИТЕРИИ ОЦЕНИВАНИЯ ЗАДАНИЯ 19 (ЕГЭ 2025):
1. Требуется привести ТРИ примера, иллюстрирующих теоретическое положение
2. Каждый пример = 1 балл (максимум 3 балла)
3. Примеры должны быть:
   - Развёрнутыми (НЕ отдельные слова или словосочетания)
   - Конкретными (локализованы в пространстве/времени)
   - Соответствующими заданию
   - Фактически правильными

ВАЖНЫЕ ПРАВИЛА:
- Если приведено 4+ примера и хотя бы один содержит ошибку - НЕ ЗАСЧИТЫВАТЬ весь ответ (0 баллов)
- Если приведено ровно 3 примера - засчитывать только корректные
- Примеры из искусства, истории, личного опыта, СМИ - все допустимы
- Степень конкретизации может быть разной, но пример должен быть узнаваемым"""
    
    async def evaluate(
        self, 
        answer: str, 
        topic: str,
        task_text: str,
        key_points: List[str] = None,
        **kwargs
    ) -> EvaluationResult:
        """
        Оценка ответа на задание 19
        
        Args:
            answer: Ответ ученика
            topic: Тема задания
            task_text: Полный текст задания
            key_points: Ключевые аспекты для проверки
        """
        
        # Подготовка промпта для оценки
        key_points_text = ""
        if key_points:
            key_points_text = f"\nКлючевые аспекты для проверки:\n" + "\n".join([f"- {kp}" for kp in key_points])
        
        evaluation_prompt = f"""Проверь ответ на задание 19 ЕГЭ по обществознанию.

ЗАДАНИЕ: {task_text}
Тема: "{topic}"
{key_points_text}

ОТВЕТ УЧЕНИКА:
{answer}

АЛГОРИТМ ПРОВЕРКИ:
1. Подсчитай общее количество приведённых примеров
2. Если примеров больше 3, проверь ВСЕ на наличие ошибок
3. Для каждого примера определи:
   - Является ли он развёрнутым (не просто слово/словосочетание)
   - Соответствует ли теме задания
   - Конкретен ли (есть детали, контекст)
   - Фактически корректен ли
   - Не дублирует ли другой пример

ФОРМАТ ОТВЕТА:
{{
    "total_examples_count": число,
    "has_extra_examples": true/false,
    "examples_analysis": [
        {{
            "example_num": 1,
            "text": "краткое описание примера",
            "is_developed": true/false,
            "is_relevant": true/false,
            "is_specific": true/false,
            "is_correct": true/false,
            "is_duplicate": true/false,
            "error_description": "описание ошибки или null"
        }},
        ...
    ],
    "valid_examples_count": число (сколько примеров можно засчитать),
    "score": число от 0 до 3,
    "scoring_explanation": "объяснение выставленной оценки",
    "main_issues": ["список основных проблем"],
    "suggestions": ["конкретные рекомендации"]
}}"""

        result = await self.ai_service.get_json_completion(
            evaluation_prompt,
            system_prompt=self.get_system_prompt(),
            temperature=0.2
        )
        
        if not result:
            return self._get_fallback_result(answer, topic)
        
        # Определение финального балла с учётом правил ЕГЭ 2025
        score = self._calculate_final_score(result)
        
        # Проверка фактических ошибок
        factual_errors = await self.check_factual_accuracy(answer, topic)
        
        # Генерация персонализированной обратной связи
        feedback = await self._generate_task19_feedback(
            answer, score, result, topic
        )
        
        return EvaluationResult(
            scores={"Правильность примеров": score},
            total_score=score,
            max_score=3,
            feedback=feedback,
            detailed_analysis=result,
            suggestions=result.get("suggestions", []),
            factual_errors=factual_errors
        )
    
    def _calculate_final_score(self, analysis: Dict[str, Any]) -> int:
        """Расчёт финального балла с учётом правил ЕГЭ 2025"""
        
        # Если есть дополнительные примеры с ошибками
        if analysis.get("has_extra_examples", False):
            examples = analysis.get("examples_analysis", [])
            extra_examples = [ex for ex in examples[3:] if ex.get("example_num", 0) > 3]
            
            # Проверяем наличие ошибок в дополнительных примерах
            for ex in extra_examples:
                if not all([
                    ex.get("is_developed", False),
                    ex.get("is_relevant", False),
                    ex.get("is_specific", False),
                    ex.get("is_correct", False),
                    not ex.get("is_duplicate", False)
                ]):
                    # Есть ошибка в дополнительном примере - 0 баллов
                    logger.info("Обнаружена ошибка в дополнительном примере - выставляется 0 баллов")
                    return 0
        
        # Иначе считаем по обычным правилам
        return min(analysis.get("valid_examples_count", 0), 3)
    
    async def _generate_task19_feedback(
        self,
        answer: str,
        score: int,
        analysis: Dict[str, Any],
        topic: str
    ) -> str:
        """Генерация развёрнутой обратной связи для задания 19"""
        
        system_prompt = """Ты - опытный преподаватель обществознания, даёшь обратную связь по заданию 19.
Будь конкретным, доброжелательным и конструктивным. Используй эмодзи для наглядности."""
        
        examples_info = []
        for ex in analysis.get("examples_analysis", [])[:3]:
            status = "✅" if all([
                ex.get("is_developed"), ex.get("is_relevant"),
                ex.get("is_specific"), ex.get("is_correct")
            ]) else "❌"
            examples_info.append(f"{status} Пример {ex['example_num']}")
        
        prompt = f"""Ученик выполнял задание 19 по теме "{topic}".
Оценка: {score}/3 балла

Статус примеров:
{chr(10).join(examples_info)}

Основные проблемы: {', '.join(analysis.get('main_issues', [])) or 'нет'}

Составь краткую обратную связь (3-4 предложения):
1. Что получилось хорошо
2. Главная проблема (если есть) 
3. Конкретный совет для улучшения
4. Мотивирующее заключение

НЕ повторяй баллы и оценки - они уже показаны."""
        
        result = await self.ai_service.get_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.7
        )
        
        return result["text"] if result["success"] else ""
    
    def _get_fallback_result(self, answer: str, topic: str) -> EvaluationResult:
        """Простая оценка без AI"""
        # Подсчитываем примеры (строки длиннее 20 символов)
        lines = [line.strip() for line in answer.split('\n') if line.strip()]
        examples = [line for line in lines if len(line) > 20]
        examples_count = len(examples)
        
        # Простая оценка
        score = min(examples_count, 3) if examples_count <= 3 else 0
        
        feedback = f"Найдено примеров: {examples_count}\n"
        if examples_count < 3:
            feedback += "❌ Необходимо привести три примера.\n"
        elif examples_count == 3:
            feedback += "✅ Количество примеров соответствует требованиям.\n"
        else:
            feedback += "⚠️ Приведено больше трех примеров. Если хотя бы один содержит ошибку, все примеры не засчитываются.\n"
        
        suggestions = []
        if examples_count < 3:
            suggestions.append("Добавьте больше конкретных примеров")
        if any(len(ex) < 50 for ex in examples):
            suggestions.append("Сделайте примеры более развернутыми и конкретными")
        
        return EvaluationResult(
            scores={"Правильность примеров": score},
            total_score=score,
            max_score=3,
            feedback=feedback,
            suggestions=suggestions
        )
