"""
Сервис для сохранения и получения результатов проверки вариантов.
"""

import logging
import json
import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.db import DATABASE_FILE
from ..utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


async def ensure_tables():
    """Создаёт таблицу variant_checks если её нет."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS variant_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    teacher_id INTEGER NOT NULL,
                    variant_source TEXT NOT NULL,
                    variant_id TEXT,
                    tasks_checked TEXT NOT NULL,
                    student_name TEXT,
                    results_json TEXT NOT NULL,
                    total_score INTEGER,
                    max_score INTEGER,
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_variant_checks_teacher
                ON variant_checks(teacher_id, created_at DESC)
            """)
            await db.commit()
            logger.debug("variant_checks table ensured")
    except Exception as e:
        logger.error(f"Error ensuring variant_checks table: {e}", exc_info=True)


async def save_variant_check(
    teacher_id: int,
    variant_source: str,
    variant_id: Optional[str],
    tasks_checked: List[int],
    student_name: Optional[str],
    results: Dict[int, Dict],
    total_score: int,
    max_score: int,
) -> Optional[int]:
    """
    Сохраняет результат проверки варианта в БД.

    Returns:
        ID записи или None при ошибке.
    """
    try:
        await ensure_tables()

        # Конвертируем ключи results в строки для JSON
        results_for_json = {str(k): v for k, v in results.items()}

        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                INSERT INTO variant_checks (
                    teacher_id, variant_source, variant_id,
                    tasks_checked, student_name, results_json,
                    total_score, max_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                teacher_id,
                variant_source,
                variant_id,
                json.dumps(tasks_checked),
                student_name,
                json.dumps(results_for_json, ensure_ascii=False),
                total_score,
                max_score,
                utc_now().isoformat(),
            ))
            await db.commit()
            return cursor.lastrowid

    except Exception as e:
        logger.error(f"Error saving variant check: {e}", exc_info=True)
        return None


async def get_variant_check_history(
    teacher_id: int,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Получает историю проверок вариантов."""
    try:
        await ensure_tables()

        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM variant_checks
                WHERE teacher_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (teacher_id, limit))

            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"Error getting variant check history: {e}", exc_info=True)
        return []
