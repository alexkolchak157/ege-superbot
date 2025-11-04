"""
Сервис для работы с домашними заданиями.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any

from ..models import (
    HomeworkAssignment,
    HomeworkStudentAssignment,
    AssignmentType,
    AssignmentStatus,
    StudentAssignmentStatus,
    TargetType
)


async def create_homework_assignment(
    teacher_id: int,
    title: str,
    assignment_type: AssignmentType,
    assignment_data: Dict[str, Any],
    target_type: TargetType,
    student_ids: List[int],
    description: Optional[str] = None,
    deadline: Optional[datetime] = None
) -> HomeworkAssignment:
    """
    Создает домашнее задание.

    Args:
        teacher_id: ID учителя
        title: Название задания
        assignment_type: Тип задания
        assignment_data: Данные задания (JSON)
        target_type: Кому назначено
        student_ids: Список ID учеников
        description: Описание (опционально)
        deadline: Дедлайн (опционально)

    Returns:
        HomeworkAssignment
    """
    # TODO: Сохранить в БД
    homework = HomeworkAssignment(
        id=0,  # AUTO_INCREMENT
        teacher_id=teacher_id,
        created_at=datetime.now(),
        title=title,
        description=description,
        deadline=deadline,
        assignment_type=assignment_type,
        assignment_data=assignment_data,
        target_type=target_type,
        status=AssignmentStatus.ACTIVE
    )

    # TODO: Создать назначения для каждого ученика
    for student_id in student_ids:
        await assign_homework_to_student(homework.id, student_id)

    return homework


async def assign_homework_to_student(
    homework_id: int,
    student_id: int
) -> HomeworkStudentAssignment:
    """
    Назначает задание конкретному ученику.

    Args:
        homework_id: ID задания
        student_id: ID ученика

    Returns:
        HomeworkStudentAssignment
    """
    # TODO: Сохранить в БД
    assignment = HomeworkStudentAssignment(
        id=0,  # AUTO_INCREMENT
        homework_id=homework_id,
        student_id=student_id,
        assigned_at=datetime.now(),
        status=StudentAssignmentStatus.ASSIGNED
    )

    return assignment


async def get_student_homeworks(student_id: int) -> List[HomeworkAssignment]:
    """
    Получает список домашних заданий ученика.

    Args:
        student_id: ID ученика

    Returns:
        Список HomeworkAssignment
    """
    # TODO: Получить из БД через join с homework_student_assignments
    return []


async def get_homework_by_id(homework_id: int) -> Optional[HomeworkAssignment]:
    """
    Получает домашнее задание по ID.

    Args:
        homework_id: ID задания

    Returns:
        HomeworkAssignment или None
    """
    # TODO: Получить из БД
    return None


async def get_teacher_homeworks(teacher_id: int) -> List[HomeworkAssignment]:
    """
    Получает все домашние задания учителя.

    Args:
        teacher_id: ID учителя

    Returns:
        Список HomeworkAssignment
    """
    # TODO: Получить из БД
    return []


async def update_homework_status(
    homework_id: int,
    status: AssignmentStatus
) -> bool:
    """
    Обновляет статус домашнего задания.

    Args:
        homework_id: ID задания
        status: Новый статус

    Returns:
        True если успешно
    """
    # TODO: Обновить в БД
    return True


async def update_student_assignment_status(
    homework_id: int,
    student_id: int,
    status: StudentAssignmentStatus
) -> bool:
    """
    Обновляет статус выполнения задания учеником.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        status: Новый статус

    Returns:
        True если успешно
    """
    # TODO: Обновить в БД
    return True
