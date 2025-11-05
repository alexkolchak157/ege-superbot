"""
Интеграция выполнения домашних заданий с существующими evaluators.

Этот модуль связывает систему домашних заданий учителей
с существующими плагинами (task19, task20, task24, task25).
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from . import assignment_service, progress_tracker
from ..models import AssignmentType, StudentAssignmentStatus

logger = logging.getLogger(__name__)


async def start_homework_session(
    homework_id: int,
    student_id: int,
    context
) -> Optional[Dict[str, Any]]:
    """
    Начинает сессию выполнения домашнего задания.

    Args:
        homework_id: ID домашнего задания
        student_id: ID ученика
        context: Telegram context для сохранения состояния

    Returns:
        Dict с данными задания или None при ошибке
    """
    # Получаем задание
    homework = await assignment_service.get_homework_by_id(homework_id)
    if not homework:
        logger.error(f"Homework {homework_id} not found")
        return None

    # Проверяем, что задание назначено этому ученику
    student_homeworks = await assignment_service.get_student_homeworks(student_id)
    if not any(hw.homework_id == homework_id for hw in student_homeworks):
        logger.warning(f"Homework {homework_id} not assigned to student {student_id}")
        return None

    # Обновляем статус на "in_progress" если был "assigned"
    await assignment_service.update_student_assignment_status(
        homework_id,
        student_id,
        StudentAssignmentStatus.IN_PROGRESS
    )

    # Извлекаем данные задания
    assignment_data = homework.assignment_data
    task_module = assignment_data.get('task_module')  # 'task19', 'task20', etc.
    questions_count = assignment_data.get('questions_count', 10)

    # Сохраняем в контекст для использования в обработчиках
    context.user_data['current_homework'] = {
        'homework_id': homework_id,
        'task_module': task_module,
        'questions_count': questions_count,
        'current_question': 0,
        'title': homework.title
    }

    logger.info(f"Started homework session {homework_id} for student {student_id}")

    return context.user_data['current_homework']


async def save_homework_answer(
    homework_id: int,
    student_id: int,
    question_id: str,
    answer: str,
    is_correct: bool,
    ai_feedback: Optional[str] = None
) -> bool:
    """
    Сохраняет ответ ученика на вопрос домашнего задания.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        question_id: ID вопроса (например, "task19_q1")
        answer: Ответ ученика
        is_correct: Правильный ли ответ
        ai_feedback: Фидбэк от AI

    Returns:
        True при успехе
    """
    progress = await progress_tracker.save_homework_progress(
        homework_id=homework_id,
        student_id=student_id,
        question_id=question_id,
        user_answer=answer,
        is_correct=is_correct,
        ai_feedback=ai_feedback
    )

    if not progress:
        return False

    logger.info(f"Saved answer for homework {homework_id}, student {student_id}, question {question_id}")
    return True


async def check_and_complete_homework(
    homework_id: int,
    student_id: int,
    total_questions: int
) -> bool:
    """
    Проверяет и автоматически завершает задание если все вопросы выполнены.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        total_questions: Общее количество вопросов

    Returns:
        True если задание было завершено
    """
    return await progress_tracker.auto_complete_homework(
        homework_id,
        student_id,
        total_questions
    )


async def get_homework_progress_summary(
    homework_id: int,
    student_id: int
) -> Dict[str, Any]:
    """
    Получает сводку по прогрессу выполнения задания.

    Args:
        homework_id: ID задания
        student_id: ID ученика

    Returns:
        Dict с прогрессом и статистикой
    """
    homework = await assignment_service.get_homework_by_id(homework_id)
    if not homework:
        return {}

    questions_count = homework.assignment_data.get('questions_count', 10)

    completion = await progress_tracker.calculate_homework_completion(
        homework_id,
        student_id,
        questions_count
    )

    performance = await progress_tracker.get_student_performance_summary(
        student_id,
        homework_id
    )

    return {
        'homework_id': homework_id,
        'title': homework.title,
        'deadline': homework.deadline,
        'completion': completion,
        'performance': performance,
        'is_completed': completion['percentage'] >= 100
    }


def get_task_module_callback(task_module: str, is_homework: bool = False) -> str:
    """
    Генерирует callback_data для перехода в модуль задания.

    Args:
        task_module: Код модуля ('task19', 'task20', etc.)
        is_homework: Режим домашнего задания

    Returns:
        Строка callback_data
    """
    if is_homework:
        return f"homework_{task_module}"
    else:
        return f"choose_{task_module}"


# Интеграция с конкретными evaluators


async def evaluate_task19_answer(
    answer: str,
    topic: str,
    **kwargs
) -> tuple[bool, Optional[str]]:
    """
    Проверяет ответ через evaluator task19.

    Args:
        answer: Ответ ученика
        topic: Тема вопроса
        **kwargs: Дополнительные параметры

    Returns:
        Tuple (is_correct, feedback)
    """
    try:
        from task19.evaluator import Task19AIEvaluator, StrictnessLevel

        evaluator = Task19AIEvaluator(strictness=StrictnessLevel.STRICT)
        result = await evaluator.evaluate(answer, topic, **kwargs)

        return result.is_correct, result.feedback

    except Exception as e:
        logger.error(f"Error evaluating task19 answer: {e}")
        return False, "Ошибка при проверке ответа"


async def evaluate_homework_answer(
    task_module: str,
    answer: str,
    question_data: Dict[str, Any]
) -> tuple[bool, Optional[str]]:
    """
    Универсальная функция для проверки ответа на вопрос домашнего задания.

    Args:
        task_module: Модуль задания ('task19', 'task20', etc.)
        answer: Ответ ученика
        question_data: Данные вопроса (topic, question_text, etc.)

    Returns:
        Tuple (is_correct, feedback)
    """
    if task_module == 'task19':
        return await evaluate_task19_answer(
            answer,
            question_data.get('topic', ''),
            **question_data
        )

    # TODO: Добавить интеграцию с task20, task24, task25

    logger.warning(f"Evaluator for {task_module} not implemented")
    return False, "Проверка для этого типа заданий пока не реализована"
