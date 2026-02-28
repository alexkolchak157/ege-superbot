"""AI-проверка для задания 17 ЕГЭ по обществознанию.

Задание 17 — анализ текстового фрагмента. Ученик должен найти и указать
конкретные элементы (понятия, функции, признаки и т.д.), прямо названные
в тексте. Максимальный балл — 2.

Критерии оценивания (ФИПИ):
  2 балла — правильно названы все требуемые элементы.
  1 балл — правильно названа часть элементов (на один меньше требуемого).
  0 баллов — назван один элемент или ответ неправильный.

Если в ответе наряду с верными приведены неверные элементы — каждый
неверный снижает оценку на 1 балл.
"""

import logging
from typing import Dict, List, Any

from core.types import TaskRequirements, EvaluationResult

logger = logging.getLogger(__name__)

try:
    from core.ai_service import create_ai_service, AIServiceConfig, AIModel
    AI_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI service not available: {e}")
    AI_AVAILABLE = False


class Task17AIEvaluator:
    """AI-проверщик для задания 17."""

    def __init__(self):
        self.requirements = TaskRequirements(
            task_number=17,
            task_name="Анализ текста: поиск информации",
            max_score=2,
            criteria=[],
            description=(
                "Прочитайте текст и найдите указанные в вопросе элементы "
                "(функции, признаки, понятия и т.д.)."
            ),
        )
        self.config = None
        if AI_AVAILABLE:
            try:
                self.config = AIServiceConfig.from_env()
                self.config.model = AIModel.LITE
                self.config.temperature = 0.15
                logger.info("Task17 AI evaluator configured")
            except Exception as e:
                logger.error(f"Failed to configure AI service for task17: {e}")

    # ------------------------------------------------------------------
    # system prompt
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        return """Ты — опытный эксперт ЕГЭ по обществознанию, проверяющий задание 17.

СУТЬ ЗАДАНИЯ 17:
Ученику дан текстовый фрагмент. Нужно найти и назвать определённое
количество элементов (функции, признаки, виды, черты и т.д.), которые
ПРЯМО упомянуты или следуют из текста.

КРИТЕРИИ ОЦЕНИВАНИЯ (максимум 2 балла):
• 2 балла — правильно названы ВСЕ требуемые элементы.
• 1 балл — правильно названы на один элемент меньше, чем требуется
  (например, 2 из 3).
• 0 баллов — назван лишь один элемент, или ответ неправильный.

ВАЖНЫЕ ПРАВИЛА:
1. Если ученик назвал БОЛЬШЕ элементов, чем требуется, и среди них есть
   НЕВЕРНЫЕ, каждый неверный элемент СНИЖАЕТ оценку на 1 балл.
2. Верным считается элемент, который по смыслу соответствует тексту,
   даже если формулировка отличается от авторской.
3. Не засчитываются элементы, представляющие собой общие фразы без
   конкретного содержания из текста.
4. Если один элемент ответа дублирует другой (по смыслу), засчитывается
   только один.

Отвечай ВСЕГДА в формате JSON."""

    # ------------------------------------------------------------------
    # evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        answer: str,
        task_data: Dict[str, Any],
        **kwargs,
    ) -> EvaluationResult:
        if not AI_AVAILABLE or not self.config:
            return self._basic_evaluation(answer, task_data)

        prompt = self._build_evaluation_prompt(answer, task_data)

        try:
            async with create_ai_service(self.config) as service:
                result = await service.get_json_completion(
                    prompt=prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.config.temperature,
                )
                if result:
                    return self._parse_response(result, task_data)
                logger.error("AI returned None for task17")
                return self._basic_evaluation(answer, task_data)
        except Exception as e:
            logger.error(f"Error in Task17 evaluation: {e}")
            return self._basic_evaluation(answer, task_data)

    # ------------------------------------------------------------------
    # prompt builder
    # ------------------------------------------------------------------

    def _build_evaluation_prompt(
        self,
        answer: str,
        task_data: Dict[str, Any],
    ) -> str:
        text = task_data.get("text", "")
        question = task_data.get("question", "")
        correct_answers = task_data.get("correct_answers", [])
        required_count = task_data.get("required_count", 3)
        scoring_notes = task_data.get("scoring_notes", "")

        correct_block = "\n".join(
            f"  {i}. {a}" for i, a in enumerate(correct_answers, 1)
        )

        return f"""Проверь ответ на задание 17 ЕГЭ.

ТЕКСТ:
{text}

ВОПРОС:
{question}

ПРАВИЛЬНЫЕ ОТВЕТЫ (эталон):
{correct_block}

ТРЕБУЕМОЕ КОЛИЧЕСТВО ЭЛЕМЕНТОВ: {required_count}

КРИТЕРИИ ОЦЕНКИ:
{scoring_notes}

ОТВЕТ УЧЕНИКА:
{answer}

ПОШАГОВЫЙ АЛГОРИТМ:
1. Определи, сколько элементов привёл ученик.
2. Для каждого элемента определи, соответствует ли он тексту и эталонным
   ответам (допускай перефразирование).
3. Посчитай количество верных элементов.
4. Если есть неверные элементы сверх требуемого — сними за каждый 1 балл.
5. Выстави итоговый балл: 0, 1 или 2.

Ответь в формате JSON:
```json
{{
    "score": число от 0 до 2,
    "valid_elements_count": количество верных элементов,
    "invalid_elements_count": количество неверных элементов,
    "elements_evaluation": [
        {{
            "element_num": 1,
            "user_text": "текст элемента ученика",
            "is_correct": true/false,
            "matched_answer": "какой эталонный ответ совпал" или null,
            "comment": "краткий комментарий"
        }}
    ],
    "feedback": "общий комментарий (2-3 предложения)",
    "suggestions": ["рекомендация 1", "рекомендация 2"]
}}
```

ВАЖНО: Верни ТОЛЬКО валидный JSON."""

    # ------------------------------------------------------------------
    # response parsing
    # ------------------------------------------------------------------

    def _parse_response(
        self,
        response: Dict[str, Any],
        task_data: Dict[str, Any],
    ) -> EvaluationResult:
        try:
            score = min(max(response.get("score", 0), 0), 2)
            valid_count = response.get("valid_elements_count", 0)
            invalid_count = response.get("invalid_elements_count", 0)

            feedback = response.get("feedback", "")
            feedback += (
                f"\n\n<b>Результат:</b> {valid_count} верных элементов"
                f" из {task_data.get('required_count', 3)} требуемых."
                f" Балл: {score}/2\n"
            )

            elements = response.get("elements_evaluation", [])
            if elements:
                feedback += "\n<b>Проверка элементов:</b>\n"
                for el in elements:
                    icon = "\u2705" if el.get("is_correct") else "\u274c"
                    comment = el.get("comment", "")
                    feedback += f"{icon} {el.get('user_text', '???')}"
                    if comment:
                        feedback += f" — {comment}"
                    feedback += "\n"

            if invalid_count:
                feedback += (
                    f"\n\u26a0\ufe0f Неверных элементов: {invalid_count}. "
                    "Каждый неверный элемент снижает оценку на 1 балл.\n"
                )

            return EvaluationResult(
                criteria_scores={"K1": score},
                total_score=score,
                max_score=2,
                feedback=feedback,
                detailed_feedback=response,
                suggestions=response.get("suggestions", []),
                factual_errors=[],
            )
        except Exception as e:
            logger.error(f"Error parsing task17 AI response: {e}")
            return self._basic_evaluation("", task_data)

    # ------------------------------------------------------------------
    # fallback
    # ------------------------------------------------------------------

    def _basic_evaluation(
        self,
        answer: str,
        task_data: Dict[str, Any],
    ) -> EvaluationResult:
        return EvaluationResult(
            criteria_scores={"K1": 0},
            total_score=0,
            max_score=2,
            feedback=(
                "AI-сервис временно недоступен. "
                "Обратитесь к преподавателю для проверки."
            ),
            detailed_feedback={},
            suggestions=[
                "Внимательно прочитайте текст перед ответом",
                "Ответ должен содержать конкретные элементы из текста",
            ],
            factual_errors=[],
        )
