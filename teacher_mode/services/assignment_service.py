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


async def get_completed_question_ids(homework_id: int, student_id: int) -> List[int]:
    """
    Получает список ID выполненных вопросов для конкретного задания и ученика.

    Args:
        homework_id: ID домашнего задания
        student_id: ID ученика

    Returns:
        Список ID выполненных вопросов
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT question_id
                FROM homework_progress
                WHERE homework_id = ? AND student_id = ?
            """, (homework_id, student_id))

            rows = await cursor.fetchall()
            return [int(row['question_id']) for row in rows]

    except Exception as e:
        logger.error(f"Ошибка при получении выполненных вопросов: {e}")
        return []


async def save_question_progress(homework_id: int, student_id: int, question_id: int,
                                 user_answer: str, is_correct: bool,
                                 ai_feedback: Optional[str] = None) -> bool:
    """
    Сохраняет прогресс выполнения конкретного вопроса.

    Args:
        homework_id: ID домашнего задания
        student_id: ID ученика
        question_id: ID вопроса
        user_answer: Ответ ученика
        is_correct: Правильность ответа
        ai_feedback: Обратная связь от AI (опционально)

    Returns:
        True если успешно сохранено, False иначе
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Сохраняем или обновляем прогресс
            await db.execute("""
                INSERT OR REPLACE INTO homework_progress
                (homework_id, student_id, question_id, user_answer, is_correct, ai_feedback, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (homework_id, student_id, str(question_id), user_answer, is_correct, ai_feedback))

            await db.commit()
            return True

    except Exception as e:
        logger.error(f"Ошибка при сохранении прогресса вопроса: {e}")
        return False


async def get_question_progress(homework_id: int, student_id: int, question_id: int) -> Optional[Dict]:
    """
    Получает прогресс выполнения конкретного вопроса.

    Args:
        homework_id: ID домашнего задания
        student_id: ID ученика
        question_id: ID вопроса

    Returns:
        Словарь с данными прогресса или None если не найдено
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, homework_id, student_id, question_id, user_answer,
                       is_correct, ai_feedback, completed_at
                FROM homework_progress
                WHERE homework_id = ? AND student_id = ? AND question_id = ?
            """, (homework_id, student_id, str(question_id)))

            row = await cursor.fetchone()
            if not row:
                return None

            return {
                'id': row['id'],
                'homework_id': row['homework_id'],
                'student_id': row['student_id'],
                'question_id': row['question_id'],
                'user_answer': row['user_answer'],
                'is_correct': bool(row['is_correct']),
                'ai_feedback': row['ai_feedback'],
                'completed_at': row['completed_at']
            }

    except Exception as e:
        logger.error(f"Ошибка при получении прогресса вопроса: {e}")
        return None


async def get_homework_student_progress(homework_id: int, student_id: int) -> List[Dict]:
    """
    Получает полный прогресс ученика по домашнему заданию.

    Args:
        homework_id: ID домашнего задания
        student_id: ID ученика

    Returns:
        Список словарей с прогрессом по каждому вопросу
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, homework_id, student_id, question_id, user_answer,
                       is_correct, ai_feedback, completed_at
                FROM homework_progress
                WHERE homework_id = ? AND student_id = ?
                ORDER BY completed_at ASC
            """, (homework_id, student_id))

            rows = await cursor.fetchall()

            return [
                {
                    'id': row['id'],
                    'homework_id': row['homework_id'],
                    'student_id': row['student_id'],
                    'question_id': int(row['question_id']),
                    'user_answer': row['user_answer'],
                    'is_correct': bool(row['is_correct']),
                    'ai_feedback': row['ai_feedback'],
                    'completed_at': row['completed_at']
                }
                for row in rows
            ]

    except Exception as e:
        logger.error(f"Ошибка при получении прогресса ученика: {e}")
        return []


async def get_homework_all_progress(homework_id: int) -> Dict[int, List[Dict]]:
    """
    Получает прогресс всех учеников по домашнему заданию.

    Args:
        homework_id: ID домашнего задания

    Returns:
        Словарь {student_id: [список прогресса]}
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, homework_id, student_id, question_id, user_answer,
                       is_correct, ai_feedback, completed_at
                FROM homework_progress
                WHERE homework_id = ?
                ORDER BY student_id, completed_at ASC
            """, (homework_id,))

            rows = await cursor.fetchall()

            # Группируем по student_id
            progress_by_student = {}
            for row in rows:
                student_id = row['student_id']
                if student_id not in progress_by_student:
                    progress_by_student[student_id] = []

                progress_by_student[student_id].append({
                    'id': row['id'],
                    'homework_id': row['homework_id'],
                    'student_id': row['student_id'],
                    'question_id': int(row['question_id']),
                    'user_answer': row['user_answer'],
                    'is_correct': bool(row['is_correct']),
                    'ai_feedback': row['ai_feedback'],
                    'completed_at': row['completed_at']
                })

            return progress_by_student

    except Exception as e:
        logger.error(f"Ошибка при получении прогресса всех учеников: {e}")
        return {}


async def add_teacher_comment(progress_id: int, teacher_comment: str) -> bool:
    """
    Добавляет комментарий учителя к ответу ученика.

    Args:
        progress_id: ID записи в homework_progress
        teacher_comment: Комментарий учителя

    Returns:
        True если успешно, False иначе
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Проверяем, есть ли колонка teacher_comment
            # Если нет, нужно будет добавить через миграцию
            # Пока просто обновим ai_feedback, добавив комментарий
            cursor = await db.execute("""
                SELECT ai_feedback FROM homework_progress WHERE id = ?
            """, (progress_id,))

            row = await cursor.fetchone()
            if not row:
                return False

            current_feedback = row[0] or ""
            updated_feedback = f"{current_feedback}\n\n👨‍🏫 <b>Комментарий учителя:</b>\n{teacher_comment}"

            await db.execute("""
                UPDATE homework_progress
                SET ai_feedback = ?
                WHERE id = ?
            """, (updated_feedback, progress_id))

            await db.commit()
            return True

    except Exception as e:
        logger.error(f"Ошибка при добавлении комментария учителя: {e}")
        return False


async def override_answer_score(progress_id: int, is_correct: bool) -> bool:
    """
    Переоценивает ответ ученика (изменяет статус is_correct).

    Args:
        progress_id: ID записи в homework_progress
        is_correct: Новый статус (True - принят, False - отклонен)

    Returns:
        True если успешно, False иначе
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE homework_progress
                SET is_correct = ?
                WHERE id = ?
            """, (1 if is_correct else 0, progress_id))

            await db.commit()
            return True

    except Exception as e:
        logger.error(f"Ошибка при переоценке ответа: {e}")
        return False


async def get_question_progress_by_id(progress_id: int) -> Optional[Dict]:
    """
    Получает прогресс выполнения вопроса по ID записи.

    Args:
        progress_id: ID записи в homework_progress

    Returns:
        Словарь с данными прогресса или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, homework_id, student_id, question_id, user_answer,
                       is_correct, ai_feedback, completed_at
                FROM homework_progress
                WHERE id = ?
            """, (progress_id,))

            row = await cursor.fetchone()
            if not row:
                return None

            return {
                'id': row['id'],
                'homework_id': row['homework_id'],
                'student_id': row['student_id'],
                'question_id': int(row['question_id']),
                'user_answer': row['user_answer'],
                'is_correct': bool(row['is_correct']),
                'ai_feedback': row['ai_feedback'],
                'completed_at': row['completed_at']
            }

    except Exception as e:
        logger.error(f"Ошибка при получении прогресса по ID: {e}")
        return None


async def get_student_statistics(teacher_id: int, student_id: int) -> Optional[Dict]:
    """
    Получает детальную статистику ученика по всем заданиям учителя.

    Args:
        teacher_id: ID учителя
        student_id: ID ученика

    Returns:
        Словарь со статистикой или None при ошибке
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Получаем все домашние задания учителя для этого ученика
            cursor = await db.execute("""
                SELECT ha.id, ha.title, ha.assignment_type, ha.assignment_data, ha.created_at
                FROM homework_assignments ha
                JOIN homework_student_assignments hsa ON ha.id = hsa.homework_id
                WHERE ha.teacher_id = ? AND hsa.student_id = ?
                ORDER BY ha.created_at DESC
            """, (teacher_id, student_id))

            assignments = await cursor.fetchall()

            if not assignments:
                return {
                    'total_assignments': 0,
                    'completed_assignments': 0,
                    'total_questions': 0,
                    'correct_answers': 0,
                    'incorrect_answers': 0,
                    'accuracy_rate': 0,
                    'assignments_by_module': {},
                    'weak_modules': [],
                    'strong_modules': []
                }

            # Статистика по модулям
            module_stats = {}  # module_name -> {correct: int, incorrect: int, total: int}

            total_assignments = len(assignments)
            completed_assignments = 0
            total_questions = 0
            correct_answers = 0
            incorrect_answers = 0

            for assignment in assignments:
                assignment_id = assignment['id']
                assignment_data = json.loads(assignment['assignment_data'])

                # Получаем прогресс ученика по этому заданию
                progress_cursor = await db.execute("""
                    SELECT question_id, is_correct
                    FROM homework_progress
                    WHERE homework_id = ? AND student_id = ?
                """, (assignment_id, student_id))

                progress_rows = await progress_cursor.fetchall()

                # Определяем модуль задания
                if assignment_data.get('is_custom'):
                    task_module = 'custom'
                elif assignment_data.get('is_mixed'):
                    # Для смешанных заданий учитываем все модули
                    modules_list = [m['task_module'] for m in assignment_data.get('modules', [])]
                else:
                    task_module = assignment_data.get('task_module', 'unknown')
                    modules_list = [task_module]

                # Подсчитываем вопросы
                if assignment_data.get('is_mixed'):
                    assignment_questions = assignment_data.get('total_questions_count', 0)
                elif assignment_data.get('is_custom'):
                    assignment_questions = len(assignment_data.get('custom_questions', []))
                else:
                    assignment_questions = assignment_data.get('questions_count', 0)

                total_questions += assignment_questions

                # Если ученик ответил на все вопросы, считаем задание завершенным
                if len(progress_rows) >= assignment_questions:
                    completed_assignments += 1

                # Подсчитываем правильные/неправильные ответы
                for progress_row in progress_rows:
                    is_correct = bool(progress_row['is_correct'])

                    if is_correct:
                        correct_answers += 1
                    else:
                        incorrect_answers += 1

                    # Обновляем статистику по модулям
                    for module in modules_list:
                        if module not in module_stats:
                            module_stats[module] = {'correct': 0, 'incorrect': 0, 'total': 0}

                        module_stats[module]['total'] += 1
                        if is_correct:
                            module_stats[module]['correct'] += 1
                        else:
                            module_stats[module]['incorrect'] += 1

            # Вычисляем процент правильных ответов
            total_answered = correct_answers + incorrect_answers
            accuracy_rate = (correct_answers / total_answered * 100) if total_answered > 0 else 0

            # Определяем слабые и сильные модули
            weak_modules = []
            strong_modules = []

            for module, stats in module_stats.items():
                if stats['total'] < 3:  # Слишком мало данных для анализа
                    continue

                module_accuracy = (stats['correct'] / stats['total'] * 100) if stats['total'] > 0 else 0

                if module_accuracy < 50:
                    weak_modules.append({
                        'module': module,
                        'accuracy': module_accuracy,
                        'correct': stats['correct'],
                        'total': stats['total']
                    })
                elif module_accuracy >= 80:
                    strong_modules.append({
                        'module': module,
                        'accuracy': module_accuracy,
                        'correct': stats['correct'],
                        'total': stats['total']
                    })

            # Сортируем по точности
            weak_modules.sort(key=lambda x: x['accuracy'])
            strong_modules.sort(key=lambda x: x['accuracy'], reverse=True)

            return {
                'total_assignments': total_assignments,
                'completed_assignments': completed_assignments,
                'total_questions': total_questions,
                'correct_answers': correct_answers,
                'incorrect_answers': incorrect_answers,
                'accuracy_rate': round(accuracy_rate, 1),
                'total_answered': total_answered,
                'assignments_by_module': module_stats,
                'weak_modules': weak_modules[:3],  # Топ-3 слабых
                'strong_modules': strong_modules[:3]  # Топ-3 сильных
            }

    except Exception as e:
        logger.error(f"Ошибка при получении статистики ученика: {e}")
        return None
