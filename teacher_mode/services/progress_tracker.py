"""
Сервис для отслеживания прогресса выполнения заданий.
"""

from datetime import datetime
from typing import List, Optional

from ..models import HomeworkProgress


async def save_homework_progress(
    homework_id: int,
    student_id: int,
    question_id: str,
    user_answer: str,
    is_correct: bool,
    ai_feedback: Optional[str] = None
) -> HomeworkProgress:
    """
    Сохраняет прогресс по одному вопросу.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        question_id: ID вопроса
        user_answer: Ответ ученика
        is_correct: Правильный ли ответ
        ai_feedback: Фидбэк от AI (опционально)

    Returns:
        HomeworkProgress
    """
    # TODO: Сохранить в БД
    progress = HomeworkProgress(
        id=0,  # AUTO_INCREMENT
        homework_id=homework_id,
        student_id=student_id,
        question_id=question_id,
        user_answer=user_answer,
        is_correct=is_correct,
        ai_feedback=ai_feedback,
        completed_at=datetime.now()
    )

    return progress


async def get_homework_progress(
    homework_id: int,
    student_id: int
) -> List[HomeworkProgress]:
    """
    Получает прогресс ученика по заданию.

    Args:
        homework_id: ID задания
        student_id: ID ученика

    Returns:
        Список HomeworkProgress
    """
    # TODO: Получить из БД
    return []


async def calculate_homework_completion(
    homework_id: int,
    student_id: int,
    total_questions: int
) -> dict:
    """
    Вычисляет процент выполнения задания.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        total_questions: Всего вопросов в задании

    Returns:
        Dict с completed, total, percentage, correct, incorrect
    """
    progress = await get_homework_progress(homework_id, student_id)

    completed = len(progress)
    correct = sum(1 for p in progress if p.is_correct)
    incorrect = completed - correct
    percentage = (completed / total_questions * 100) if total_questions > 0 else 0

    return {
        'completed': completed,
        'total': total_questions,
        'percentage': round(percentage, 2),
        'correct': correct,
        'incorrect': incorrect
    }


async def is_homework_completed(
    homework_id: int,
    student_id: int,
    total_questions: int
) -> bool:
    """
    Проверяет, завершено ли задание учеником.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        total_questions: Всего вопросов в задании

    Returns:
        True если все вопросы выполнены
    """
    completion = await calculate_homework_completion(homework_id, student_id, total_questions)
    return completion['completed'] >= total_questions
