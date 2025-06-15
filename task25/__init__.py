# plugins/task25/__init__.py

from .plugin import setup
from .handlers import Task25Handler
from .evaluator import Task25Evaluator

__all__ = ['setup', 'Task25Handler', 'Task25Evaluator']