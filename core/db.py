"""
Модуль работы с базой данных с защитой от SQL injection.
Все SQL запросы используют параметризацию для безопасности.
"""

import os
import logging
from datetime import datetime, date, timezone
from typing import Dict, Any, List, Tuple, Optional, Set
import aiosqlite
from core.config import DATABASE_FILE
from core.types import UserID, TaskType, EvaluationResult, CallbackData
from core import states
import asyncio
logger = logging.getLogger(__name__)

# Имена таблиц - константы для предотвращения injection через имена таблиц
TABLE_PROGRESS = 'user_progress'
TABLE_MISTAKES = 'user_mistakes'
TABLE_ANSWERED = 'answered_questions'
TABLE_USERS = 'users'

# Глобальная переменная для единственного соединения
_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    """Возвращает единственное соединение с БД."""
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DATABASE_FILE)
        _db.row_factory = aiosqlite.Row
    return _db


async def close_db():
    """Закрывает соединение с БД."""
    global _db
    if _db:
        await _db.close()
        _db = None


async def execute_with_retry(query: str, params: tuple = (), max_retries: int = 3):
    """Выполняет запрос с повторными попытками при блокировке БД."""
    
    for attempt in range(max_retries):
        try:
            db = await get_db()
            cursor = await db.execute(query, params)
            await db.commit()
            return cursor
        except aiosqlite.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                logger.warning(f"БД заблокирована, попытка {attempt + 1}/{max_retries}")
                await asyncio.sleep(0.1 * (attempt + 1))  # Экспоненциальная задержка
            else:
                raise


async def init_db():
    """
    Инициализирует базу данных: создает таблицы, добавляет/проверяет столбцы и создает индексы.
    Использует параметризованные запросы где возможно.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # --- 1. Создание таблиц (IF NOT EXISTS) ---
            # Для CREATE TABLE параметризация не требуется, т.к. имена таблиц - константы
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_PROGRESS} (
                    user_id INTEGER NOT NULL, 
                    topic TEXT NOT NULL,
                    correct_count INTEGER DEFAULT 0, 
                    total_answered INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, topic)
                )
            ''')
            
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_MISTAKES} (
                    user_id INTEGER NOT NULL, 
                    question_id TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, question_id)
                )
            ''')
            
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_ANSWERED} (
                    user_id INTEGER NOT NULL, 
                    question_id TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, question_id)
                )
            ''')
            
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_USERS} (
                    user_id INTEGER PRIMARY KEY,
                    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_subscribed BOOLEAN DEFAULT FALSE,
                    subscription_expires DATETIME NULL,
                    monthly_usage_count INTEGER DEFAULT 0,
                    current_month_start DATETIME NULL,
                    current_daily_streak INTEGER DEFAULT 0,
                    max_daily_streak INTEGER DEFAULT 0,
                    current_correct_streak INTEGER DEFAULT 0,
                    max_correct_streak INTEGER DEFAULT 0,
                    last_activity_date DATE NULL,
                    reminders_enabled BOOLEAN DEFAULT TRUE
                )
            ''')
            
            logger.info("Проверка/создание таблиц завершено.")

            # --- 2. Проверка и добавление недостающих столбцов ---
            cursor = await db.execute(f"PRAGMA table_info({TABLE_USERS})")
            rows = await cursor.fetchall()
            existing_columns = {row[1] for row in rows}

            # Столбцы для добавления если отсутствуют
            columns_to_add = {
                'first_seen': 'DATETIME DEFAULT CURRENT_TIMESTAMP',
                'is_subscribed': 'BOOLEAN DEFAULT FALSE',
                'subscription_expires': 'DATETIME NULL',
                'monthly_usage_count': 'INTEGER DEFAULT 0',
                'current_month_start': 'DATETIME NULL',
                'current_daily_streak': 'INTEGER DEFAULT 0',
                'max_daily_streak': 'INTEGER DEFAULT 0',
                'current_correct_streak': 'INTEGER DEFAULT 0',
                'max_correct_streak': 'INTEGER DEFAULT 0',
                'last_activity_date': 'DATE NULL',
                'reminders_enabled': 'BOOLEAN DEFAULT TRUE'
            }

            for col_name, col_def in columns_to_add.items():
                if col_name not in existing_columns:
                    try:
                        # ALTER TABLE безопасен с константными именами таблиц
                        await db.execute(f"ALTER TABLE {TABLE_USERS} ADD COLUMN {col_name} {col_def}")
                        logger.info(f"Добавлен столбец '{col_name}' в таблицу '{TABLE_USERS}'.")
                    except aiosqlite.Error as e:
                        if "duplicate column name" in str(e).lower():
                            logger.debug(f"Столбец '{col_name}' уже существует.")
                        else:
                            logger.error(f"Ошибка при добавлении столбца '{col_name}': {e}")

            # --- 3. Создание индексов ---
            indices = [
                (f'idx_{TABLE_PROGRESS}_user_id', TABLE_PROGRESS, 'user_id'),
                (f'idx_{TABLE_MISTAKES}_user_id', TABLE_MISTAKES, 'user_id'),
                (f'idx_{TABLE_ANSWERED}_user_id', TABLE_ANSWERED, 'user_id'),
                (f'idx_{TABLE_MISTAKES}_question_id', TABLE_MISTAKES, 'question_id'),
                (f'idx_{TABLE_ANSWERED}_question_id', TABLE_ANSWERED, 'question_id'),
                (f'idx_{TABLE_USERS}_last_activity_date', TABLE_USERS, 'last_activity_date')
            ]
            
            for idx_name, table_name, column_name in indices:
                await db.execute(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} ({column_name})')
            
            logger.info("Создание индексов завершено.")

            await db.commit()
            logger.info(f"База данных успешно инициализирована.")

    except Exception as e:
        logger.exception(f"Ошибка при инициализации БД: {e}")
        raise


async def get_or_create_user_status(user_id: int) -> Dict[str, Any]:
    """
    Получает статус пользователя. Создает запись если не существует.
    Использует параметризованные запросы для безопасности.
    """
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id: {user_id}")
        return {"is_subscribed": False, "monthly_usage_count": 0}
    
    try:
        now = datetime.now(timezone.utc)
        today = now.date()
        
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Создаем пользователя если не существует
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            
            # Получаем данные пользователя
            cursor = await db.execute(
                f"""SELECT is_subscribed, subscription_expires, monthly_usage_count, 
                    current_month_start, last_activity_date 
                    FROM {TABLE_USERS} WHERE user_id = ?""",
                (user_id,)
            )
            row = await cursor.fetchone()
            
            if not row:
                return {"is_subscribed": False, "monthly_usage_count": 0}
            
            # Обновляем last_activity_date
            if row['last_activity_date'] != str(today):
                await db.execute(
                    f"UPDATE {TABLE_USERS} SET last_activity_date = ? WHERE user_id = ?",
                    (today, user_id)
                )
            
            # Сброс месячного счетчика если новый месяц
            month_start = row['current_month_start']
            if month_start:
                month_start_dt = datetime.fromisoformat(month_start)
                if month_start_dt.month != now.month or month_start_dt.year != now.year:
                    await db.execute(
                        f"""UPDATE {TABLE_USERS} 
                            SET monthly_usage_count = 0, current_month_start = ? 
                            WHERE user_id = ?""",
                        (now.isoformat(), user_id)
                    )
                    await db.commit()
                    return {"is_subscribed": row['is_subscribed'], "monthly_usage_count": 0}
            else:
                await db.execute(
                    f"UPDATE {TABLE_USERS} SET current_month_start = ? WHERE user_id = ?",
                    (now.isoformat(), user_id)
                )
            
            await db.commit()
            
            # Проверка срока подписки
            is_subscribed = row['is_subscribed']
            if is_subscribed and row['subscription_expires']:
                expires_dt = datetime.fromisoformat(row['subscription_expires'])
                if expires_dt < now:
                    is_subscribed = False
                    await db.execute(
                        f"UPDATE {TABLE_USERS} SET is_subscribed = ? WHERE user_id = ?",
                        (False, user_id)
                    )
                    await db.commit()
            
            return {
                "is_subscribed": is_subscribed,
                "monthly_usage_count": row['monthly_usage_count'] or 0
            }
            
    except Exception as e:
        logger.exception(f"Ошибка получения статуса user {user_id}: {e}")
        return {"is_subscribed": False, "monthly_usage_count": 0}


async def increment_usage(user_id: int):
    """Увеличивает счетчик использования. Безопасно от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id для increment_usage: {user_id}")
        return
        
    try:
        await execute_with_retry(
            f"UPDATE {TABLE_USERS} SET monthly_usage_count = monthly_usage_count + 1 WHERE user_id = ?",
            (user_id,)
        )
    except Exception as e:
        logger.exception(f"Ошибка инкремента использования user {user_id}: {e}")


async def update_progress(user_id: int, topic: str, is_correct: bool):
    """Обновляет прогресс пользователя. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id: {user_id}")
        return
        
    if not topic or not isinstance(topic, str) or topic == "N/A":
        logger.debug(f"Пропуск записи прогресса для user {user_id} без темы.")
        return
    
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Вставляем запись если не существует
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_PROGRESS} (user_id, topic) VALUES (?, ?)",
                (user_id, topic)
            )
            
            # Обновляем счетчики
            if is_correct:
                await db.execute(
                    f"""UPDATE {TABLE_PROGRESS} 
                        SET correct_count = correct_count + 1, 
                            total_answered = total_answered + 1 
                        WHERE user_id = ? AND topic = ?""",
                    (user_id, topic)
                )
            else:
                await db.execute(
                    f"""UPDATE {TABLE_PROGRESS} 
                        SET total_answered = total_answered + 1 
                        WHERE user_id = ? AND topic = ?""",
                    (user_id, topic)
                )
            
            await db.commit()
    except Exception as e:
        logger.exception(f"Ошибка обновления прогресса user {user_id}, topic {topic}: {e}")


async def record_mistake(user_id: int, question_id: str):
    """Записывает ошибку. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id: {user_id}")
        return
        
    if not question_id or not isinstance(question_id, str):
        logger.debug(f"Пропуск записи ошибки для user {user_id} без question_id.")
        return
    
    try:
        await execute_with_retry(
            f"""INSERT INTO {TABLE_MISTAKES} (user_id, question_id, timestamp) 
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, question_id) 
                DO UPDATE SET timestamp = CURRENT_TIMESTAMP""",
            (user_id, question_id)
        )
    except Exception as e:
        logger.exception(f"Ошибка записи ошибки user {user_id}, question {question_id}: {e}")


async def get_mistake_ids(user_id: int) -> List[str]:
    """Возвращает список ID вопросов с ошибками. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id: {user_id}")
        return []
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"SELECT question_id FROM {TABLE_MISTAKES} WHERE user_id = ? ORDER BY timestamp ASC",
                (user_id,)
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
    except Exception as e:
        logger.exception(f"Ошибка получения ошибок user {user_id}: {e}")
        return []

async def get_correct_answers_count(user_id: int) -> int:
    """Возвращает общее количество правильных ответов. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return 0
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"""SELECT SUM(correct_count) 
                    FROM {TABLE_PROGRESS}
                    WHERE user_id = ?""",
                (user_id,)
            )
            result = await cursor.fetchone()
            return result[0] if result and result[0] else 0
            
    except Exception as e:
        logger.exception(f"Ошибка получения количества правильных ответов: {e}")
        return 0


async def get_total_questions_count() -> int:
    """Возвращает общее количество вопросов в базе."""
    # Это заглушка - нужно реализовать подсчет из данных вопросов
    # Временно возвращаем примерное значение
    return 500

async def delete_mistake(user_id: int, question_id: str):
    """Удаляет ошибку из списка. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return
        
    if not question_id or not isinstance(question_id, str):
        return
        
    try:
        await execute_with_retry(
            f"DELETE FROM {TABLE_MISTAKES} WHERE user_id = ? AND question_id = ?",
            (user_id, question_id)
        )
        logger.debug(f"Удалена ошибка {question_id} для user {user_id}")
        
    except Exception as e:
        logger.exception(f"Ошибка удаления ошибки: {e}")


async def record_answered(user_id: int, question_id: str):
    """Записывает отвеченный вопрос. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0 or not question_id:
        return
        
    try:
        await execute_with_retry(
            f"INSERT OR IGNORE INTO {TABLE_ANSWERED} (user_id, question_id) VALUES (?, ?)",
            (user_id, question_id)
        )
    except Exception as e:
        logger.exception(f"Ошибка записи отвеченного вопроса: {e}")


async def get_answered_question_ids(user_id: int) -> Set[str]:
    """Возвращает множество отвеченных вопросов. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return set()
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"SELECT question_id FROM {TABLE_ANSWERED} WHERE user_id = ?",
                (user_id,)
            )
            rows = await cursor.fetchall()
            return {row[0] for row in rows}
    except Exception as e:
        logger.exception(f"Ошибка получения отвеченных вопросов: {e}")
        return set()


async def reset_answered_questions(user_id: int):
    """Очищает историю отвеченных вопросов. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return
        
    try:
        await execute_with_retry(
            f"DELETE FROM {TABLE_ANSWERED} WHERE user_id = ?",
            (user_id,)
        )
        logger.info(f"История ответов для user {user_id} сброшена.")
    except Exception as e:
        logger.exception(f"Ошибка сброса истории: {e}")


async def get_user_stats(user_id: int) -> List[Tuple[str, int, int]]:
    """Возвращает статистику по темам. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return []
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"""SELECT topic, correct_count, total_answered 
                    FROM {TABLE_PROGRESS}
                    WHERE user_id = ? AND total_answered > 0 
                    ORDER BY topic ASC""",
                (user_id,)
            )
            return await cursor.fetchall()
    except Exception as e:
        logger.exception(f"Ошибка получения статистики: {e}")
        return []


async def set_subscription_status(user_id: int, subscribed: bool, expires_at: Optional[datetime] = None):
    """Устанавливает статус подписки. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return
        
    expires_iso = expires_at.isoformat() if expires_at else None
    
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            await db.execute(
                f"""UPDATE {TABLE_USERS} 
                    SET is_subscribed = ?, subscription_expires = ? 
                    WHERE user_id = ?""",
                (subscribed, expires_iso, user_id)
            )
            await db.commit()
            logger.info(f"Статус подписки для user {user_id} обновлен")
    except Exception as e:
        logger.exception(f"Ошибка установки подписки: {e}")


async def set_reminders_status(user_id: int, enabled: bool):
    """Включает/выключает напоминания. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            await db.execute(
                f"UPDATE {TABLE_USERS} SET reminders_enabled = ? WHERE user_id = ?",
                (enabled, user_id)
            )
            await db.commit()
            logger.info(f"Статус напоминаний для user {user_id}: {enabled}")
    except Exception as e:
        logger.exception(f"Ошибка установки напоминаний: {e}")


async def get_users_for_reminders(inactive_days: int) -> List[int]:
    """Возвращает пользователей для напоминаний. Защищено от SQL injection."""
    if not isinstance(inactive_days, int) or inactive_days < 0:
        inactive_days = 3  # Значение по умолчанию
        
    try:
        threshold_date = (date.today() - timedelta(days=inactive_days)).isoformat()
        
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"""SELECT user_id FROM {TABLE_USERS} 
                    WHERE reminders_enabled = 1 
                    AND last_activity_date <= ?""",
                (threshold_date,)
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
    except Exception as e:
        logger.exception(f"Ошибка получения пользователей для напоминаний: {e}")
        return []


async def update_streak(user_id: int, streak_type: str, value: int):
    """Обновляет значение стрика. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return
        
    if streak_type not in ['daily', 'correct']:
        return
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            
            if streak_type == 'daily':
                await db.execute(
                    f"""UPDATE {TABLE_USERS}
                        SET current_daily_streak = ?,
                            max_daily_streak = MAX(max_daily_streak, ?)
                        WHERE user_id = ?""",
                    (value, value, user_id)
                )
            else:  # correct
                await db.execute(
                    f"""UPDATE {TABLE_USERS}
                        SET current_correct_streak = ?,
                            max_correct_streak = MAX(max_correct_streak, ?)
                        WHERE user_id = ?""",
                    (value, value, user_id)
                )
            
            await db.commit()
            
    except Exception as e:
        logger.exception(f"Ошибка обновления стрика {streak_type} для user {user_id}: {e}")


async def get_user_streaks(user_id: int) -> Dict[str, int]:
    """Получает стрики пользователя. Защищено от SQL injection."""
    streaks = {
        'current_daily': 0, 'max_daily': 0,
        'current_correct': 0, 'max_correct': 0
    }
    
    if not isinstance(user_id, int) or user_id <= 0:
        return streaks
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"""SELECT current_daily_streak, max_daily_streak,
                           current_correct_streak, max_correct_streak
                    FROM {TABLE_USERS} WHERE user_id = ?""",
                (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                streaks['current_daily'] = row[0] or 0
                streaks['max_daily'] = row[1] or 0
                streaks['current_correct'] = row[2] or 0
                streaks['max_correct'] = row[3] or 0
    except Exception as e:
        logger.exception(f"Ошибка получения стриков: {e}")
    
    return streaks


# Добавляем импорт для совместимости


async def update_daily_streak(user_id: int) -> tuple[int, int]:
    """
    Обновляет дневной стрик пользователя.
    Возвращает (текущий_стрик, максимальный_стрик).
    """
    if not isinstance(user_id, int) or user_id <= 0:
        return (0, 0)
    
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Вставляем запись если не существует
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            
            # Получаем текущую дату и последнюю активность
            today = date.today()
            cursor = await db.execute(
                f"SELECT last_activity_date, current_daily_streak, max_daily_streak FROM {TABLE_USERS} WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            
            if row and row[0]:
                last_activity = date.fromisoformat(row[0])
                current_streak = row[1] or 0
                max_streak = row[2] or 0
                
                # Проверяем, нужно ли обновить стрик
                if last_activity == today:
                    # Уже были сегодня
                    return (current_streak, max_streak)
                elif (today - last_activity).days == 1:
                    # Вчера были - продолжаем стрик
                    current_streak += 1
                    max_streak = max(max_streak, current_streak)
                else:
                    # Пропустили день - сбрасываем
                    current_streak = 1
            else:
                # Первый раз
                current_streak = 1
                max_streak = 1
            
            # Обновляем БД
            await db.execute(
                f"""UPDATE {TABLE_USERS} 
                    SET current_daily_streak = ?, 
                        max_daily_streak = ?,
                        last_activity_date = ?
                    WHERE user_id = ?""",
                (current_streak, max_streak, today.isoformat(), user_id)
            )
            await db.commit()
            
            return (current_streak, max_streak)
            
    except Exception as e:
        logger.exception(f"Ошибка обновления дневного стрика: {e}")
        return (0, 0)


async def update_correct_streak(user_id: int) -> tuple[int, int]:
    """
    Увеличивает стрик правильных ответов.
    Возвращает (текущий_стрик, максимальный_стрик).
    """
    if not isinstance(user_id, int) or user_id <= 0:
        return (0, 0)
    
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            
            # Увеличиваем стрик
            await db.execute(
                f"""UPDATE {TABLE_USERS}
                    SET current_correct_streak = current_correct_streak + 1,
                        max_correct_streak = MAX(max_correct_streak, current_correct_streak + 1)
                    WHERE user_id = ?""",
                (user_id,)
            )
            await db.commit()
            
            # Получаем значения
            cursor = await db.execute(
                f"SELECT current_correct_streak, max_correct_streak FROM {TABLE_USERS} WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            
            if row:
                return (row[0] or 0, row[1] or 0)
            return (0, 0)
            
    except Exception as e:
        logger.exception(f"Ошибка обновления стрика правильных ответов: {e}")
        return (0, 0)


async def reset_correct_streak(user_id: int):
    """Сбрасывает стрик правильных ответов."""
    if not isinstance(user_id, int) or user_id <= 0:
        return
    
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                f"UPDATE {TABLE_USERS} SET current_correct_streak = 0 WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()
    except Exception as e:
        logger.exception(f"Ошибка сброса стрика правильных ответов: {e}")

async def reset_user_progress(user_id: int):
    """Полностью сбрасывает прогресс пользователя. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id: {user_id}")
        return
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Удаляем прогресс
            await db.execute(
                f"DELETE FROM {TABLE_PROGRESS} WHERE user_id = ?",
                (user_id,)
            )
            
            # Удаляем ошибки
            await db.execute(
                f"DELETE FROM {TABLE_MISTAKES} WHERE user_id = ?",
                (user_id,)
            )
            
            # Удаляем историю ответов
            await db.execute(
                f"DELETE FROM {TABLE_ANSWERED} WHERE user_id = ?",
                (user_id,)
            )
            
            # Сбрасываем стрики
            await db.execute(
                f"""UPDATE {TABLE_USERS} 
                    SET current_daily_streak = 0,
                        current_correct_streak = 0,
                        monthly_usage_count = 0
                    WHERE user_id = ?""",
                (user_id,)
            )
            
            await db.commit()
            logger.info(f"Прогресс пользователя {user_id} полностью сброшен")
            
    except Exception as e:
        logger.exception(f"Ошибка сброса прогресса для user {user_id}: {e}")

async def ensure_user(user_id: int) -> None:
    """Создает пользователя в БД если он не существует."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            await db.commit()
    except Exception as e:
        logger.exception(f"Ошибка при создании пользователя: {e}")