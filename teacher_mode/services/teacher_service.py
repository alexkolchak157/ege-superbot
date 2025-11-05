"""
Сервис для работы с учителями.
"""

from __future__ import annotations  # Python 3.8 compatibility

import secrets
import string
import json
import logging
from datetime import datetime
from typing import Optional, List
import aiosqlite

from core.config import DATABASE_FILE
from ..models import TeacherProfile, TeacherStudentRelationship, RelationshipStatus

logger = logging.getLogger(__name__)


def generate_teacher_code() -> str:
    """Генерирует уникальный код учителя формата TEACH-XXXXXX"""
    # 6 символов: буквы и цифры
    code_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"TEACH-{code_part}"


async def create_teacher_profile(
    user_id: int,
    display_name: str,
    subscription_tier: str = 'teacher_basic'
) -> TeacherProfile:
    """
    Создает профиль учителя.

    Args:
        user_id: ID пользователя Telegram
        display_name: Отображаемое имя учителя
        subscription_tier: Уровень подписки

    Returns:
        TeacherProfile
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Генерируем уникальный код
            teacher_code = generate_teacher_code()

            # Проверяем уникальность кода (на случай коллизии)
            while True:
                cursor = await db.execute(
                    "SELECT teacher_code FROM teacher_profiles WHERE teacher_code = ?",
                    (teacher_code,)
                )
                if not await cursor.fetchone():
                    break
                teacher_code = generate_teacher_code()

            # Добавляем роль teacher
            await db.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role) VALUES (?, 'teacher')",
                (user_id,)
            )

            # Создаем профиль учителя
            now = datetime.now()
            feedback_settings_json = json.dumps({})

            await db.execute("""
                INSERT INTO teacher_profiles
                (user_id, teacher_code, display_name, subscription_tier, created_at, feedback_settings)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, teacher_code, display_name, subscription_tier, now, feedback_settings_json))

            await db.commit()

            profile = TeacherProfile(
                user_id=user_id,
                teacher_code=teacher_code,
                display_name=display_name,
                has_active_subscription=False,
                subscription_expires=None,
                subscription_tier=subscription_tier,
                created_at=now,
                feedback_settings={}
            )

            logger.info(f"Создан профиль учителя для user_id={user_id}, код={teacher_code}")
            return profile

    except Exception as e:
        logger.error(f"Ошибка при создании профиля учителя: {e}")
        raise


async def get_teacher_profile(user_id: int) -> Optional[TeacherProfile]:
    """
    Получает профиль учителя по user_id.

    Args:
        user_id: ID пользователя Telegram

    Returns:
        TeacherProfile или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT user_id, teacher_code, display_name, has_active_subscription,
                       subscription_expires, subscription_tier, created_at, feedback_settings
                FROM teacher_profiles
                WHERE user_id = ?
            """, (user_id,))

            row = await cursor.fetchone()
            if not row:
                return None

            return TeacherProfile(
                user_id=row['user_id'],
                teacher_code=row['teacher_code'],
                display_name=row['display_name'],
                has_active_subscription=bool(row['has_active_subscription']),
                subscription_expires=datetime.fromisoformat(row['subscription_expires']) if row['subscription_expires'] else None,
                subscription_tier=row['subscription_tier'],
                created_at=datetime.fromisoformat(row['created_at']),
                feedback_settings=json.loads(row['feedback_settings']) if row['feedback_settings'] else {}
            )

    except Exception as e:
        logger.error(f"Ошибка при получении профиля учителя: {e}")
        return None


async def get_teacher_by_code(teacher_code: str) -> Optional[TeacherProfile]:
    """
    Находит учителя по коду.

    Args:
        teacher_code: Код учителя (например, TEACH-ABC123)

    Returns:
        TeacherProfile или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT user_id, teacher_code, display_name, has_active_subscription,
                       subscription_expires, subscription_tier, created_at, feedback_settings
                FROM teacher_profiles
                WHERE teacher_code = ?
            """, (teacher_code,))

            row = await cursor.fetchone()
            if not row:
                return None

            return TeacherProfile(
                user_id=row['user_id'],
                teacher_code=row['teacher_code'],
                display_name=row['display_name'],
                has_active_subscription=bool(row['has_active_subscription']),
                subscription_expires=datetime.fromisoformat(row['subscription_expires']) if row['subscription_expires'] else None,
                subscription_tier=row['subscription_tier'],
                created_at=datetime.fromisoformat(row['created_at']),
                feedback_settings=json.loads(row['feedback_settings']) if row['feedback_settings'] else {}
            )

    except Exception as e:
        logger.error(f"Ошибка при поиске учителя по коду: {e}")
        return None


async def add_student_to_teacher(
    teacher_id: int,
    student_id: int
) -> Optional[TeacherStudentRelationship]:
    """
    Добавляет ученика к учителю.

    Args:
        teacher_id: ID учителя
        student_id: ID ученика

    Returns:
        TeacherStudentRelationship или None (если превышен лимит)
    """
    try:
        # Проверяем лимит учеников по тарифу
        can_add, reason = await can_add_student(teacher_id)
        if not can_add:
            logger.warning(f"Учитель {teacher_id} не может добавить ученика: {reason}")
            return None

        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Добавляем роль student ученику (если ещё нет)
            await db.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role) VALUES (?, 'student')",
                (student_id,)
            )

            # Создаем связь учитель-ученик
            now = datetime.now()
            cursor = await db.execute("""
                INSERT INTO teacher_student_relationships
                (teacher_id, student_id, invited_at, status)
                VALUES (?, ?, ?, 'active')
            """, (teacher_id, student_id, now))

            await db.commit()

            relationship = TeacherStudentRelationship(
                id=cursor.lastrowid,
                teacher_id=teacher_id,
                student_id=student_id,
                invited_at=now,
                status=RelationshipStatus.ACTIVE
            )

            logger.info(f"Ученик {student_id} добавлен к учителю {teacher_id}")
            return relationship

    except aiosqlite.IntegrityError:
        # Связь уже существует
        logger.warning(f"Связь учитель {teacher_id} - ученик {student_id} уже существует")
        return None
    except Exception as e:
        logger.error(f"Ошибка при добавлении ученика к учителю: {e}")
        return None


async def get_teacher_students(teacher_id: int) -> List[int]:
    """
    Получает список ID учеников учителя.

    Args:
        teacher_id: ID учителя

    Returns:
        Список user_id учеников
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT student_id
                FROM teacher_student_relationships
                WHERE teacher_id = ? AND status = 'active'
            """, (teacher_id,))

            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    except Exception as e:
        logger.error(f"Ошибка при получении списка учеников: {e}")
        return []


async def get_student_teachers(student_id: int) -> List[int]:
    """
    Получает список ID учителей ученика.

    Args:
        student_id: ID ученика

    Returns:
        Список user_id учителей
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT teacher_id
                FROM teacher_student_relationships
                WHERE student_id = ? AND status = 'active'
            """, (student_id,))

            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    except Exception as e:
        logger.error(f"Ошибка при получении списка учителей: {e}")
        return []


async def can_add_student(teacher_id: int) -> tuple[bool, str]:
    """
    Проверяет, может ли учитель добавить еще одного ученика.

    Args:
        teacher_id: ID учителя

    Returns:
        Кортеж (bool, str): (можно добавить, сообщение-причина)
    """
    profile = await get_teacher_profile(teacher_id)
    if not profile:
        return False, "Профиль учителя не найден"

    if not profile.has_active_subscription:
        return False, "У учителя нет активной подписки"

    max_students = profile.max_students
    if max_students == -1:  # Безлимит
        return True, ""

    current_students = await get_teacher_students(teacher_id)
    current_count = len(current_students)

    if current_count >= max_students:
        return False, f"Достигнут лимит учеников ({max_students})"

    return True, ""


async def is_student_connected(teacher_id: int, student_id: int) -> bool:
    """
    Проверяет, подключен ли ученик к учителю.

    Args:
        teacher_id: ID учителя
        student_id: ID ученика

    Returns:
        True если связь существует и активна
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT id FROM teacher_student_relationships
                WHERE teacher_id = ? AND student_id = ? AND status = 'active'
            """, (teacher_id, student_id))

            row = await cursor.fetchone()
            return row is not None

    except Exception as e:
        logger.error(f"Ошибка при проверке связи учитель-ученик: {e}")
        return False
