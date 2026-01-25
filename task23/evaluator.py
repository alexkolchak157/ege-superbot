"""
AI-проверка для задания 23 (Конституция РФ).

Поддерживает два типа моделей вопросов:
- Model Type 1: Одна характеристика, три подтверждения
- Model Type 2: Три характеристики, по одному подтверждению каждой
"""

import logging
import json
import re
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass

from core.types import TaskRequirements, EvaluationResult

logger = logging.getLogger(__name__)

# Безопасный импорт AI сервисов
try:
    from core.ai_evaluator import BaseAIEvaluator
    from core.ai_service import YandexGPTService, YandexGPTConfig, YandexGPTModel
    AI_EVALUATOR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI evaluator components not available: {e}")
    AI_EVALUATOR_AVAILABLE = False

    class BaseAIEvaluator:
        def __init__(self, requirements: TaskRequirements):
            self.requirements = requirements

    class YandexGPTService:
        pass

    class YandexGPTConfig:
        pass

    class YandexGPTModel:
        LITE = "yandexgpt-lite"
        PRO = "yandexgpt"


@dataclass
class AnswerEvaluation:
    """Результат оценки одного ответа."""
    is_correct: bool
    score: float
    feedback: str
    matched_model_answer: Optional[str] = None


class Task23Evaluator(BaseAIEvaluator if AI_EVALUATOR_AVAILABLE else object):
    """AI-проверщик для задания 23 (Конституция РФ)."""

    def __init__(self):
        if AI_EVALUATOR_AVAILABLE:
            requirements = TaskRequirements(
                task_number=23,
                task_name="Конституция Российской Федерации",
                max_score=3,
                criteria=[
                    {
                        "name": "К1",
                        "max_score": 3,
                        "description": "Правильность подтверждений (по 1 баллу за каждое)"
                    }
                ],
                description="Сформулируйте подтверждения характеристик на основе Конституции РФ"
            )
            super().__init__(requirements)
        else:
            self.requirements = TaskRequirements(
                task_number=23,
                task_name="Конституция Российской Федерации",
                max_score=3,
                criteria=[{"name": "К1", "max_score": 3, "description": "Правильность подтверждений"}],
                description="Сформулируйте подтверждения характеристик на основе Конституции РФ"
            )

        self.ai_service = None
        self.config = None

        if AI_EVALUATOR_AVAILABLE:
            try:
                config = YandexGPTConfig.from_env()
                config.model = YandexGPTModel.PRO
                config.temperature = 0.2
                self.config = config
                logger.info("Task23 AI evaluator configured")
            except Exception as e:
                logger.error(f"Failed to configure AI service: {e}")
                self.config = None

    def get_system_prompt(self) -> str:
        """Системный промпт для YandexGPT."""
        return """Ты - опытный эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 23 (Конституция РФ).

ВАЖНЫЕ ПРАВИЛА ДЛЯ ЗАДАНИЯ 23:

1. Задание проверяет знание положений Конституции Российской Федерации.
2. Максимальный балл - 3 (по 1 баллу за каждое правильное подтверждение).
3. Подтверждение должно быть сформулировано как распространённое предложение с опорой на конкретное положение Конституции РФ.
4. НЕ требуется указание номеров статей Конституции.
5. НЕ требуется дословное воспроизведение статей.

КРИТЕРИИ ОЦЕНИВАНИЯ:
- 3 балла: даны три правильных подтверждения
- 2 балла: даны два правильных подтверждения
- 1 балл: дано одно правильное подтверждение
- 0 баллов: ответ неправильный или приведены рассуждения общего характера

ПРИ ОЦЕНКЕ ПОДТВЕРЖДЕНИЙ:
1. Проверяй соответствие положениям Конституции РФ
2. Учитывай, что формулировка может отличаться от эталонной
3. Главное - передача смысла конституционного положения
4. Принимай синонимичные и перефразированные ответы
5. Не засчитывай общие рассуждения без конкретики
6. Не засчитывай фактически неверные утверждения

При проверке:
- Будь строг, но справедлив
- Давай конкретные комментарии к каждому подтверждению
- Объясняй, почему ответ засчитан или не засчитан
- Указывай, какое положение Конституции соответствует ответу"""

    async def evaluate(
        self,
        user_answer: str,
        question_data: Dict[str, Any],
        **kwargs
    ) -> EvaluationResult:
        """
        Оценка ответа пользователя.

        Args:
            user_answer: Ответ пользователя (текст)
            question_data: Данные вопроса из JSON

        Returns:
            EvaluationResult с оценкой и обратной связью
        """
        model_type = question_data.get('model_type', 1)

        if model_type == 1:
            return await self._evaluate_model1(user_answer, question_data)
        elif model_type == 2:
            return await self._evaluate_model2(user_answer, question_data)
        else:
            logger.error(f"Unknown model_type: {model_type}")
            return self._create_error_result("Неизвестный тип вопроса")

    async def _evaluate_model1(
        self,
        user_answer: str,
        question_data: Dict[str, Any]
    ) -> EvaluationResult:
        """
        Оценка ответа для Model Type 1.

        Дана ОДНА характеристика, нужно дать 3 подтверждения.
        Каждое правильное подтверждение = 1 балл.
        """
        characteristic = question_data.get('characteristics', [''])[0]
        model_answers = question_data.get('model_answers', [])

        # Парсим ответы пользователя
        user_answers = self._parse_user_answers(user_answer)

        if not AI_EVALUATOR_AVAILABLE or not self.config:
            return self._basic_evaluation_model1(user_answers, model_answers, characteristic)

        # Формируем промпт для AI оценки
        prompt = self._build_model1_prompt(
            characteristic, model_answers, user_answers, user_answer
        )

        try:
            async with YandexGPTService(self.config) as service:
                result = await service.get_json_completion(
                    prompt=prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.config.temperature
                )

                if result:
                    return self._parse_model1_response(result, model_answers)
                else:
                    return self._basic_evaluation_model1(user_answers, model_answers, characteristic)

        except Exception as e:
            logger.error(f"Error in Task23 Model1 evaluation: {e}")
            return self._basic_evaluation_model1(user_answers, model_answers, characteristic)

    async def _evaluate_model2(
        self,
        user_answer: str,
        question_data: Dict[str, Any]
    ) -> EvaluationResult:
        """
        Оценка ответа для Model Type 2.

        Даны ТРИ характеристики, нужно дать по одному подтверждению каждой.
        Каждое правильное подтверждение = 1 балл.
        """
        characteristics = question_data.get('characteristics', [])
        model_answers = question_data.get('model_answers', {})

        # Парсим ответы пользователя
        user_answers = self._parse_user_answers(user_answer)

        if not AI_EVALUATOR_AVAILABLE or not self.config:
            return self._basic_evaluation_model2(
                user_answers, characteristics, model_answers
            )

        # Формируем промпт для AI оценки
        prompt = self._build_model2_prompt(
            characteristics, model_answers, user_answers, user_answer
        )

        try:
            async with YandexGPTService(self.config) as service:
                result = await service.get_json_completion(
                    prompt=prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.config.temperature
                )

                if result:
                    return self._parse_model2_response(result, characteristics)
                else:
                    return self._basic_evaluation_model2(
                        user_answers, characteristics, model_answers
                    )

        except Exception as e:
            logger.error(f"Error in Task23 Model2 evaluation: {e}")
            return self._basic_evaluation_model2(
                user_answers, characteristics, model_answers
            )

    def _parse_user_answers(self, answer: str) -> List[str]:
        """Парсинг ответов пользователя из текста."""
        answers = []

        # Пробуем найти нумерованные ответы
        pattern = r'^\s*(\d+)[.)]\s*(.+?)(?=^\s*\d+[.)]|\Z)'
        matches = re.finditer(pattern, answer, re.MULTILINE | re.DOTALL)

        for match in matches:
            answer_text = match.group(2).strip()
            if answer_text:
                answers.append(answer_text)

        # Если не нашли нумерацию, разделяем по переносам строк
        if len(answers) == 0:
            lines = [line.strip() for line in answer.split('\n') if line.strip()]
            # Убираем возможные маркеры в начале строк
            for line in lines:
                clean_line = re.sub(r'^[-–—•]\s*', '', line).strip()
                if clean_line:
                    answers.append(clean_line)

        return answers[:3]  # Максимум 3 ответа

    def _build_model1_prompt(
        self,
        characteristic: str,
        model_answers: List[str],
        user_answers: List[str],
        full_answer: str
    ) -> str:
        """Формирование промпта для Model Type 1."""
        model_answers_text = "\n".join([f"  {i}. {ans}" for i, ans in enumerate(model_answers, 1)])
        user_answers_text = "\n".join([f"  {i}. {ans}" for i, ans in enumerate(user_answers, 1)])

        return f"""Проверь ответ на задание 23 ЕГЭ (Конституция РФ).

ХАРАКТЕРИСТИКА:
{characteristic}

ЭТАЛОННЫЕ ПОДТВЕРЖДЕНИЯ (любые 3 из них правильные):
{model_answers_text}

ОТВЕТ УЧЕНИКА (полный текст):
{full_answer}

РАСПОЗНАННЫЕ ПОДТВЕРЖДЕНИЯ:
{user_answers_text}

ЗАДАЧА:
1. Проверь каждое подтверждение ученика
2. Сравни с эталонными ответами (допускается перефразирование)
3. Засчитай подтверждения, которые:
   - Соответствуют положениям Конституции РФ
   - Раскрывают данную характеристику
   - Содержат конкретное утверждение (не общие слова)
4. Выстави балл: количество правильных подтверждений (0-3)

Ответь в формате JSON:
```json
{{
    "score": число от 0 до 3,
    "correct_count": количество правильных подтверждений,
    "answers_evaluation": [
        {{
            "number": номер подтверждения,
            "user_answer": "ответ ученика",
            "is_correct": true/false,
            "matched_model": "какому эталонному ответу соответствует" или null,
            "comment": "почему засчитано/не засчитано"
        }}
    ],
    "feedback": "общий комментарий (2-3 предложения)",
    "suggestions": ["рекомендация по улучшению"]
}}
```

ВАЖНО: Верни ТОЛЬКО валидный JSON."""

    def _build_model2_prompt(
        self,
        characteristics: List[str],
        model_answers: Dict[str, List[str]],
        user_answers: List[str],
        full_answer: str
    ) -> str:
        """Формирование промпта для Model Type 2."""
        chars_with_answers = ""
        for i, char in enumerate(characteristics, 1):
            char_answers = model_answers.get(char, [])
            answers_text = "; ".join(char_answers) if char_answers else "нет эталона"
            chars_with_answers += f"\n{i}. Характеристика: {char}\n   Эталонные ответы: {answers_text}\n"

        user_answers_text = "\n".join([f"  {i}. {ans}" for i, ans in enumerate(user_answers, 1)])

        return f"""Проверь ответ на задание 23 ЕГЭ (Конституция РФ) - тип с тремя характеристиками.

ХАРАКТЕРИСТИКИ И ЭТАЛОННЫЕ ОТВЕТЫ:
{chars_with_answers}

ОТВЕТ УЧЕНИКА (полный текст):
{full_answer}

РАСПОЗНАННЫЕ ПОДТВЕРЖДЕНИЯ (по порядку характеристик):
{user_answers_text}

ЗАДАЧА:
1. Соотнеси каждое подтверждение ученика с соответствующей характеристикой
2. Проверь, раскрывает ли подтверждение данную характеристику
3. Сравни с эталонными ответами (допускается перефразирование)
4. Засчитай подтверждения, которые:
   - Соответствуют положениям Конституции РФ
   - Раскрывают ИМЕННО ту характеристику, к которой относятся
   - Содержат конкретное утверждение
5. Выстави балл: количество правильных подтверждений (0-3)

Ответь в формате JSON:
```json
{{
    "score": число от 0 до 3,
    "correct_count": количество правильных подтверждений,
    "answers_evaluation": [
        {{
            "characteristic_number": номер характеристики (1-3),
            "characteristic": "текст характеристики",
            "user_answer": "ответ ученика",
            "is_correct": true/false,
            "matched_model": "какому эталонному ответу соответствует" или null,
            "comment": "почему засчитано/не засчитано"
        }}
    ],
    "feedback": "общий комментарий (2-3 предложения)",
    "suggestions": ["рекомендация по улучшению"]
}}
```

ВАЖНО: Верни ТОЛЬКО валидный JSON."""

    def _parse_model1_response(
        self,
        response: Dict[str, Any],
        model_answers: List[str]
    ) -> EvaluationResult:
        """Парсинг ответа AI для Model Type 1."""
        try:
            score = min(response.get("score", 0), 3)
            correct_count = response.get("correct_count", 0)

            feedback = f"<b>Результат:</b> {correct_count} из 3 подтверждений засчитано.\n"
            feedback += f"<b>Балл:</b> {score}/3\n\n"

            # Добавляем оценку каждого подтверждения
            if response.get("answers_evaluation"):
                feedback += "<b>Проверка подтверждений:</b>\n"
                for eval_item in response["answers_evaluation"]:
                    num = eval_item.get("number", "?")
                    is_correct = eval_item.get("is_correct", False)
                    comment = eval_item.get("comment", "")

                    icon = "✅" if is_correct else "❌"
                    feedback += f"{icon} <b>Подтверждение {num}:</b> {comment}\n"

                    if is_correct and eval_item.get("matched_model"):
                        feedback += f"   <i>Соответствует: {eval_item['matched_model'][:100]}...</i>\n"

            # Общий комментарий
            if response.get("feedback"):
                feedback += f"\n<b>Комментарий:</b> {response['feedback']}"

            return EvaluationResult(
                criteria_scores={"К1": score},
                total_score=score,
                max_score=3,
                feedback=feedback,
                detailed_feedback=response,
                suggestions=response.get("suggestions", []),
                factual_errors=[]
            )

        except Exception as e:
            logger.error(f"Error parsing Model1 response: {e}")
            return self._create_error_result("Ошибка обработки ответа AI")

    def _parse_model2_response(
        self,
        response: Dict[str, Any],
        characteristics: List[str]
    ) -> EvaluationResult:
        """Парсинг ответа AI для Model Type 2."""
        try:
            score = min(response.get("score", 0), 3)
            correct_count = response.get("correct_count", 0)

            feedback = f"<b>Результат:</b> {correct_count} из 3 подтверждений засчитано.\n"
            feedback += f"<b>Балл:</b> {score}/3\n\n"

            # Добавляем оценку каждого подтверждения
            if response.get("answers_evaluation"):
                feedback += "<b>Проверка по характеристикам:</b>\n"
                for eval_item in response["answers_evaluation"]:
                    char_num = eval_item.get("characteristic_number", "?")
                    char_text = eval_item.get("characteristic", "")[:50]
                    is_correct = eval_item.get("is_correct", False)
                    comment = eval_item.get("comment", "")

                    icon = "✅" if is_correct else "❌"
                    feedback += f"\n{icon} <b>{char_num}. {char_text}...</b>\n"
                    feedback += f"   {comment}\n"

            # Общий комментарий
            if response.get("feedback"):
                feedback += f"\n<b>Комментарий:</b> {response['feedback']}"

            return EvaluationResult(
                criteria_scores={"К1": score},
                total_score=score,
                max_score=3,
                feedback=feedback,
                detailed_feedback=response,
                suggestions=response.get("suggestions", []),
                factual_errors=[]
            )

        except Exception as e:
            logger.error(f"Error parsing Model2 response: {e}")
            return self._create_error_result("Ошибка обработки ответа AI")

    def _basic_evaluation_model1(
        self,
        user_answers: List[str],
        model_answers: List[str],
        characteristic: str
    ) -> EvaluationResult:
        """Базовая оценка Model Type 1 без AI."""
        score = min(len(user_answers), 3)

        feedback = f"<b>Обнаружено подтверждений:</b> {len(user_answers)}\n"
        feedback += f"<b>Базовый балл:</b> {score}/3\n\n"
        feedback += "<i>Для точной проверки требуется AI-сервис.</i>\n\n"
        feedback += "<b>Эталонные ответы:</b>\n"
        for i, ans in enumerate(model_answers[:3], 1):
            feedback += f"{i}. {ans}\n"

        return EvaluationResult(
            criteria_scores={"К1": score},
            total_score=score,
            max_score=3,
            feedback=feedback,
            detailed_feedback={
                "answers_count": len(user_answers),
                "note": "Базовая проверка без AI",
                "user_answers": user_answers
            },
            suggestions=[
                "Убедитесь, что каждое подтверждение опирается на Конституцию РФ",
                "Формулируйте ответы развёрнутыми предложениями"
            ],
            factual_errors=[]
        )

    def _basic_evaluation_model2(
        self,
        user_answers: List[str],
        characteristics: List[str],
        model_answers: Dict[str, List[str]]
    ) -> EvaluationResult:
        """Базовая оценка Model Type 2 без AI."""
        score = min(len(user_answers), 3)

        feedback = f"<b>Обнаружено подтверждений:</b> {len(user_answers)}\n"
        feedback += f"<b>Базовый балл:</b> {score}/3\n\n"
        feedback += "<i>Для точной проверки требуется AI-сервис.</i>\n\n"
        feedback += "<b>Характеристики и эталонные ответы:</b>\n"

        for i, char in enumerate(characteristics, 1):
            char_answers = model_answers.get(char, [])
            if char_answers:
                example = char_answers[0][:100] + "..." if len(char_answers[0]) > 100 else char_answers[0]
                feedback += f"\n{i}. <b>{char[:50]}...</b>\n   <i>{example}</i>\n"

        return EvaluationResult(
            criteria_scores={"К1": score},
            total_score=score,
            max_score=3,
            feedback=feedback,
            detailed_feedback={
                "answers_count": len(user_answers),
                "note": "Базовая проверка без AI",
                "user_answers": user_answers
            },
            suggestions=[
                "Давайте подтверждения в том же порядке, что и характеристики",
                "Каждое подтверждение должно раскрывать конкретную характеристику"
            ],
            factual_errors=[]
        )

    def _create_error_result(self, message: str) -> EvaluationResult:
        """Создание результата с ошибкой."""
        return EvaluationResult(
            criteria_scores={"К1": 0},
            total_score=0,
            max_score=3,
            feedback=f"❌ {message}",
            detailed_feedback={"error": message},
            suggestions=[],
            factual_errors=[]
        )

    def get_model_answers_text(self, question_data: Dict[str, Any]) -> str:
        """Получить текст эталонных ответов для отображения."""
        model_type = question_data.get('model_type', 1)

        if model_type == 1:
            answers = question_data.get('model_answers', [])
            text = "<b>Эталонные подтверждения (любые 3 из них):</b>\n\n"
            for i, ans in enumerate(answers, 1):
                text += f"{i}. {ans}\n\n"
            return text
        else:
            characteristics = question_data.get('characteristics', [])
            model_answers = question_data.get('model_answers', {})

            text = "<b>Эталонные подтверждения:</b>\n\n"
            for i, char in enumerate(characteristics, 1):
                text += f"<b>{i}. {char}</b>\n"
                char_answers = model_answers.get(char, [])
                if char_answers:
                    for ans in char_answers:
                        text += f"   • {ans}\n"
                text += "\n"
            return text
