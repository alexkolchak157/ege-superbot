"""AI-оценщик для задания 19."""

import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
from dataclasses import dataclass
from typing import Dict

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

class StrictnessLevel(Enum):
    """Уровни строгости проверки"""
    BASIC = "Базовый"
    STANDARD = "Стандартный"  
    STRICT = "Строгий"
    EXPERT = "Экспертный"

@dataclass
class StrictnessConfig:
    """Конфигурация параметров строгости."""
    level: StrictnessLevel
    min_example_length: int          # Минимальная длина примера в символах
    require_localization: bool       # Требовать локализацию в пространстве/времени
    require_specific_details: bool   # Требовать конкретные детали
    penalize_extra_errors: bool      # Применять правило вычета за доп. ошибки
    temperature: float               # Температура для AI (ниже = строже)
    
    @classmethod
    def get_config(cls, level: StrictnessLevel) -> "StrictnessConfig":
        """Получить конфигурацию для уровня строгости."""
        configs = {
            StrictnessLevel.LENIENT: cls(
                level=StrictnessLevel.LENIENT,
                min_example_length=30,
                require_localization=False,
                require_specific_details=False,
                penalize_extra_errors=False,
                temperature=0.5
            ),
            StrictnessLevel.STANDARD: cls(
                level=StrictnessLevel.STANDARD,
                min_example_length=50,
                require_localization=True,
                require_specific_details=True,
                penalize_extra_errors=False,
                temperature=0.3
            ),
            StrictnessLevel.STRICT: cls(
                level=StrictnessLevel.STRICT,
                min_example_length=70,
                require_localization=True,
                require_specific_details=True,
                penalize_extra_errors=True,  # Полное соответствие ФИПИ
                temperature=0.1
            )
        }
        return configs[level]

class Task19AIEvaluator(BaseAIEvaluator):
    """AI-оценщик для задания 19 с настраиваемой строгостью"""
    
    def __init__(self, strictness: StrictnessLevel = StrictnessLevel.STRICT):
        self.strictness = strictness
        requirements = TaskRequirements(
            task_number=19,
            task_name="Примеры социальных объектов",
            max_score=3,
            criteria=[
                {
                    "name": "Правильность примеров",
                    "max_score": 3,
                    "description": "По 1 баллу за каждый корректный пример"
                }
            ],
            description="Приведите три примера, иллюстрирующих..."
        )
        super().__init__(requirements)
    
    def get_system_prompt(self) -> str:
        """Системный промпт с учетом уровня строгости"""
        
        base_prompt = """Ты - эксперт ЕГЭ по обществознанию, проверяющий задание 19."""
        
        if self.strictness == StrictnessLevel.BASIC:
            return base_prompt + """
Проверяй основные требования: наличие трех примеров, их соответствие теме."""
            
        elif self.strictness == StrictnessLevel.STANDARD:
            return base_prompt + """
Проверяй: развернутость примеров, соответствие теме, базовую корректность.
Обращай внимание на очевидные фактические ошибки."""
            
        else:  # STRICT или EXPERT
            return base_prompt + """
СТРОЖАЙШИЕ ТРЕБОВАНИЯ:
1. Проверяй КАЖДЫЙ факт на соответствие российскому законодательству
2. НЕ ПРОПУСКАЙ правовые ошибки - они критичны!
3. Будь особенно внимателен к:
   - Трудовому праву (ЗАПРЕЩЕНЫ штрафы работников!)
   - Административным процедурам
   - Конституционным нормам
   - Экономическим реалиям РФ

АВТОМАТИЧЕСКИ НЕ ЗАСЧИТЫВАЙ примеры с:
- Штрафами работников работодателями (нарушение ст. 192 ТК РФ)
- Несуществующими в РФ органами власти
- Неверными правовыми процедурами
- Анахронизмами или устаревшими данными

Помни: штраф работника = грубейшая ошибка! В РФ допустимы только:
- Замечание
- Выговор  
- Увольнение по соответствующим основаниям

Лучше быть слишком строгим, чем пропустить ошибку!"""
    
    def _apply_scoring_rules(self, valid_count: int, invalid_count: int) -> int:
        """Применение правил подсчёта баллов в зависимости от строгости."""
        final_score = valid_count
        
        if self.config.penalize_extra_errors:
            # Строгое правило ФИПИ
            if invalid_count >= 2:
                final_score = 0
            elif invalid_count == 1 and final_score > 0:
                final_score -= 1
        
        return min(final_score, 3)  # Максимум 3 балла
    
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

        async with self.ai_service:
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
        
        async with self.ai_service:
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
