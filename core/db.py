# -*- coding: utf-8 -*-
# db.py
import aiosqlite
import logging
from datetime import datetime, timedelta, timezone, date
from typing import Optional, List, Set, Tuple, Dict, Any
from .config import DATABASE_FILE

# --- Логгер ---
logger = logging.getLogger(__name__)

# --- КОНСТАНТЫ ТАБЛИЦ ---
TABLE_PROGRESS = "progress"
TABLE_MISTAKES = "user_mistakes"
TABLE_ANSWERED = "user_answered"
TABLE_USERS = "users"


# --- НОВЫЕ СТОЛБЦЫ ДЛЯ СТРИКОВ ---
# current_daily_streak - текущий дневной стрик
# max_daily_streak - максимальный дневной стрик
# current_correct_streak - текущий стрик правильных ответов подряд
# max_correct_streak - максимальный стрик правильных ответов подряд
# last_activity_date - дата последней активности (для дневного стрика)

_db: aiosqlite.Connection | None = None

async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DATABASE_FILE)
    return _db

async def update_daily_streak(user_id: int) -> Tuple[int, int]:
    """
    Обновляет ДНЕВНОЙ стрик пользователя на основе последней активности.
    Вызывается при КАЖДОМ ответе пользователя.
    Возвращает кортеж (текущий дневной стрик, максимальный дневной стрик) после обновления.
    """
    today = date.today()
    current_daily_streak = 0
    max_daily_streak = 0
    last_activity_date = None

    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Убедимся, что пользователь существует и у него есть нужные колонки
        cursor_check = await db.execute(f"PRAGMA table_info({TABLE_USERS})")
        columns = [row[1] for row in await cursor_check.fetchall()]
        required_cols = ['current_daily_streak', 'max_daily_streak', 'last_activity_date']
        if not all(col in columns for col in required_cols):
             logger.error(f"Отсутствуют необходимые колонки для стрика у user {user_id}. Проверьте init_db.")
             return 0, 0

        # Получаем текущие значения ДНЕВНОГО стрика и дату
        cursor = await db.execute(
            f"SELECT current_daily_streak, max_daily_streak, last_activity_date FROM {TABLE_USERS} WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()

        if row:
            db_current_daily, db_max_daily, last_activity_iso = row
            current_daily_streak = db_current_daily or 0
            max_daily_streak = db_max_daily or 0
            if last_activity_iso:
                try:
                    last_activity_date = date.fromisoformat(last_activity_iso)
                except ValueError:
                    logger.warning(f"Invalid date format '{last_activity_iso}' for user {user_id}. Resetting daily streak.")
                    last_activity_date = None

        # Логика обновления ДНЕВНОГО стрика
        needs_update = False
        if last_activity_date == today:
            logger.debug(f"Daily streak for user {user_id} already updated today.")
            # Дату активности все равно обновим, чтобы она была самой свежей меткой
            # Это нужно, если пользователь начал вчера, продолжил сегодня утром, а потом вечером опять отвечает.
            # Без обновления last_activity_date на следующий день стрик не продолжится.
            needs_update = True # Помечаем, что дату нужно обновить
        elif last_activity_date == today - timedelta(days=1):
            current_daily_streak += 1
            needs_update = True
            logger.info(f"Daily streak continued for user {user_id}. New daily streak: {current_daily_streak}")
        else:
            current_daily_streak = 1
            needs_update = True
            logger.info(f"New daily streak started for user {user_id}.")

        # Обновляем максимальный ДНЕВНОЙ стрик
        if current_daily_streak > max_daily_streak:
            max_daily_streak = current_daily_streak
            needs_update = True
            logger.info(f"New max daily streak for user {user_id}: {max_daily_streak}")

        # Сохраняем обновленные данные (только если стрик изменился или дата обновляется)
        if needs_update:
            try:
                await db.execute(
                    f"""UPDATE {TABLE_USERS} SET
                            current_daily_streak = ?,
                            max_daily_streak = ?,
                            last_activity_date = ?
                        WHERE user_id = ?""",
                    (current_daily_streak, max_daily_streak, today.isoformat(), user_id)
                )
                await db.commit()
            except Exception as update_err:
                 logger.exception(f"Ошибка при обновлении дневного стрика для user {user_id}: {update_err}")
                 # Возвращаем старые значения или 0,0 в случае ошибки
                 return db_current_daily or 0, db_max_daily or 0

    return current_daily_streak, max_daily_streak


    
async def update_correct_streak(user_id: int) -> Tuple[int, int]:
    """
    Увеличивает стрик ПРАВИЛЬНЫХ ОТВЕТОВ ПОДРЯД на 1.
    Вызывается только при ПРАВИЛЬНОМ ответе.
    Возвращает кортеж (текущий стрик правильных ответов, максимальный стрик правильных ответов).
    """
    current_correct_streak = 0
    max_correct_streak = 0
    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Сначала убедимся, что пользователь существует
        await db.execute(
            f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
            (user_id,)
        )
        
        # Убедимся, что колонки существуют
        cursor_check = await db.execute(f"PRAGMA table_info({TABLE_USERS})")
        columns = [row[1] for row in await cursor_check.fetchall()]
        required_cols = ['current_correct_streak', 'max_correct_streak']
        if not all(col in columns for col in required_cols):
             logger.error(f"Отсутствуют необходимые колонки для стрика верных ответов у user {user_id}.")
             return 0, 0

        # Получаем текущие значения
        cursor = await db.execute(
            f"SELECT current_correct_streak, max_correct_streak FROM {TABLE_USERS} WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        
        if row:
            db_current_correct = row[0] if row[0] is not None else 0
            db_max_correct = row[1] if row[1] is not None else 0
        else:
            db_current_correct = 0
            db_max_correct = 0

        # Увеличиваем текущий стрик
        current_correct_streak = db_current_correct + 1
        logger.info(f"Correct answer streak incremented for user {user_id}: {db_current_correct} -> {current_correct_streak}")

        # Обновляем максимальный стрик
        max_correct_streak = max(db_max_correct, current_correct_streak)
        if current_correct_streak > db_max_correct:
            logger.info(f"New max correct answer streak for user {user_id}: {max_correct_streak}")

        # Сохраняем
        try:
            await db.execute(
                f"""UPDATE {TABLE_USERS} SET
                        current_correct_streak = ?,
                        max_correct_streak = ?
                    WHERE user_id = ?""",
                (current_correct_streak, max_correct_streak, user_id)
            )
            await db.commit()
            return current_correct_streak, max_correct_streak
        except Exception as update_err:
             logger.exception(f"Ошибка при обновлении стрика правильных ответов для user {user_id}: {update_err}")
             return db_current_correct, db_max_correct



async def reset_correct_streak(user_id: int) -> None:
    """
    Сбрасывает стрик ПРАВИЛЬНЫХ ОТВЕТОВ ПОДРЯД до 0, сохраняя максимальный стрик.
    Вызывается при НЕПРАВИЛЬНОМ ответе.
    """
    async with aiosqlite.connect(DATABASE_FILE) as db:
        try:
            # Перед сбросом проверяем, существует ли колонка
            cursor_check = await db.execute(f"PRAGMA table_info({TABLE_USERS})")
            columns = [row[1] for row in await cursor_check.fetchall()]
            if 'current_correct_streak' in columns:
                await db.execute(
                    f"UPDATE {TABLE_USERS} SET current_correct_streak = 0 WHERE user_id = ?",
                    (user_id,)
                )
                await db.commit()
                logger.info(f"Correct answer streak reset to 0 for user {user_id}.")
            else:
                logger.warning(f"Column 'current_correct_streak' not found for user {user_id} during reset. Skipping.")
        except aiosqlite.Error as e:
             logger.error(f"DB Error resetting correct streak for user {user_id}: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error resetting correct streak for user {user_id}: {e}")

async def get_user_streaks(user_id: int) -> Dict[str, int]:
    """Возвращает словарь с текущими и максимальными стриками пользователя."""
    streaks = {
        'current_daily': 0, 'max_daily': 0,
        'current_correct': 0, 'max_correct': 0
    }
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
                # Проверяем, что значения не None перед использованием
                streaks['current_daily'] = row[0] if row[0] is not None else 0
                streaks['max_daily'] = row[1] if row[1] is not None else 0
                streaks['current_correct'] = row[2] if row[2] is not None else 0
                streaks['max_correct'] = row[3] if row[3] is not None else 0
    except aiosqlite.Error as e:
        logger.error(f"Ошибка SQLite при получении стриков для user {user_id}: {e}")
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка при получении стриков user {user_id}: {e}")
    return streaks


async def init_db():
    """
    Инициализирует базу данных: создает таблицы, добавляет/проверяет столбцы и создает индексы.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # --- 1. Создание таблиц (IF NOT EXISTS) ---
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_PROGRESS} (
                    user_id INTEGER NOT NULL, topic TEXT NOT NULL,
                    correct_count INTEGER DEFAULT 0, total_answered INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, topic) )
            ''')
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_MISTAKES} (
                    user_id INTEGER NOT NULL, question_id TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, question_id) )
            ''')
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_ANSWERED} (
                    user_id INTEGER NOT NULL, question_id TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, question_id) )
            ''')
            # Обновленная структура таблицы users
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_USERS} (
                    user_id INTEGER PRIMARY KEY,
                    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_subscribed BOOLEAN DEFAULT FALSE,
                    subscription_expires DATETIME NULL,
                    monthly_usage_count INTEGER DEFAULT 0,
                    current_month_start DATETIME NULL,
                    current_daily_streak INTEGER DEFAULT 0,    -- Дневной стрик
                    max_daily_streak INTEGER DEFAULT 0,        -- Макс. дневной
                    current_correct_streak INTEGER DEFAULT 0,  -- Стрик верных ответов
                    max_correct_streak INTEGER DEFAULT 0,      -- Макс. стрик верных ответов
                    last_activity_date DATE NULL,             -- Для дневного стрика
                    reminders_enabled BOOLEAN DEFAULT TRUE
                )
            ''')
            logger.info("Проверка/создание таблиц завершено.")

            # --- 2. Добавление/Проверка столбцов (если их нет) ---
            table_columns = {}
            cursor = await db.execute(f"PRAGMA table_info({TABLE_USERS})")
            rows = await cursor.fetchall()
            table_columns[TABLE_USERS] = {row[1] for row in rows} # row[1] - имя столбца

            # Словарь с ожидаемыми колонками и их определениями для ALTER TABLE
            # Определения должны быть совместимы с ALTER TABLE (тип и DEFAULT/NULL)
            all_expected_columns_defs = {
                'user_id': 'INTEGER PRIMARY KEY', # Пропускается в цикле ALTER
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

            for col_name, col_def_full in all_expected_columns_defs.items():
                if "PRIMARY KEY" in col_def_full:
                    continue # Пропускаем первичный ключ

                if col_name not in table_columns[TABLE_USERS]:
                    # Извлекаем определение для ALTER TABLE
                    # Упрощенный парсинг: предполагаем формат "ТИП [DEFAULT ЗНАЧЕНИЕ | NULL]"
                    parts = col_def_full.split(' ', 1) # Разделяем имя (которое мы уже знаем) и остальное
                    col_definition_for_alter = parts[1] if len(parts) > 1 else col_def_full

                    sql_add_column = f"ALTER TABLE {TABLE_USERS} ADD COLUMN {col_name} {col_definition_for_alter}"
                    try:
                        await db.execute(sql_add_column)
                        logger.info(f"Успешно добавлен столбец '{col_name}' в таблицу '{TABLE_USERS}'.")
                    except aiosqlite.Error as e:
                        if "duplicate column name" in str(e).lower():
                            logger.warning(f"Столбец '{col_name}' уже существует в '{TABLE_USERS}' (игнорируем ошибку дубликата).")
                        else:
                            logger.error(f"Ошибка при добавлении столбца '{col_name}' в '{TABLE_USERS}': {e} (SQL: {sql_add_column})")
                else:
                     logger.debug(f"Столбец '{col_name}' уже существует в таблице '{TABLE_USERS}'.")

            # --- 3. Создание индексов (IF NOT EXISTS) ---
            await db.execute(f'CREATE INDEX IF NOT EXISTS idx_{TABLE_PROGRESS}_user_id ON {TABLE_PROGRESS} (user_id)')
            await db.execute(f'CREATE INDEX IF NOT EXISTS idx_{TABLE_MISTAKES}_user_id ON {TABLE_MISTAKES} (user_id)')
            await db.execute(f'CREATE INDEX IF NOT EXISTS idx_{TABLE_ANSWERED}_user_id ON {TABLE_ANSWERED} (user_id)')
            await db.execute(f'CREATE INDEX IF NOT EXISTS idx_{TABLE_MISTAKES}_question_id ON {TABLE_MISTAKES} (question_id)')
            await db.execute(f'CREATE INDEX IF NOT EXISTS idx_{TABLE_ANSWERED}_question_id ON {TABLE_ANSWERED} (question_id)')
            # Можно добавить индекс на last_activity_date для ускорения поиска пользователей для напоминаний
            await db.execute(f'CREATE INDEX IF NOT EXISTS idx_{TABLE_USERS}_last_activity_date ON {TABLE_USERS} (last_activity_date)')
            logger.info("Проверка/создание индексов завершено.")

            # --- 4. Коммит всех изменений ---
            await db.commit()
            logger.info(f"База данных ({DATABASE_FILE}) успешно инициализирована/обновлена.")

    except aiosqlite.Error as e:
        logger.error(f"Ошибка SQLite при инициализации/обновлении базы данных: {e}")
        raise
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка при инициализации/обновлении БД: {e}")
        raise

# --- Остальные функции базы данных (get_or_create_user_status, increment_usage, record_mistake и т.д.) остаются без изменений ---
# (кроме get_user_stats, который мы заменили на get_user_streaks для получения стриков,
# но сама get_user_stats для статистики по темам остается нужна)

async def get_or_create_user_status(user_id: int) -> Dict[str, Any]:
    """
    Получает статус пользователя (подписка, использование).
    Сбрасывает счетчик при смене месяца. Создает пользователя, если его нет.
    """
    now = datetime.now(timezone.utc)
    current_month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    # Добавляем поля стриков со значениями по умолчанию 0
    status = {"user_id": user_id, "is_subscribed": False, "subscription_expires": None,
              "monthly_usage_count": 0, 'current_daily': 0, 'max_daily': 0,
              'current_correct': 0, 'max_correct': 0}
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Убедимся, что пользователь есть, иначе создаем с дефолтными значениями
            await db.execute(f"""INSERT OR IGNORE INTO {TABLE_USERS}
                                (user_id, current_month_start, first_seen)
                                VALUES (?, ?, ?)""",
                             (user_id, current_month_start.isoformat(), now.isoformat()))

            # Получаем все нужные данные
            cursor = await db.execute(f"""
                SELECT is_subscribed, subscription_expires, monthly_usage_count,
                       current_month_start, current_daily_streak, max_daily_streak,
                       current_correct_streak, max_correct_streak
                FROM {TABLE_USERS} WHERE user_id = ? """, (user_id,))
            row = await cursor.fetchone()

            if row:
                is_subscribed, expires_iso, usage, month_start_iso, \
                current_daily, max_daily, current_correct, max_correct = row
                expires = datetime.fromisoformat(expires_iso) if expires_iso else None
                month_start = datetime.fromisoformat(month_start_iso) if month_start_iso else current_month_start

                # Подписка
                if is_subscribed and expires and expires > now:
                    status["is_subscribed"] = True
                    status["subscription_expires"] = expires
                else:
                    if is_subscribed:
                        await db.execute(f"UPDATE {TABLE_USERS} SET is_subscribed = FALSE, subscription_expires = NULL WHERE user_id = ?", (user_id,))
                    status["is_subscribed"] = False

                # Месячный счетчик
                if month_start < current_month_start:
                    logger.info(f"Resetting monthly usage for user {user_id}. Old month: {month_start}, New month: {current_month_start}")
                    await db.execute(f"UPDATE {TABLE_USERS} SET monthly_usage_count = 0, current_month_start = ? WHERE user_id = ?",
                                     (current_month_start.isoformat(), user_id))
                    status["monthly_usage_count"] = 0
                else:
                    status["monthly_usage_count"] = usage if usage is not None else 0

                # Стрики (просто передаем текущие значения из БД)
                status['current_daily'] = current_daily if current_daily is not None else 0
                status['max_daily'] = max_daily if max_daily is not None else 0
                status['current_correct'] = current_correct if current_correct is not None else 0
                status['max_correct'] = max_correct if max_correct is not None else 0
            else:
                 logger.warning(f"User {user_id} not found after INSERT OR IGNORE. Using default status.")

            await db.commit()
        return status
    except Exception as e:
        logger.exception(f"Ошибка получения/создания статуса user {user_id}: {e}")
        return status # Возвращаем дефолтный статус

async def create_users_table():
    await execute_query("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        subscription_status TEXT DEFAULT 'free',
        subscription_end TIMESTAMP DEFAULT NULL,
        is_vip BOOLEAN DEFAULT 0
    );""")

async def set_user_vip(user_id, is_vip=True):
    await execute_query("""
    INSERT INTO users (user_id, is_vip) VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET is_vip=?;
    """, (user_id, is_vip, is_vip))

async def check_user_vip(user_id):
    result = await fetch_one("""
    SELECT is_vip FROM users WHERE user_id=?;
    """, (user_id,))
    return result[0] if result else False


async def increment_usage(user_id: int):
    """Увеличивает месячный счетчик использования на 1."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(f"UPDATE {TABLE_USERS} SET monthly_usage_count = monthly_usage_count + 1 WHERE user_id = ?", (user_id,))
            await db.commit()
    except Exception as e:
        logger.exception(f"Ошибка инкремента использования user {user_id}: {e}")


async def update_progress(user_id: int, topic: str, is_correct: bool):
    """Обновляет прогресс пользователя (правильные/всего)."""
    if not topic or topic == "N/A":
        logger.debug(f"Пропуск записи прогресса для user {user_id} без темы.")
        return
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(f"INSERT OR IGNORE INTO {TABLE_PROGRESS} (user_id, topic) VALUES (?, ?)", (user_id, topic))
            cols_to_update = "correct_count = correct_count + 1, total_answered = total_answered + 1" if is_correct else "total_answered = total_answered + 1"
            await db.execute(f"UPDATE {TABLE_PROGRESS} SET {cols_to_update} WHERE user_id = ? AND topic = ?", (user_id, topic))
            await db.commit()
    except Exception as e:
        logger.exception(f"Ошибка обновления прогресса user {user_id}, topic {topic}: {e}")


async def record_mistake(user_id: int, question_id: str):
    """
    Записывает ID вопроса с ошибкой.
    Если ошибка по этому вопросу уже была, обновляет временную метку.
    """
    if not question_id:
        logger.debug(f"Пропуск записи ошибки для user {user_id} без question_id.")
        return
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(f"""INSERT INTO {TABLE_MISTAKES} (user_id, question_id, timestamp) VALUES (?, ?, CURRENT_TIMESTAMP)
                                 ON CONFLICT(user_id, question_id) DO UPDATE SET timestamp = CURRENT_TIMESTAMP""", (user_id, question_id))
            await db.commit()
    except Exception as e:
        logger.exception(f"Ошибка записи ошибки user {user_id}, question {question_id}: {e}")


async def get_mistake_ids(user_id: int) -> List[str]:
    """Возвращает список ID вопросов с ошибками, отсортированный по времени (старые первыми)."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(f"SELECT question_id FROM {TABLE_MISTAKES} WHERE user_id = ? ORDER BY timestamp ASC", (user_id,))
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
    except aiosqlite.Error as e:
        logger.error(f"Ошибка получения ошибок для user {user_id}: {e}")
        return []
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка при получении ошибок user {user_id}: {e}")
        return []


async def delete_mistake(user_id: int, question_id: str):
    """Удаляет запись об ошибке (например, после правильного ответа в режиме /mistakes)."""
    if not question_id:
        logger.debug(f"Пропуск удаления ошибки для user {user_id} без question_id.")
        return
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(f"DELETE FROM {TABLE_MISTAKES} WHERE user_id = ? AND question_id = ?", (user_id, question_id))
            await db.commit()
            logger.info(f"Mistake {question_id} deleted for user {user_id}")
    except Exception as e:
        logger.exception(f"Ошибка удаления ошибки user {user_id}, question {question_id}: {e}")


async def record_answered(user_id: int, question_id: str):
    """Записывает ID отвеченного вопроса, чтобы не повторять его скоро."""
    if not question_id:
        logger.debug(f"Пропуск записи ответа для user {user_id} без question_id.")
        return
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(f"INSERT OR IGNORE INTO {TABLE_ANSWERED} (user_id, question_id) VALUES (?, ?)", (user_id, question_id))
            await db.commit()
    except Exception as e:
        logger.exception(f"Ошибка записи отвеченного вопроса user {user_id}, question {question_id}: {e}")


async def get_answered_question_ids(user_id: int) -> Set[str]:
    """Возвращает множество (set) ID отвеченных вопросов для быстрой проверки."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(f"SELECT question_id FROM {TABLE_ANSWERED} WHERE user_id = ?", (user_id,))
            rows = await cursor.fetchall()
            return {row[0] for row in rows}
    except aiosqlite.Error as e:
        logger.error(f"Ошибка получения отвеченных вопросов для user {user_id}: {e}")
        return set()
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка при получении отвеченных вопросов user {user_id}: {e}")
        return set()


async def reset_answered_questions(user_id: int):
    """Очищает историю отвеченных вопросов для пользователя."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(f"DELETE FROM {TABLE_ANSWERED} WHERE user_id = ?", (user_id,))
            await db.commit()
            logger.info(f"История ответов для user {user_id} сброшена.")
    except Exception as e:
        logger.exception(f"Ошибка сброса истории ответов user {user_id}: {e}")


async def get_user_stats(user_id: int) -> List[Tuple[str, int, int]]:
    """
    Возвращает статистику пользователя по темам: список кортежей (topic, correct_count, total_answered).
    Исключает темы, где не было ответов. Сортирует по коду темы.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(f""" SELECT topic, correct_count, total_answered FROM {TABLE_PROGRESS}
                                          WHERE user_id = ? AND total_answered > 0 ORDER BY topic ASC """, (user_id,))
            return await cursor.fetchall()
    except aiosqlite.Error as e:
        logger.error(f"Ошибка получения статистики для user {user_id}: {e}")
        return []
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка при получении статистики user {user_id}: {e}")
        return []


async def set_subscription_status(user_id: int, subscribed: bool, expires_at: Optional[datetime] = None):
    """
    Устанавливает статус подписки пользователя.
    """
    expires_iso: Optional[str] = expires_at.isoformat() if expires_at else None
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)", (user_id,))
            await db.execute(f"UPDATE {TABLE_USERS} SET is_subscribed = ?, subscription_expires = ? WHERE user_id = ?",
                             (subscribed, expires_iso, user_id))
            await db.commit()
            logger.info(f"Статус подписки для user {user_id} обновлен: subscribed={subscribed}, expires={expires_iso}")
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка установки статуса подписки user {user_id}: {e}")


async def set_reminders_status(user_id: int, enabled: bool):
    """Включает или выключает напоминания для пользователя."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)", (user_id,))
            await db.execute(f"UPDATE {TABLE_USERS} SET reminders_enabled = ? WHERE user_id = ?", (enabled, user_id))
            await db.commit()
            logger.info(f"Статус напоминаний для user {user_id} установлен в {enabled}")
    except Exception as e:
        logger.exception(f"Ошибка установки статуса напоминаний для user {user_id}: {e}")


async def get_users_for_reminders(inactive_days: int) -> List[int]:
    """
    Возвращает список user_id пользователей, которым нужно отправить напоминание.
    """
    if inactive_days <= 0:
        return []

    cutoff_date = date.today() - timedelta(days=inactive_days)
    cutoff_date_iso = cutoff_date.isoformat()

    user_ids = []
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(f"""
                SELECT user_id FROM {TABLE_USERS}
                WHERE
                    reminders_enabled = TRUE
                    AND (
                        (last_activity_date IS NOT NULL AND last_activity_date < ?)
                        OR
                        (last_activity_date IS NULL AND DATE(first_seen) < ?)
                    )
                """, (cutoff_date_iso, cutoff_date_iso))
            rows = await cursor.fetchall()
            user_ids = [row[0] for row in rows]
            logger.info(f"Найдено пользователей для напоминаний ({inactive_days} дней): {len(user_ids)}")
    except Exception as e:
        logger.exception(f"Ошибка получения пользователей для напоминаний: {e}")

    return user_ids
