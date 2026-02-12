"""
B2B API v1 для онлайн-школ.

Эндпоинты:
- POST /api/v1/check       — отправить ответ на проверку
- GET  /api/v1/check/{id}  — получить результат проверки
- GET  /api/v1/questions    — банк вопросов с фильтрацией
- GET  /api/v1/usage        — статистика использования API-ключа
"""

import logging
import time
from datetime import datetime
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from api.middleware.api_key_auth import APIKeyInfo, validate_api_key, increment_check_count
from api.schemas.b2b import (
    CheckRequest, CheckResponse, CheckResult, CheckStatus,
    QuestionsResponse, QuestionItem, APIUsageResponse,
)
from core.config import DATABASE_FILE
from teacher_mode.services.topics_loader import load_topics_for_module

router = APIRouter()
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# POST /check — отправить ответ на проверку
# ------------------------------------------------------------------

@router.post(
    "/check",
    response_model=CheckResponse,
    summary="Отправить ответ на проверку",
    description=(
        "Принимает текст задания и ответ ученика. "
        "Проверка выполняется синхронно через AI-оценщик. "
        "Результат можно получить по check_id через GET /check/{id}."
    ),
)
async def create_check(
    request: CheckRequest,
    api_key: APIKeyInfo = Depends(validate_api_key),
) -> CheckResponse:
    start_time = time.time()

    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row

        # Создаём запись в логе
        cursor = await db.execute(
            """
            INSERT INTO b2b_check_log
                (api_key_id, school_id, task_type, task_text, student_answer, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
            """,
            (
                api_key.key_id,
                api_key.school_id,
                request.task_type.value,
                request.task_text,
                request.student_answer,
            ),
        )
        check_id = cursor.lastrowid
        await db.commit()

    # Выполняем проверку
    try:
        await _run_check(check_id, request, start_time)
    except Exception as e:
        logger.error(f"Check {check_id} failed: {e}", exc_info=True)
        await _mark_check_error(check_id, str(e))

    # Инкрементируем счётчик использования
    await increment_check_count(api_key.key_id)

    # Возвращаем ID
    return CheckResponse(
        check_id=check_id,
        status=CheckStatus.COMPLETED,
        created_at=datetime.utcnow(),
    )


async def _run_check(check_id: int, request: CheckRequest, start_time: float):
    """Запускает AI-проверку и сохраняет результат."""
    from teacher_mode.services.ai_homework_evaluator import evaluate_homework_answer

    # Обновляем статус на processing
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            "UPDATE b2b_check_log SET status = 'processing' WHERE id = ?",
            (check_id,),
        )
        await db.commit()

    task_module = request.task_type.value
    question_data = {
        "title": f"{task_module} — B2B API check",
        "task_text": request.task_text,
    }

    is_correct, ai_feedback = await evaluate_homework_answer(
        task_module=task_module,
        question_data=question_data,
        user_answer=request.student_answer,
        user_id=0,  # B2B проверка — нет Telegram user_id
    )

    # Определяем баллы из фидбека (по типу задания)
    score, max_score = _extract_score(task_module, is_correct, ai_feedback)

    elapsed_ms = int((time.time() - start_time) * 1000)

    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            """
            UPDATE b2b_check_log
            SET status = 'completed',
                score = ?,
                max_score = ?,
                feedback = ?,
                processing_time_ms = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (score, max_score, ai_feedback, elapsed_ms, datetime.utcnow().isoformat(), check_id),
        )
        await db.commit()


def _extract_score(task_module: str, is_correct: bool, feedback: str) -> tuple[int, int]:
    """Извлекает баллы из результата проверки."""
    max_scores = {
        "task19": 3, "task20": 3, "task21": 3,
        "task22": 4, "task23": 3, "task24": 4, "task25": 6,
        "custom": 1,
    }
    max_score = max_scores.get(task_module, 1)

    if is_correct:
        # Если отмечено как правильное — максимальный балл
        # (evaluate_homework_answer возвращает is_correct=True если score >= 50% max)
        return max_score, max_score

    # Для неправильных — 0 (детальные баллы есть в feedback)
    return 0, max_score


async def _mark_check_error(check_id: int, error_msg: str):
    """Помечает проверку как ошибку."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            """
            UPDATE b2b_check_log
            SET status = 'error', error_message = ?, completed_at = ?
            WHERE id = ?
            """,
            (error_msg[:1000], datetime.utcnow().isoformat(), check_id),
        )
        await db.commit()


# ------------------------------------------------------------------
# GET /check/{check_id} — получить результат проверки
# ------------------------------------------------------------------

@router.get(
    "/check/{check_id}",
    response_model=CheckResult,
    summary="Получить результат проверки",
    description="Возвращает полный результат проверки по ID.",
)
async def get_check_result(
    check_id: int,
    api_key: APIKeyInfo = Depends(validate_api_key),
) -> CheckResult:
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT cl.*, ak.school_id AS key_school_id
            FROM b2b_check_log cl
            JOIN b2b_api_keys ak ON cl.api_key_id = ak.id
            WHERE cl.id = ? AND cl.api_key_id = ?
            """,
            (check_id, api_key.key_id),
        )
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Check not found")

    return CheckResult(
        check_id=row["id"],
        status=CheckStatus(row["status"]),
        task_type=row["task_type"],
        task_text=row["task_text"],
        student_answer=row["student_answer"],
        score=row["score"],
        max_score=row["max_score"],
        feedback=row["feedback"],
        error_message=row["error_message"],
        processing_time_ms=row["processing_time_ms"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


# ------------------------------------------------------------------
# GET /questions — банк вопросов с фильтрацией
# ------------------------------------------------------------------

@router.get(
    "/questions",
    response_model=QuestionsResponse,
    summary="Банк вопросов",
    description=(
        "Возвращает вопросы из банка заданий ЕГЭ с фильтрацией по типу, "
        "поиском по тексту и пагинацией."
    ),
)
async def get_questions(
    api_key: APIKeyInfo = Depends(validate_api_key),
    module: str = Query(
        "task19",
        description="Модуль: task19, task20, task24, task25, test_part",
    ),
    search: Optional[str] = Query(None, description="Поиск по тексту задания"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> QuestionsResponse:
    valid_modules = ["test_part", "task19", "task20", "task24", "task25"]
    if module not in valid_modules:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid module. Must be one of: {', '.join(valid_modules)}",
        )

    topics_data = load_topics_for_module(module)
    if not topics_data or not topics_data.get("topics_by_id"):
        return QuestionsResponse(total=0, questions=[])

    all_topics = list(topics_data["topics_by_id"].values())

    # Фильтрация по поиску
    if search:
        search_lower = search.lower()
        all_topics = [
            t for t in all_topics
            if search_lower in t.get("title", "").lower()
            or search_lower in t.get("task_text", "").lower()
        ]

    total = len(all_topics)
    page = all_topics[offset: offset + limit]

    questions = []
    for t in page:
        q_id = f"{module}_{t.get('id', 'unknown')}"
        questions.append(
            QuestionItem(
                id=q_id,
                module=module,
                title=t.get("title", "Без названия"),
                task_text=t.get("task_text", t.get("text", "")),
                topic=t.get("topic", t.get("block")),
                difficulty=t.get("difficulty", "medium"),
            )
        )

    return QuestionsResponse(total=total, questions=questions)


# ------------------------------------------------------------------
# GET /usage — статистика использования API-ключа
# ------------------------------------------------------------------

@router.get(
    "/usage",
    response_model=APIUsageResponse,
    summary="Статистика использования",
    description="Показывает текущее потребление и лимиты API-ключа.",
)
async def get_usage(
    api_key: APIKeyInfo = Depends(validate_api_key),
) -> APIUsageResponse:
    school_name = None
    if api_key.school_id:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT name FROM schools WHERE id = ?", (api_key.school_id,)
            )
            row = await cursor.fetchone()
            if row:
                school_name = row["name"]

    return APIUsageResponse(
        api_key_name=api_key.name,
        school_name=school_name,
        checks_used_this_month=api_key.checks_used_this_month,
        monthly_limit=api_key.monthly_check_limit,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
    )
