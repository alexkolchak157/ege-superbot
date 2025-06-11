from core.ai_evaluator import BaseAIEvaluator, EvaluationResult, TaskRequirements
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class StrictnessLevel(Enum):
    LENIENT = "Мягкий"
    STANDARD = "Стандартный"
    STRICT = "Строгий"

class Task20AIEvaluator(BaseAIEvaluator):
    """AI-проверщик для задания 20 с настраиваемой строгостью."""
    
    def __init__(self, strictness: StrictnessLevel = StrictnessLevel.STANDARD):
        requirements = TaskRequirements(
            task_number=20,
            task_name="Формулирование суждений",
            max_score=3,
            criteria=[
                {
                    "name": "К1",
                    "max_score": 3,
                    "description": "Корректность суждений (по 1 баллу за каждое)"
                }
            ],
            description="Сформулируйте три суждения..."
        )
        super().__init__(requirements)
        self.strictness = strictness
    
    def get_system_prompt(self) -> str:
        # Промпт для YandexGPT
        pass
    
    async def evaluate(self, answer: str, topic: str, **kwargs) -> EvaluationResult:
        # Логика проверки через YandexGPT
        pass