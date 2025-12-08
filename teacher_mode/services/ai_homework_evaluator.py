"""
Сервис для AI проверки ответов учеников в домашних заданиях.
"""

import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)


async def evaluate_homework_answer(
    task_module: str,
    question_data: Dict,
    user_answer: str,
    user_id: int
) -> Tuple[bool, str]:
    """
    Проверяет ответ ученика через AI evaluator соответствующего модуля.

    Args:
        task_module: Название модуля ('task19', 'task20', 'task24', 'task25', 'test_part', 'custom')
        question_data: Данные вопроса из question_loader или custom_questions
        user_answer: Ответ ученика
        user_id: ID ученика

    Returns:
        Tuple[bool, str]: (is_correct, feedback_text)
        - is_correct: True если ответ принят (набрано > 50% баллов)
        - feedback_text: Текст обратной связи для ученика
    """
    try:
        # Для кастомных вопросов используем указанный тип
        if task_module == 'custom':
            custom_type = question_data.get('type', 'test_part')
            return await _evaluate_custom_question(custom_type, question_data, user_answer, user_id)

        if task_module == 'test_part':
            return await _evaluate_test_part(question_data, user_answer, user_id)
        elif task_module == 'task19':
            return await _evaluate_task19(question_data, user_answer, user_id)
        elif task_module == 'task20':
            return await _evaluate_task20(question_data, user_answer, user_id)
        elif task_module == 'task24':
            return await _evaluate_task24(question_data, user_answer, user_id)
        elif task_module == 'task25':
            return await _evaluate_task25(question_data, user_answer, user_id)
        else:
            logger.warning(f"Unknown task module: {task_module}")
            return False, f"❌ Неизвестный тип задания: {task_module}"

    except Exception as e:
        logger.error(f"Error evaluating answer for {task_module}: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке ответа: {str(e)}"


async def _evaluate_task19(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task19 (примеры с обществознанием)"""
    try:
        from task19.evaluator import Task19AIEvaluator, StrictnessLevel
        from core.types import EvaluationResult

        # Создаем evaluator
        evaluator = Task19AIEvaluator(strictness=StrictnessLevel.STANDARD)

        # Вызываем проверку
        topic = question_data.get('title', 'Неизвестная тема')
        task_text = question_data.get('task_text', '')

        result: EvaluationResult = await evaluator.evaluate(
            answer=user_answer,
            topic=topic,
            task_text=task_text
        )

        # Формируем обратную связь
        is_correct = result.total_score >= (result.max_score / 2)  # >= 50% баллов

        feedback = f"📊 <b>Результат проверки:</b>\n\n"
        feedback += f"Баллы: {result.total_score}/{result.max_score}\n\n"
        feedback += f"<b>Обратная связь:</b>\n{result.feedback}"

        if result.warnings:
            feedback += f"\n\n⚠️ <b>Предупреждения:</b>\n"
            feedback += "\n".join(f"• {w}" for w in result.warnings)

        if result.suggestions:
            feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
            feedback += "\n".join(f"• {s}" for s in result.suggestions)

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task19 evaluator not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task19 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task20(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task20 (логические задачи)"""
    try:
        from task20.evaluator import Task20AIEvaluator
        from core.types import EvaluationResult

        # Создаем evaluator
        evaluator = Task20AIEvaluator()

        # Вызываем проверку
        topic = question_data.get('title', 'Неизвестная тема')
        task_text = question_data.get('task_text', '')

        result: EvaluationResult = await evaluator.evaluate(
            answer=user_answer,
            topic=topic,
            task_text=task_text
        )

        # Формируем обратную связь
        is_correct = result.total_score >= (result.max_score / 2)

        feedback = f"📊 <b>Результат проверки:</b>\n\n"
        feedback += f"Баллы: {result.total_score}/{result.max_score}\n\n"
        feedback += f"<b>Обратная связь:</b>\n{result.feedback}"

        if result.warnings:
            feedback += f"\n\n⚠️ <b>Предупреждения:</b>\n"
            feedback += "\n".join(f"• {w}" for w in result.warnings)

        if result.suggestions:
            feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
            feedback += "\n".join(f"• {s}" for s in result.suggestions)

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task20 evaluator not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task20 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task24(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task24 (развернутый план)"""
    try:
        from task24.checker import evaluate_plan_with_ai
        from task24.handlers import bot_data  # Глобальный объект с данными планов

        # Получаем данные эталонного плана
        topic_name = question_data.get('title', 'Неизвестная тема')

        # Формируем ideal_plan_data из question_data
        ideal_plan_data = {
            'full_plan': question_data.get('full_plan', []),
            'points_data': question_data.get('points_data', []),
            'min_points': question_data.get('min_points', 3),
            'min_detailed_points': question_data.get('min_detailed_points', 2),
            'min_subpoints': question_data.get('min_subpoints', 3)
        }

        # Вызываем проверку
        feedback_text = await evaluate_plan_with_ai(
            user_plan_text=user_answer,
            ideal_plan_data=ideal_plan_data,
            bot_data=bot_data,
            topic_name=topic_name,
            use_ai=True,
            user_id=user_id
        )

        # Извлекаем баллы из feedback
        import re
        k1_match = re.search(r'К1.*?(\d+)/3', feedback_text)
        k2_match = re.search(r'К2.*?(\d+)/1', feedback_text)
        k1 = int(k1_match.group(1)) if k1_match else 0
        k2 = int(k2_match.group(1)) if k2_match else 0

        total_score = k1 + k2
        max_score = 4

        is_correct = total_score >= (max_score / 2)  # >= 2 баллов из 4

        feedback = f"📊 <b>Результат проверки плана:</b>\n\n"
        feedback += feedback_text

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task24 checker not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task24 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task25(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task25 (эссе)"""
    try:
        from task25.evaluator import Task25AIEvaluator
        from core.types import EvaluationResult

        # Создаем evaluator
        evaluator = Task25AIEvaluator()

        # Вызываем проверку
        result: EvaluationResult = await evaluator.evaluate(
            answer=user_answer,
            topic=question_data,  # Передаем весь question_data как topic
            user_id=user_id
        )

        # Формируем обратную связь
        is_correct = result.total_score >= (result.max_score / 2)

        feedback = f"📊 <b>Результат проверки:</b>\n\n"
        feedback += f"Баллы: {result.total_score}/{result.max_score}\n\n"

        # Добавляем детали по критериям
        if result.criteria_scores:
            feedback += "<b>По критериям:</b>\n"
            for criterion, score in result.criteria_scores.items():
                feedback += f"• {criterion}: {score}\n"
            feedback += "\n"

        feedback += f"<b>Обратная связь:</b>\n{result.feedback}"

        if result.warnings:
            feedback += f"\n\n⚠️ <b>Предупреждения:</b>\n"
            feedback += "\n".join(f"• {w}" for w in result.warnings)

        if result.suggestions:
            feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
            feedback += "\n".join(f"• {s}" for s in result.suggestions)

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task25 evaluator not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task25 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_test_part(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для тестовой части (короткий ответ)"""
    try:
        # Для тестовой части используем точное сравнение
        correct_answer = question_data.get('answer', question_data.get('correct_answer', ''))

        # Нормализуем ответы (убираем пробелы, приводим к нижнему регистру)
        user_answer_normalized = user_answer.strip().lower().replace(' ', '')
        correct_answer_normalized = str(correct_answer).strip().lower().replace(' ', '')

        is_correct = user_answer_normalized == correct_answer_normalized

        if is_correct:
            feedback = (
                "✅ <b>Ответ правильный!</b>\n\n"
                f"Ваш ответ: <code>{user_answer}</code>\n"
                f"Правильный ответ: <code>{correct_answer}</code>"
            )
        else:
            feedback = (
                "❌ <b>Ответ неправильный</b>\n\n"
                f"Ваш ответ: <code>{user_answer}</code>\n"
                f"Правильный ответ: <code>{correct_answer}</code>"
            )

        return is_correct, feedback

    except Exception as e:
        logger.error(f"Error in test_part evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_custom_question(
    custom_type: str,
    question_data: Dict,
    user_answer: str,
    user_id: int
) -> Tuple[bool, str]:
    """
    Проверка кастомного вопроса с использованием evaluator соответствующего типа.

    Args:
        custom_type: Тип кастомного вопроса ('test_part', 'task19', 'task20', 'task24', 'task25')
        question_data: Данные кастомного вопроса (включая text, type, correct_answer)
        user_answer: Ответ ученика
        user_id: ID ученика

    Returns:
        Tuple[bool, str]: (is_correct, feedback_text)
    """
    try:
        # Получаем текст вопроса и правильный ответ/критерии из кастомного вопроса
        question_text = question_data.get('text', '')
        correct_answer = question_data.get('correct_answer')

        # Для test_part используем простую проверку
        if custom_type == 'test_part':
            if correct_answer:
                # Если учитель указал правильный ответ, сравниваем
                user_answer_normalized = user_answer.strip().lower().replace(' ', '')
                correct_answer_normalized = str(correct_answer).strip().lower().replace(' ', '')

                is_correct = user_answer_normalized == correct_answer_normalized

                if is_correct:
                    feedback = (
                        "✅ <b>Ответ правильный!</b>\n\n"
                        f"Ваш ответ: <code>{user_answer}</code>\n"
                        f"Правильный ответ: <code>{correct_answer}</code>"
                    )
                else:
                    feedback = (
                        "❌ <b>Ответ неправильный</b>\n\n"
                        f"Ваш ответ: <code>{user_answer}</code>\n"
                        f"Правильный ответ: <code>{correct_answer}</code>"
                    )

                return is_correct, feedback
            else:
                # Если правильный ответ не указан, принимаем ответ без проверки
                feedback = (
                    "✅ <b>Ответ принят</b>\n\n"
                    f"Ваш ответ: <code>{user_answer}</code>\n\n"
                    "💡 Учитель не указал правильный ответ, поэтому ваш ответ принят автоматически."
                )
                return True, feedback

        # Для заданий 19, 20, 24, 25 используем соответствующие AI evaluators
        elif custom_type == 'task19':
            # Формируем question_data для evaluator
            eval_question_data = {
                'title': 'Кастомный вопрос',
                'task_text': question_text
            }

            # Если указаны критерии, добавляем их в feedback
            if correct_answer:
                eval_question_data['criteria'] = correct_answer

            return await _evaluate_task19(eval_question_data, user_answer, user_id)

        elif custom_type == 'task20':
            eval_question_data = {
                'title': 'Кастомный вопрос',
                'task_text': question_text
            }

            if correct_answer:
                eval_question_data['criteria'] = correct_answer

            return await _evaluate_task20(eval_question_data, user_answer, user_id)

        elif custom_type == 'task24':
            eval_question_data = {
                'topic': 'Кастомный план',
                'full_plan': [],
                'points_data': [],
                'min_points': 3,
                'min_detailed_points': 2,
                'min_subpoints': 3
            }

            if correct_answer:
                # Если учитель указал критерии, можем использовать их
                eval_question_data['description'] = f"Критерии: {correct_answer}"

            return await _evaluate_task24(eval_question_data, user_answer, user_id)

        elif custom_type == 'task25':
            eval_question_data = {
                'title': 'Кастомное эссе',
                'task_text': question_text
            }

            if correct_answer:
                eval_question_data['criteria'] = correct_answer

            return await _evaluate_task25(eval_question_data, user_answer, user_id)

        else:
            logger.warning(f"Unknown custom question type: {custom_type}")
            return True, f"✅ Ответ принят (неизвестный тип задания: {custom_type})"

    except Exception as e:
        logger.error(f"Error evaluating custom question: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке кастомного вопроса: {str(e)}"
