"""
Обработчики для режима учителя.
"""

from . import teacher_handlers
from . import student_handlers
from . import assignment_handlers
from . import analytics_handlers

__all__ = [
    'teacher_handlers',
    'student_handlers',
    'assignment_handlers',
    'analytics_handlers',
]
