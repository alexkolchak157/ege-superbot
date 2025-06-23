from __future__ import annotations
"""AI evaluator for task 25 using unified base class."""

import logging
from typing import Dict, Any

from core.base_evaluator import BaseAIEvaluator, StrictnessLevel
from core.types import TaskRequirements, EvaluationCriteria

logger = logging.getLogger(__name__)


class Task25AIEvaluator(BaseAIEvaluator):
    """AI evaluator for task 25 extended answers."""

    def __init__(self, strictness: StrictnessLevel = StrictnessLevel.STRICT):
        requirements = TaskRequirements(
            task_number=25,
            task_name="Развёрнутый ответ",
            max_score=6,
            criteria=[
                EvaluationCriteria("К1", "Обоснование", 2, "Корректное обоснование с теорией"),
                EvaluationCriteria("К2", "Ответ на вопрос", 1, "Дан правильный ответ"),
                EvaluationCriteria("К3", "Примеры", 3, "Три развёрнутых примера"),
            ],
            description="Обоснуйте, ответьте на вопрос и приведите три примера",
        )
        super().__init__(requirements, strictness)

    def _build_evaluation_prompt(self, answer: str, task_data: Dict[str, Any]) -> str:
        task_text = task_data.get("task_text", "")
        return (
            f"Оцени ответ ученика на задание 25.\n\n"
            f"ЗАДАНИЕ: {task_text}\n\n"
            f"ОТВЕТ УЧЕНИКА:\n{answer}\n\n"
            "Проанализируй обоснование, ответ и примеры. Верни результаты в формате, указанном в системном промпте."
        )
