from __future__ import annotations
"""AI evaluator for task 19 using unified base class."""

import logging
import os
from typing import Dict, Any

from core.base_evaluator import BaseAIEvaluator, StrictnessLevel
from core.types import TaskRequirements, EvaluationCriteria, EvaluationResult

AI_EVALUATOR_AVAILABLE = bool(
    os.getenv("YANDEX_GPT_API_KEY") and os.getenv("YANDEX_GPT_FOLDER_ID")
)

__all__ = [
    "Task19AIEvaluator",
    "StrictnessLevel",
    "EvaluationResult",
    "AI_EVALUATOR_AVAILABLE",
]

logger = logging.getLogger(__name__)


class Task19AIEvaluator(BaseAIEvaluator):
    """AI evaluator for task 19 examples."""

    def __init__(self, strictness: StrictnessLevel = StrictnessLevel.STRICT):
        requirements = TaskRequirements(
            task_number=19,
            task_name="Примеры социальных объектов",
            max_score=3,
            criteria=[
                EvaluationCriteria(
                    "К1",
                    "Примеры",
                    3,
                    "По 1 баллу за каждый корректный пример",
                )
            ],
            description="Приведите три примера, иллюстрирующие обществоведческое положение",
        )
        super().__init__(requirements, strictness)

    def _build_evaluation_prompt(self, answer: str, task_data: Dict[str, Any]) -> str:
        task_text = task_data.get("task_text", "")
        return (
            f"Оцени ответ ученика на задание 19.\n\n"
            f"ЗАДАНИЕ: {task_text}\n\n"
            f"ОТВЕТ УЧЕНИКА:\n{answer}\n\n"
            "Проанализируй каждый пример и верни результаты в формате, указанном в системном промпте."
        )
