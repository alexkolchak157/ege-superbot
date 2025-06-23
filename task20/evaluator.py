from __future__ import annotations
"""AI evaluator for task 20 using unified base class."""

import logging
from typing import Dict, Any

from core.base_evaluator import BaseAIEvaluator, StrictnessLevel
from core.types import TaskRequirements, EvaluationCriteria

logger = logging.getLogger(__name__)


class Task20AIEvaluator(BaseAIEvaluator):
    """AI evaluator for task 20 statements."""

    def __init__(self, strictness: StrictnessLevel = StrictnessLevel.STRICT):
        requirements = TaskRequirements(
            task_number=20,
            task_name="Формулирование суждений",
            max_score=3,
            criteria=[
                EvaluationCriteria(
                    "К1",
                    "Суждения",
                    3,
                    "По 1 баллу за каждое корректное суждение",
                )
            ],
            description="Сформулируйте три суждения по заданной теме",
        )
        super().__init__(requirements, strictness)

    def _build_evaluation_prompt(self, answer: str, task_data: Dict[str, Any]) -> str:
        task_text = task_data.get("task_text", "")
        return (
            f"Оцени ответ ученика на задание 20.\n\n"
            f"ЗАДАНИЕ: {task_text}\n\n"
            f"ОТВЕТ УЧЕНИКА:\n{answer}\n\n"
            "Проанализируй каждое суждение и верни результаты в формате, указанном в системном промпте."
        )
