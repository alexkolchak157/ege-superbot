"""
Pydantic schemas для заданий (assignments).
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime


class ModuleSelection(BaseModel):
    """Выбор модуля и вопросов для задания"""
    module_code: str = Field(
        ...,
        description="Код модуля",
        pattern=r'^(test_part|task19|task20|task24|task25)$'
    )
    selection_mode: str = Field(
        ...,
        description="Режим выбора вопросов (all, random, specific)",
        pattern=r'^(all|random|specific)$'
    )
    question_count: Optional[int] = Field(
        None,
        description="Количество вопросов (для режима random)",
        ge=1,
        le=100
    )
    question_ids: Optional[List[str]] = Field(
        None,
        description="ID вопросов (для режима specific)"
    )

    @field_validator('question_ids')
    @classmethod
    def validate_question_ids(cls, v, info):
        """Валидация question_ids в зависимости от selection_mode"""
        values = info.data
        if values.get('selection_mode') == 'specific' and not v:
            raise ValueError('question_ids required for specific selection mode')
        return v

    @field_validator('question_count')
    @classmethod
    def validate_question_count(cls, v, info):
        """Валидация question_count в зависимости от selection_mode"""
        values = info.data
        if values.get('selection_mode') == 'random' and not v:
            raise ValueError('question_count required for random selection mode')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "module_code": "test_part",
                "selection_mode": "random",
                "question_count": 10
            }
        }


class CreateAssignmentRequest(BaseModel):
    """Запрос на создание задания"""
    assignment_type: str = Field(
        ...,
        description="Тип задания (existing_topics, test_part, custom)"
    )
    title: str = Field(
        ...,
        description="Название задания",
        min_length=3,
        max_length=100
    )
    description: Optional[str] = Field(
        None,
        description="Описание задания",
        max_length=500
    )
    deadline: Optional[datetime] = Field(
        None,
        description="Дедлайн выполнения"
    )
    student_ids: List[int] = Field(
        ...,
        description="ID учеников для назначения",
        min_length=1,
        max_length=100
    )
    modules: List[ModuleSelection] = Field(
        ...,
        description="Модули и вопросы для задания",
        min_length=1,
        max_length=5
    )

    @field_validator('deadline')
    @classmethod
    def validate_deadline(cls, v):
        """Валидация дедлайна - не может быть в прошлом"""
        if v and v < datetime.utcnow():
            raise ValueError('Deadline cannot be in the past')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "assignment_type": "existing_topics",
                "title": "Домашнее задание №5",
                "description": "Подготовка к контрольной",
                "deadline": "2025-01-15T23:59:59Z",
                "student_ids": [1, 2, 3],
                "modules": [
                    {
                        "module_code": "test_part",
                        "selection_mode": "random",
                        "question_count": 10
                    },
                    {
                        "module_code": "task19",
                        "selection_mode": "specific",
                        "question_ids": ["task19_45", "task19_67"]
                    }
                ]
            }
        }


class CreateAssignmentResponse(BaseModel):
    """Ответ на создание задания"""
    success: bool = Field(..., description="Успешно ли создано задание")
    assignment_id: int = Field(..., description="ID созданного задания")
    created_at: datetime = Field(..., description="Время создания")
    message: str = Field(..., description="Сообщение о результате")
    students_notified: int = Field(..., description="Количество уведомленных учеников")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "assignment_id": 456,
                "created_at": "2025-12-29T15:30:00Z",
                "message": "Задание успешно создано и отправлено 3 ученикам",
                "students_notified": 3
            }
        }


class Assignment(BaseModel):
    """Информация о задании"""
    id: int = Field(..., description="ID задания")
    teacher_id: int = Field(..., description="ID учителя")
    title: str = Field(..., description="Название задания")
    description: Optional[str] = Field(None, description="Описание")
    deadline: Optional[datetime] = Field(None, description="Дедлайн")
    assignment_type: str = Field(..., description="Тип задания")
    created_at: datetime = Field(..., description="Дата создания")
    status: str = Field(..., description="Статус (active, archived)")
    total_students: int = Field(..., description="Всего назначено ученикам")
    completed_count: int = Field(0, description="Завершили задание")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 456,
                "teacher_id": 123,
                "title": "Домашнее задание №5",
                "description": "Подготовка к контрольной",
                "deadline": "2025-01-15T23:59:59Z",
                "assignment_type": "existing_topics",
                "created_at": "2025-12-29T15:30:00Z",
                "status": "active",
                "total_students": 3,
                "completed_count": 1
            }
        }


class AssignmentsListResponse(BaseModel):
    """Ответ со списком заданий"""
    total: int = Field(..., description="Общее количество заданий")
    assignments: List[Assignment] = Field(..., description="Список заданий")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 15,
                "assignments": [
                    {
                        "id": 456,
                        "teacher_id": 123,
                        "title": "Домашнее задание №5",
                        "description": "Подготовка к контрольной",
                        "deadline": "2025-01-15T23:59:59Z",
                        "assignment_type": "existing_topics",
                        "created_at": "2025-12-29T15:30:00Z",
                        "status": "active",
                        "total_students": 3,
                        "completed_count": 1
                    }
                ]
            }
        }
