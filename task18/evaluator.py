"""AI-проверка для задания 18 ЕГЭ по обществознанию.

Задание 18 — объяснение понятия из текста и/или приведение примеров
(признаков, функций и т.д.) с опорой на обществоведческие знания.
Максимальный балл — 2.

Критерии оценивания (ФИПИ):
  2 балла — правильно названы все требуемые элементы (например, три
            признака / три примера / определение + два предложения).
  1 балл — правильно названа часть элементов (на один меньше).
  0 баллов — назван один элемент или ответ неправильный.

Если в ответе наряду с верными приведены неверные — каждый неверный
снижает оценку на 1 балл.
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


class Task18AIEvaluator:
    """AI-проверщик для задания 18."""

    def __init__(self):
        self.requirements = TaskRequirements(
            task_number=18,
            task_name="Анализ текста: объяснение понятия",
            max_score=2,
            criteria=[],
            description=(
                "Используя обществоведческие знания, объясните понятие "
                "из текста и/или приведите примеры, признаки, функции."
            ),
        )
        self.config = None
        if AI_AVAILABLE:
            try:
                self.config = AIServiceConfig.from_env()
                self.config.model = AIModel.LITE
                self.config.temperature = 0.2
                logger.info("Task18 AI evaluator configured")
            except Exception as e:
                logger.error(f"Failed to configure AI for task18: {e}")

    # ------------------------------------------------------------------
    # system prompt
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        return """Ты — опытный эксперт ЕГЭ по обществознанию, проверяющий задание 18.

СУТЬ ЗАДАНИЯ 18:
Ученику дан тот же текстовый фрагмент, что и в задании 17. Задание 18
требует использования обществоведческих знаний: нужно объяснить понятие
и/или привести примеры (признаки, функции), опираясь НЕ ТОЛЬКО на текст,
но и на собственные знания по курсу обществознания.

КРИТЕРИИ ОЦЕНИВАНИЯ (максимум 2 балла):
• 2 балла — правильно названы все требуемые элементы.
• 1 балл — правильно названы на один элемент меньше, чем требуется.
• 0 баллов — назван лишь один элемент, или ответ неправильный.

ВАЖНЫЕ ПРАВИЛА:
1. Если ученик назвал БОЛЬШЕ элементов, чем требуется, и среди них есть
   НЕВЕРНЫЕ, каждый неверный элемент СНИЖАЕТ оценку на 1 балл.
2. Допускается перефразирование, если суть верна.
3. Ответ должен опираться на обществоведческие знания, а не только
   на текст. Общие бессодержательные фразы не засчитываются.
4. Если один элемент дублирует другой по смыслу — засчитывается один.
5. Примеры должны быть конкретными и содержательными.

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
                logger.error("AI returned None for task18")
                return self._basic_evaluation(answer, task_data)
        except Exception as e:
            logger.error(f"Error in Task18 evaluation: {e}")
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
        concept = task_data.get("concept", "")
        correct_answer = task_data.get("correct_answer", {})
        required_count = correct_answer.get("required_count", 3)
        elements = correct_answer.get("elements", [])
        scoring_notes = task_data.get("scoring_notes", "")

        correct_block = "\n".join(
            f"  {i}. {e}" for i, e in enumerate(elements, 1)
        )

        return f"""Проверь ответ на задание 18 ЕГЭ.

ТЕКСТ (тот же, что и в задании 17):
{text}

ВОПРОС:
{question}

КЛЮЧЕВОЕ ПОНЯТИЕ: {concept}

ПРАВИЛЬНЫЕ ОТВЕТЫ (эталон):
{correct_block}

ТРЕБУЕМОЕ КОЛИЧЕСТВО ЭЛЕМЕНТОВ: {required_count}

КРИТЕРИИ ОЦЕНКИ:
{scoring_notes}

ОТВЕТ УЧЕНИКА:
{answer}

ПОШАГОВЫЙ АЛГОРИТМ:
1. Определи, сколько элементов привёл ученик.
2. Оцени каждый элемент: соответствует ли он обществоведческим знаниям
   и эталонным ответам (допустимо перефразирование).
3. Отдельно оцени конкретность и содержательность примеров/пояснений.
4. Посчитай верные и неверные элементы.
5. Если есть неверные элементы сверх требуемого — сними по 1 баллу.
6. Выстави итоговый балл: 0, 1 или 2.

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
            "is_specific": true/false,
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
            concept = task_data.get("concept", "")
            req = task_data.get("correct_answer", {}).get("required_count", 3)

            feedback = response.get("feedback", "")
            feedback += (
                f"\n\n<b>Результат:</b> {valid_count} верных элементов"
                f" из {req} требуемых. Балл: {score}/2\n"
            )

            elements = response.get("elements_evaluation", [])
            if elements:
                feedback += "\n<b>Проверка элементов:</b>\n"
                for el in elements:
                    icon = "\u2705" if el.get("is_correct") else "\u274c"
                    specificity = ""
                    if el.get("is_correct") and not el.get("is_specific", True):
                        specificity = " (недостаточно конкретно)"
                    comment = el.get("comment", "")
                    feedback += f"{icon} {el.get('user_text', '???')}{specificity}"
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
            logger.error(f"Error parsing task18 AI response: {e}")
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
                "Опирайтесь на обществоведческие знания, а не только на текст",
                "Приводите конкретные примеры, а не общие фразы",
            ],
            factual_errors=[],
        )
