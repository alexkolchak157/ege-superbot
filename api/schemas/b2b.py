"""
Pydantic-схемы для B2B API v1.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class TaskType(str, Enum):
    """Поддерживаемые типы заданий ЕГЭ."""
    TASK19 = "task19"
    TASK20 = "task20"
    TASK21 = "task21"
    TASK22 = "task22"
    TASK23 = "task23"
    TASK24 = "task24"
    TASK25 = "task25"
    CUSTOM = "custom"


class CheckRequest(BaseModel):
    """Запрос на проверку ответа."""
    task_type: TaskType = Field(
        ...,
        description="Тип задания ЕГЭ (task19-task25 или custom)"
    )
    task_text: str = Field(
        ...,
        min_length=10,
        max_length=10000,
        description="Текст задания / условие"
    )
    student_answer: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Ответ ученика"
    )
    student_id: Optional[str] = Field(
        None,
        description="Идентификатор ученика во внешней системе (для аналитики)"
    )


class CheckStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


class CriterionResult(BaseModel):
    """Результат по отдельному критерию."""
    name: str
    score: int
    max_score: int
    comment: str


class CheckResponse(BaseModel):
    """Ответ после создания проверки."""
    check_id: int = Field(..., description="ID проверки")
    status: CheckStatus = Field(..., description="Статус проверки")
    created_at: datetime


class CheckResult(BaseModel):
    """Полный результат проверки."""
    check_id: int
    status: CheckStatus
    task_type: str
    task_text: str
    student_answer: str
    score: Optional[int] = Field(None, description="Набранные баллы")
    max_score: Optional[int] = Field(None, description="Максимальные баллы")
    feedback: Optional[str] = Field(None, description="Текстовый комментарий AI")
    error_message: Optional[str] = None
    processing_time_ms: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class QuestionItem(BaseModel):
    """Вопрос из банка заданий."""
    id: str
    module: str
    title: str
    task_text: str
    topic: Optional[str] = None
    difficulty: Optional[str] = None


class QuestionsResponse(BaseModel):
    """Ответ со списком вопросов."""
    total: int
    questions: List[QuestionItem]


class APIUsageResponse(BaseModel):
    """Информация об использовании API."""
    api_key_name: str
    school_name: Optional[str] = None
    checks_used_this_month: int
    monthly_limit: int
    rate_limit_per_minute: int
