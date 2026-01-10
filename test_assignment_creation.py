#!/usr/bin/env python3
"""
Тестовый скрипт для проверки создания заданий напрямую через API.
Это поможет определить, работает ли создание заданий на уровне сервиса.
"""
import asyncio
import sys
from pathlib import Path

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from teacher_mode.services.assignment_service import create_homework_assignment
from teacher_mode.models import AssignmentType, TargetType
from core.config import DATABASE_FILE

async def test_create_assignment():
    """Тест создания задания напрямую через сервис"""

    print(f"📊 Тестирование создания задания...")
    print(f"   База данных: {DATABASE_FILE}")

    # Тестовые данные
    teacher_id = 149841646
    student_ids = [149841646]  # Используем того же пользователя как студента

    assignment_data = {
        'modules': {
            'test_part': {
                'selection_mode': 'random',
                'selected_ids': [1, 2, 3, 4, 5]
            }
        },
        'questions': [
            {'module': 'test_part', 'question_id': 1},
            {'module': 'test_part', 'question_id': 2},
            {'module': 'test_part', 'question_id': 3},
            {'module': 'test_part', 'question_id': 4},
            {'module': 'test_part', 'question_id': 5}
        ],
        'total_questions': 5
    }

    print(f"\n   Учитель: {teacher_id}")
    print(f"   Студенты: {student_ids}")
    print(f"   Вопросов: {assignment_data['total_questions']}")

    # Создаем задание
    homework = await create_homework_assignment(
        teacher_id=teacher_id,
        title="Тестовое задание",
        assignment_type=AssignmentType.EXISTING_TOPICS,
        assignment_data=assignment_data,
        target_type=TargetType.SPECIFIC_STUDENTS,
        student_ids=student_ids,
        description="Это тестовое задание для проверки функциональности",
        deadline=None
    )

    if homework:
        print(f"\n✅ Задание успешно создано!")
        print(f"   ID: {homework.id}")
        print(f"   Заголовок: {homework.title}")
        print(f"   Создано: {homework.created_at}")

        # Проверяем в базе
        import sqlite3
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM homework_assignments")
        total = cursor.fetchone()[0]
        print(f"\n📊 Всего заданий в базе: {total}")

        cursor.execute("SELECT COUNT(*) FROM homework_student_assignments WHERE homework_id = ?", (homework.id,))
        student_count = cursor.fetchone()[0]
        print(f"   Назначено студентов: {student_count}")

        conn.close()

        return True
    else:
        print("\n❌ Ошибка создания задания!")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_create_assignment())
    sys.exit(0 if success else 1)
