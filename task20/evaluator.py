"""AI-проверка для задания 20 через YandexGPT."""

import logging
import os
from enum import Enum
from typing import Dict, List, Any, Optional

from core.ai_evaluator import BaseAIEvaluator, EvaluationResult, TaskRequirements
from core.ai_config import get_yandex_config, TaskType

logger = logging.getLogger(__name__)


class StrictnessLevel(Enum):
    """Уровни строгости проверки."""
    LENIENT = "Мягкий"
    STANDARD = "Стандартный" 
    STRICT = "Строгий"
    EXPERT = "Экспертный"


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
        """Системный промпт для YandexGPT."""
        base_prompt = """Ты - опытный эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 20.

ВАЖНЫЕ ПРАВИЛА ДЛЯ ЗАДАНИЯ 20:
1. В отличие от задания 19, здесь НЕ нужны конкретные примеры
2. Требуются суждения АБСТРАКТНОГО характера с элементами обобщения
3. Суждения должны быть более широкого объёма и менее конкретного содержания
4. Каждое суждение должно быть сформулировано как распространённое предложение
5. Суждения должны содержать элементы обобщения

КРИТЕРИИ ОЦЕНИВАНИЯ:
- 3 балла: приведены все требуемые суждения правильного типа
- 2 балла: приведено на одно суждение меньше требуемого
- 1 балл: приведено на два суждения меньше требуемого  
- 0 баллов: приведен только один аргумент ИЛИ рассуждения общего характера

ШТРАФЫ:
- Если наряду с требуемыми суждениями есть 2+ дополнительных с ошибками → 0 баллов
- Если есть 1 дополнительное с ошибкой → минус 1 балл от фактического

ЧТО СЧИТАЕТСЯ ПРАВИЛЬНЫМ СУЖДЕНИЕМ ДЛЯ ЗАДАНИЯ 20:
- Содержит элементы обобщения (способствует, приводит к, влияет на, обеспечивает, позволяет, создает, формирует, развивает, препятствует, ограничивает, снижает, повышает, улучшает, ухудшает, определяет, зависит от)
- НЕ содержит конкретных примеров (дат, имён, названий конкретных стран/организаций/компаний)
- Является распространённым предложением (не менее 5 слов)
- Соответствует требованию задания
- Содержит причинно-следственные связи

ЧТО НЕ ЗАСЧИТЫВАЕТСЯ:
- Конкретные примеры (например: "В 2020 году в России...", "Компания Apple...", "Во Франции...")
- Упоминание конкретных личностей, дат, событий
- Слишком конкретное содержание без обобщения
- Отдельные слова и словосочетания
- Общие рассуждения без чёткой аргументации
- Суждения, не соответствующие типу (например, негативный вместо позитивного)

ВАЖНО: Будь строг в оценке, но справедлив. Учитывай российский контекст."""

        # Модификация в зависимости от уровня строгости
        if self.strictness == StrictnessLevel.LENIENT:
            base_prompt += "\n\nУРОВЕНЬ: МЯГКИЙ - засчитывай суждения с небольшими недочётами."
        elif self.strictness == StrictnessLevel.STANDARD:
            base_prompt += "\n\nУРОВЕНЬ: СТАНДАРТНЫЙ - следуй критериям, но прощай мелкие недочёты."
        elif self.strictness == StrictnessLevel.STRICT:
            base_prompt += "\n\nУРОВЕНЬ: СТРОГИЙ - требуй полного соответствия критериям ФИПИ."
        elif self.strictness == StrictnessLevel.EXPERT:
            base_prompt += "\n\nУРОВЕНЬ: ЭКСПЕРТНЫЙ - максимальная строгость, как на реальном экзамене."
        
        return base_prompt
    
    async def evaluate(self, answer: str, topic: str, **kwargs) -> EvaluationResult:
        """Оценка ответа через YandexGPT."""
        task_text = kwargs.get('task_text', '')
        key_points = kwargs.get('key_points', [])
        
        # Формируем промпт для проверки
        evaluation_prompt = f"""Проверь ответ на задание 20 ЕГЭ.

ЗАДАНИЕ: {task_text}

ТЕМА: {topic}

ОТВЕТ УЧЕНИКА:
{answer}

ПОШАГОВЫЙ АЛГОРИТМ:
1. Определи, сколько всего суждений привёл ученик
2. Если больше 3 - проверь ВСЕ на ошибки (любая серьёзная ошибка = 0 баллов за всё)
3. Для каждого суждения оцени:
   - Абстрактность (нет конкретных примеров)
   - Наличие обобщения
   - Соответствие заданию
   - Логичность и корректность
   - Распространённость (не менее 5 слов)

УЧИТЫВАЙ:
- Суждения должны быть теоретическими
- НЕ должно быть конкретных дат, имён, названий
- Должны использоваться обобщающие конструкции

Ответь в формате JSON:
{{
    "score": число от 0 до 3,
    "valid_arguments_count": количество засчитанных суждений,
    "total_arguments": общее количество суждений в ответе,
    "penalty_applied": true/false,
    "penalty_reason": "причина штрафа" или null,
    "valid_arguments": [
        {{
            "number": номер суждения,
            "text": "текст суждения",
            "has_generalization": true/false,
            "comment": "почему засчитано"
        }}
    ],
    "invalid_arguments": [
        {{
            "number": номер суждения,
            "text": "текст суждения",
            "reason": "почему не засчитано",
            "is_concrete_example": true/false
        }}
    ],
    "feedback": "общий комментарий по проверке",
    "suggestions": ["рекомендация 1", "рекомендация 2"],
    "factual_errors": ["ошибка 1", "ошибка 2"] или []
}}"""

        try:
            # Получаем конфигурацию для YandexGPT
            config = get_yandex_config(TaskType.TASK_20)
            
            # Вызываем API
            response = await self._call_yandex_api(
                system_prompt=self.get_system_prompt(),
                user_prompt=evaluation_prompt,
                config=config
            )
            
            if response.get("error"):
                logger.error(f"YandexGPT error: {response.get('error')}")
                # Возвращаем базовую оценку
                return self._basic_evaluation(answer, topic)
            
            # Преобразуем ответ в EvaluationResult
            return self._parse_response(response, answer, topic)
            
        except Exception as e:
            logger.error(f"Error in Task20 evaluation: {e}")
            return self._basic_evaluation(answer, topic)
    
    def _basic_evaluation(self, answer: str, topic: str) -> EvaluationResult:
        """Базовая оценка без AI."""
        arguments = [arg.strip() for arg in answer.split('\n') if arg.strip()]
        score = min(len(arguments), 3) if len(arguments) <= 3 else 2
        
        return EvaluationResult(
            scores={"К1": score},
            total_score=score,
            max_score=3,
            feedback=f"Обнаружено суждений: {len(arguments)}",
            detailed_analysis={
                "arguments_count": len(arguments),
                "score": score
            },
            suggestions=[
                "Используйте больше обобщающих конструкций",
                "Избегайте конкретных примеров",
                "Формулируйте развёрнутые предложения"
            ],
            factual_errors=[]
        )
    
    def _parse_response(self, response: Dict[str, Any], answer: str, topic: str) -> EvaluationResult:
        """Парсинг ответа от YandexGPT."""
        try:
            score = response.get("score", 0)
            
            # Формируем детальную обратную связь
            feedback = response.get("feedback", "")
            
            if response.get("valid_arguments"):
                feedback += "\n\n✅ Засчитанные суждения:\n"
                for arg in response["valid_arguments"]:
                    feedback += f"{arg['number']}. {arg.get('comment', '')}\n"
            
            if response.get("invalid_arguments"):
                feedback += "\n\n❌ Не засчитанные суждения:\n"
                for arg in response["invalid_arguments"]:
                    feedback += f"{arg['number']}. {arg.get('reason', '')}\n"
            
            if response.get("penalty_applied"):
                feedback += f"\n\n⚠️ Применён штраф: {response.get('penalty_reason', '')}"
            
            return EvaluationResult(
                scores={"К1": score},
                total_score=score,
                max_score=3,
                feedback=feedback,
                detailed_analysis=response,
                suggestions=response.get("suggestions", []),
                factual_errors=response.get("factual_errors", [])
            )
            
        except Exception as e:
            logger.error(f"Error parsing YandexGPT response: {e}")
            return self._basic_evaluation(answer, topic)
