"""
Сервис для работы с домашними заданиями.
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
import aiosqlite

from core.config import DATABASE_FILE
from ..models import (
    HomeworkAssignment,
    HomeworkStudentAssignment,
    AssignmentType,
    AssignmentStatus,
    StudentAssignmentStatus,
    TargetType
)

logger = logging.getLogger(__name__)


async def create_homework_assignment(
    teacher_id: int,
    title: str,
    assignment_type: AssignmentType,
    assignment_data: Dict[str, Any],
    target_type: TargetType,
    student_ids: List[int],
    description: Optional[str] = None,
    deadline: Optional[datetime] = None
) -> Optional[HomeworkAssignment]:
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
        HomeworkAssignment или None при ошибке
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            now = datetime.now()
            assignment_data_json = json.dumps(assignment_data)

            cursor = await db.execute("""
                INSERT INTO homework_assignments
                (teacher_id, created_at, title, description, deadline,
                 assignment_type, assignment_data, target_type, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """, (
                teacher_id,
                now,
                title,
                description,
                deadline.isoformat() if deadline else None,
                assignment_type.value,
                assignment_data_json,
                target_type.value
            ))

            homework_id = cursor.lastrowid

            # Создаём назначения для каждого ученика
            for student_id in student_ids:
                await db.execute("""
                    INSERT INTO homework_student_assignments
                    (homework_id, student_id, assigned_at, status)
                    VALUES (?, ?, ?, 'assigned')
                """, (homework_id, student_id, now))

            await db.commit()

            homework = HomeworkAssignment(
                id=homework_id,
                teacher_id=teacher_id,
                created_at=now,
                title=title,
                description=description,
                deadline=deadline,
                assignment_type=assignment_type,
                assignment_data=assignment_data,
                target_type=target_type,
                status=AssignmentStatus.ACTIVE
            )

            logger.info(f"Создано ДЗ id={homework_id} от учителя {teacher_id} для {len(student_ids)} учеников")
            return homework

    except Exception as e:
        logger.error(f"Ошибка при создании домашнего задания: {e}")
        return None


async def assign_homework_to_student(
    homework_id: int,
    student_id: int
) -> Optional[HomeworkStudentAssignment]:
    """
    Назначает задание конкретному ученику.

    Args:
        homework_id: ID задания
        student_id: ID ученика

    Returns:
        HomeworkStudentAssignment или None при ошибке
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            now = datetime.now()

            cursor = await db.execute("""
                INSERT INTO homework_student_assignments
                (homework_id, student_id, assigned_at, status)
                VALUES (?, ?, ?, 'assigned')
            """, (homework_id, student_id, now))

            await db.commit()

            assignment = HomeworkStudentAssignment(
                id=cursor.lastrowid,
                homework_id=homework_id,
                student_id=student_id,
                assigned_at=now,
                status=StudentAssignmentStatus.ASSIGNED
            )

            logger.info(f"Назначено ДЗ {homework_id} ученику {student_id}")
            return assignment

    except aiosqlite.IntegrityError:
        logger.warning(f"Задание {homework_id} уже назначено ученику {student_id}")
        return None
    except Exception as e:
        logger.error(f"Ошибка при назначении задания ученику: {e}")
        return None


async def get_student_homeworks(student_id: int) -> List[HomeworkStudentAssignment]:
    """
    Получает список домашних заданий ученика с их статусами.

    Args:
        student_id: ID ученика

    Returns:
        Список HomeworkStudentAssignment с заполненными данными о заданиях
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    hsa.id as assignment_id,
                    hsa.homework_id,
                    hsa.student_id,
                    hsa.assigned_at,
                    hsa.completed_at,
                    hsa.status as student_status,
                    ha.teacher_id,
                    ha.created_at,
                    ha.title,
                    ha.description,
                    ha.deadline,
                    ha.assignment_type,
                    ha.assignment_data,
                    ha.target_type,
                    ha.status as homework_status
                FROM homework_student_assignments hsa
                JOIN homework_assignments ha ON hsa.homework_id = ha.id
                WHERE hsa.student_id = ?
                ORDER BY ha.deadline ASC, ha.created_at DESC
            """, (student_id,))

            rows = await cursor.fetchall()

            assignments = []
            for row in rows:
                assignment = HomeworkStudentAssignment(
                    id=row['assignment_id'],
                    homework_id=row['homework_id'],
                    student_id=row['student_id'],
                    assigned_at=datetime.fromisoformat(row['assigned_at']),
                    completed_at=datetime.fromisoformat(row['completed_at']) if row['completed_at'] else None,
                    status=StudentAssignmentStatus(row['student_status'])
                )

                # Добавляем данные о задании для удобства
                assignment.title = row['title']
                assignment.description = row['description']
                assignment.deadline = datetime.fromisoformat(row['deadline']) if row['deadline'] else None
                assignment.assignment_type = AssignmentType(row['assignment_type'])

                assignments.append(assignment)

            return assignments

    except Exception as e:
        logger.error(f"Ошибка при получении заданий ученика: {e}")
        return []


async def get_homework_by_id(homework_id: int) -> Optional[HomeworkAssignment]:
    """
    Получает домашнее задание по ID.

    Args:
        homework_id: ID задания

    Returns:
        HomeworkAssignment или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, teacher_id, created_at, title, description, deadline,
                       assignment_type, assignment_data, target_type, status
                FROM homework_assignments
                WHERE id = ?
            """, (homework_id,))

            row = await cursor.fetchone()
            if not row:
                return None

            return HomeworkAssignment(
                id=row['id'],
                teacher_id=row['teacher_id'],
                created_at=datetime.fromisoformat(row['created_at']),
                title=row['title'],
                description=row['description'],
                deadline=datetime.fromisoformat(row['deadline']) if row['deadline'] else None,
                assignment_type=AssignmentType(row['assignment_type']),
                assignment_data=json.loads(row['assignment_data']),
                target_type=TargetType(row['target_type']),
                status=AssignmentStatus(row['status'])
            )

    except Exception as e:
        logger.error(f"Ошибка при получении задания по ID: {e}")
        return None


async def get_teacher_homeworks(teacher_id: int) -> List[HomeworkAssignment]:
    """
    Получает все домашние задания учителя.

    Args:
        teacher_id: ID учителя

    Returns:
        Список HomeworkAssignment
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, teacher_id, created_at, title, description, deadline,
                       assignment_type, assignment_data, target_type, status
                FROM homework_assignments
                WHERE teacher_id = ?
                ORDER BY created_at DESC
            """, (teacher_id,))

            rows = await cursor.fetchall()

            homeworks = []
            for row in rows:
                homework = HomeworkAssignment(
                    id=row['id'],
                    teacher_id=row['teacher_id'],
                    created_at=datetime.fromisoformat(row['created_at']),
                    title=row['title'],
                    description=row['description'],
                    deadline=datetime.fromisoformat(row['deadline']) if row['deadline'] else None,
                    assignment_type=AssignmentType(row['assignment_type']),
                    assignment_data=json.loads(row['assignment_data']),
                    target_type=TargetType(row['target_type']),
                    status=AssignmentStatus(row['status'])
                )
                homeworks.append(homework)

            return homeworks

    except Exception as e:
        logger.error(f"Ошибка при получении заданий учителя: {e}")
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
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE homework_assignments
                SET status = ?
                WHERE id = ?
            """, (status.value, homework_id))

            await db.commit()

            logger.info(f"Обновлён статус задания {homework_id} на {status.value}")
            return True

    except Exception as e:
        logger.error(f"Ошибка при обновлении статуса задания: {e}")
        return False


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
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Если статус "completed", добавляем время завершения
            if status == StudentAssignmentStatus.COMPLETED:
                await db.execute("""
                    UPDATE homework_student_assignments
                    SET status = ?, completed_at = ?
                    WHERE homework_id = ? AND student_id = ?
                """, (status.value, datetime.now(), homework_id, student_id))
            else:
                await db.execute("""
                    UPDATE homework_student_assignments
                    SET status = ?
                    WHERE homework_id = ? AND student_id = ?
                """, (status.value, homework_id, student_id))

            await db.commit()

            logger.info(f"Обновлён статус задания {homework_id} для ученика {student_id} на {status.value}")
            return True

    except Exception as e:
        logger.error(f"Ошибка при обновлении статуса выполнения: {e}")
        return False


async def get_homework_statistics(homework_id: int) -> Dict[str, Any]:
    """
    Получает статистику по домашнему заданию.

    Args:
        homework_id: ID задания

    Returns:
        Словарь со статистикой
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Получаем количество учеников по статусам
            cursor = await db.execute("""
                SELECT status, COUNT(*) as count
                FROM homework_student_assignments
                WHERE homework_id = ?
                GROUP BY status
            """, (homework_id,))

            rows = await cursor.fetchall()

            stats = {
                'total': 0,
                'assigned': 0,
                'in_progress': 0,
                'completed': 0,
                'checked': 0
            }

            for row in rows:
                stats[row['status']] = row['count']
                stats['total'] += row['count']

            return stats

    except Exception as e:
        logger.error(f"Ошибка при получении статистики задания: {e}")
        return {'total': 0, 'assigned': 0, 'in_progress': 0, 'completed': 0, 'checked': 0}
