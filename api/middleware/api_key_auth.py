"""
Middleware аутентификации по API-ключу для B2B интеграций.

Онлайн-школы получают API-ключ и используют его в заголовке X-API-Key.
Ключ проверяется по хешу в БД, применяются rate-limit и месячные лимиты.
"""

import hashlib
import logging
import time
from collections import defaultdict
from datetime import datetime, date
from typing import Optional, NamedTuple

import aiosqlite
from fastapi import Header, HTTPException, Request

from core.config import DATABASE_FILE

logger = logging.getLogger(__name__)

# In-memory rate limiter (per API key prefix)
_rate_limiter: dict[str, list[float]] = defaultdict(list)


class APIKeyInfo(NamedTuple):
    """Информация об API-ключе после валидации."""
    key_id: int
    school_id: Optional[int]
    name: str
    rate_limit_per_minute: int
    monthly_check_limit: int
    checks_used_this_month: int


def _hash_api_key(key: str) -> str:
    """SHA-256 хеш API-ключа."""
    return hashlib.sha256(key.encode()).hexdigest()


def _check_rate_limit(key_prefix: str, limit_per_minute: int) -> bool:
    """
    Проверяет rate limit для ключа (скользящее окно 60 секунд).

    Returns:
        True если запрос разрешён, False если лимит превышен.
    """
    now = time.time()
    window_start = now - 60.0

    # Очищаем старые записи
    _rate_limiter[key_prefix] = [
        ts for ts in _rate_limiter[key_prefix] if ts > window_start
    ]

    if len(_rate_limiter[key_prefix]) >= limit_per_minute:
        return False

    _rate_limiter[key_prefix].append(now)
    return True


async def validate_api_key(
    x_api_key: str = Header(alias="X-API-Key")
) -> APIKeyInfo:
    """
    FastAPI dependency для валидации B2B API-ключа.

    Использование:
    ```python
    @router.post("/check")
    async def check(api_key: APIKeyInfo = Depends(validate_api_key)):
        ...
    ```

    Проверяет:
    1. Наличие ключа в БД
    2. Активность ключа
    3. Rate limit (запросов в минуту)
    4. Месячный лимит проверок

    Raises:
        HTTPException 401: Невалидный ключ
        HTTPException 403: Ключ деактивирован
        HTTPException 429: Лимит превышен
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    key_hash = _hash_api_key(x_api_key)
    key_prefix = x_api_key[:8] if len(x_api_key) >= 8 else x_api_key

    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row

        row = await db.execute(
            """
            SELECT id, school_id, name, rate_limit_per_minute,
                   monthly_check_limit, checks_used_this_month,
                   current_month_start, is_active
            FROM b2b_api_keys
            WHERE key_hash = ?
            """,
            (key_hash,)
        )
        key_row = await row.fetchone()

        if not key_row:
            logger.warning(f"Invalid API key attempt: prefix={key_prefix}")
            raise HTTPException(status_code=401, detail="Invalid API key")

        if not key_row['is_active']:
            logger.warning(f"Deactivated API key used: id={key_row['id']}")
            raise HTTPException(status_code=403, detail="API key is deactivated")

        # Rate limit
        if not _check_rate_limit(key_prefix, key_row['rate_limit_per_minute']):
            logger.warning(f"Rate limit exceeded for API key id={key_row['id']}")
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {key_row['rate_limit_per_minute']} requests/minute."
            )

        # Месячный лимит — сбрасываем если новый месяц
        checks_used = key_row['checks_used_this_month']
        month_start = key_row['current_month_start']
        today = date.today()

        if month_start is None or str(month_start)[:7] != str(today)[:7]:
            # Новый месяц — сбрасываем счётчик
            await db.execute(
                """
                UPDATE b2b_api_keys
                SET checks_used_this_month = 0, current_month_start = ?
                WHERE id = ?
                """,
                (today.isoformat(), key_row['id'])
            )
            await db.commit()
            checks_used = 0

        if checks_used >= key_row['monthly_check_limit']:
            logger.warning(
                f"Monthly limit reached for API key id={key_row['id']}: "
                f"{checks_used}/{key_row['monthly_check_limit']}"
            )
            raise HTTPException(
                status_code=429,
                detail=f"Monthly check limit reached ({key_row['monthly_check_limit']}). "
                       f"Contact support to increase your limit."
            )

        # Обновляем last_used_at
        await db.execute(
            "UPDATE b2b_api_keys SET last_used_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), key_row['id'])
        )
        await db.commit()

        return APIKeyInfo(
            key_id=key_row['id'],
            school_id=key_row['school_id'],
            name=key_row['name'],
            rate_limit_per_minute=key_row['rate_limit_per_minute'],
            monthly_check_limit=key_row['monthly_check_limit'],
            checks_used_this_month=checks_used,
        )


async def increment_check_count(key_id: int):
    """Увеличивает счётчик использованных проверок для API-ключа."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            "UPDATE b2b_api_keys SET checks_used_this_month = checks_used_this_month + 1 WHERE id = ?",
            (key_id,)
        )
        await db.commit()
